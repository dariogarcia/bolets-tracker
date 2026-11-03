import dataclasses
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import RouteInfo, Zone, ZoneWeather
from app.mushrooms import ELEVATION_LADDER, MUSHROOMS, availability, get_profile
from app.scoring import (
    compute_scores,
    score_habitat,
    score_season,
    score_temperature,
)
from app.zones import ZONES

SPECIES = {"rovello", "rossinyol", "camagroc", "cep"}

BOUNTIFUL = ZoneWeather(
    precip_14d_mm=70,
    rain_days_14d=5,
    precip_7d_mm=30,
    rain_days_7d=3,
    precip_target_mm=0,
    temp_max_c=16,
    temp_min_c=8,
    rh_mean_pct=80,
    source="forecast",
)


def make_zone(**overrides):
    base = {
        "id": "test",
        "name": "Test",
        "area": "Test · Test",
        "comarca": "Test",
        "lat": 42.0,
        "lon": 1.5,
        "elevation_m": 900,
        "aspect": "N",
        "forest": "Scots pine",
        "cover": "dense",
        "habitat_quality": 5,
        "popularity": 3,
        "accessibility": 7,
        "walk_min": 15,
        "access": "park at the bend and walk north",
        "notes": "test",
    }
    base.update(overrides)
    return Zone(**base)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fake_externals(monkeypatch):
    async def fake_weather(client_, lat, lon, target, today=None):
        return ZoneWeather(
            precip_14d_mm=70,
            rain_days_14d=5,
            temp_max_c=15,
            temp_min_c=8,
            rh_mean_pct=80,
            source="forecast",
        )

    async def fake_routes(client_, lat, lon, zones):
        return {
            z.id: RouteInfo(distance_km=10.0, duration_min=20.0, source="osrm")
            for z in zones
        }

    monkeypatch.setattr("app.main.weather.fetch_zone_weather", fake_weather)
    monkeypatch.setattr("app.main.routing.fetch_route_table", fake_routes)


class TestProfiles:
    def test_four_species(self):
        assert set(MUSHROOMS) == SPECIES

    def test_species_never_own_weights(self):
        # Species needs live in the fit scores, not in ranking weights: the
        # dataclass has no weights field and compute_scores shares WEIGHTS.
        assert not any(f.name == "weights" for m in MUSHROOMS.values() for f in dataclasses.fields(m))

    def test_forest_and_soil_factors_cover_dataset(self):
        groups = {g for z in ZONES for g in z.forest_shares}
        soils = {z.soil for z in ZONES}
        for m in MUSHROOMS.values():
            assert groups <= set(m.forest_factors), m.id
            assert soils <= set(m.soil_factors), m.id

    def test_metadata_complete(self):
        for m in MUSHROOMS.values():
            assert set(m.names) == {"ca", "es", "en"}
            assert m.scientific and m.emoji
            assert set(m.note) == {"ca", "es", "en"}
            assert len(m.temp_ideal) == 2 and m.temp_ideal[0] < m.temp_ideal[1]
            assert set(m.season_windows) == {"high", "mid", "low"}

    def test_unknown_profile_raises(self):
        with pytest.raises(ValueError, match="unknown mushroom"):
            get_profile("moixern")


class TestSeasonBySpecies:
    def test_camagroc_is_the_winter_one(self):
        d = date(2026, 12, 20)
        assert score_season(d, 500, MUSHROOMS["camagroc"].season_windows) > score_season(
            d, 500, MUSHROOMS["rovello"].season_windows
        )

    def test_rossinyol_precedes_rovello(self):
        d = date(2026, 9, 25)
        assert score_season(d, 900, MUSHROOMS["rossinyol"].season_windows) > score_season(
            d, 900, MUSHROOMS["rovello"].season_windows
        )

    def test_cep_is_the_summer_mountain_one(self):
        d = date(2026, 8, 15)
        assert score_season(d, 1250, MUSHROOMS["cep"].season_windows) > score_season(
            d, 1250, MUSHROOMS["rovello"].season_windows
        )

    def test_default_windows_are_rovello(self):
        assert score_season(date(2026, 11, 20), 500) == score_season(
            date(2026, 11, 20), 500, MUSHROOMS["rovello"].season_windows
        )


class TestTemperatureWindows:
    def test_warm_day_suits_rossinyol_not_rovello(self):
        assert score_temperature(24, 12, (14, 24)) > score_temperature(24, 12, (10, 21))

    def test_cold_day_suits_camagroc_not_rovello(self):
        assert score_temperature(8, 2, (6, 16)) > score_temperature(8, 2, (10, 21))

    def test_default_window_unchanged(self):
        assert score_temperature(16, 8) == 100.0
        assert score_temperature(None, None) == 50.0


class TestHabitatBySpecies:
    def test_aleppo_pine_suits_cep_more_than_camagroc(self):
        cep = score_habitat(
            make_zone(forest_shares={"aleppo": 1.0}), MUSHROOMS["cep"].forest_factors
        )
        cam = score_habitat(
            make_zone(forest_shares={"aleppo": 1.0}), MUSHROOMS["camagroc"].forest_factors
        )
        assert cep > cam

    def test_broadleaf_suits_rossinyol_more_than_rovello(self):
        ros = score_habitat(
            make_zone(forest_shares={"broadleaf": 1.0}), MUSHROOMS["rossinyol"].forest_factors
        )
        rov = score_habitat(
            make_zone(forest_shares={"broadleaf": 1.0}), MUSHROOMS["rovello"].forest_factors
        )
        assert ros > rov

    def test_soil_chemistry_shifts_rovello(self):
        acidic = score_habitat(
            make_zone(forest_shares={"scots": 1.0}, soil="acidic"),
            MUSHROOMS["rovello"].forest_factors,
            MUSHROOMS["rovello"].soil_factors,
        )
        basic = score_habitat(
            make_zone(forest_shares={"scots": 1.0}, soil="basic"),
            MUSHROOMS["rovello"].forest_factors,
            MUSHROOMS["rovello"].soil_factors,
        )
        assert acidic > basic

    def test_default_factors_unchanged(self):
        zone = make_zone(forest_shares={"scots": 1.0}, soil="acidic")
        assert score_habitat(zone) == 100.0


class TestComputeScores:
    def test_mushroom_changes_the_ranking_axes(self):
        zone = make_zone(elevation_m=900)
        d = date(2026, 11, 1)
        base = compute_scores(zone, BOUNTIFUL, d, 30.0, mushroom="rovello")
        cep = compute_scores(zone, BOUNTIFUL, d, 30.0, mushroom="cep")
        assert base.season != cep.season

    def test_rovello_default_unchanged(self):
        zone = make_zone()
        d = date(2026, 10, 25)
        assert compute_scores(zone, BOUNTIFUL, d, 30.0) == compute_scores(
            zone, BOUNTIFUL, d, 30.0, mushroom="rovello"
        )


class TestAvailability:
    def test_rovello_peaks_late_october(self):
        av = availability(MUSHROOMS["rovello"], date(2026, 10, 25))
        assert av["status"] == "peak"
        assert av["availability"] >= 80

    def test_camagroc_peaks_december(self):
        av = availability(MUSHROOMS["camagroc"], date(2026, 12, 20))
        assert av["status"] == "peak"

    def test_late_october_favors_rovello_over_camagroc(self):
        d = date(2026, 10, 25)
        assert availability(MUSHROOMS["rovello"], d)["availability"] > availability(
            MUSHROOMS["camagroc"], d
        )["availability"]

    def test_best_elevation_in_ladder(self):
        for m in MUSHROOMS.values():
            av = availability(m, date(2026, 10, 25))
            assert av["best_elevation_m"] in ELEVATION_LADDER
            assert 0 <= av["availability"] <= 100
            assert av["status"] in {"peak", "good", "early", "late", "out"}


class TestMushroomsAPI:
    def test_list(self, client):
        r = client.get("/api/mushrooms?date=2026-10-25")
        assert r.status_code == 200
        body = r.json()
        assert body["date"] == "2026-10-25"
        assert {m["id"] for m in body["mushrooms"]} == SPECIES
        rovello = next(m for m in body["mushrooms"] if m["id"] == "rovello")
        assert rovello["status"] == "peak"
        assert rovello["names"]["ca"] == "Rovelló"
        assert "weights" not in rovello

    def test_list_defaults_to_today(self, client):
        r = client.get("/api/mushrooms")
        assert r.status_code == 200
        assert len(r.json()["mushrooms"]) == 4

    def test_january_is_camagroc_country(self, client):
        r = client.get("/api/mushrooms?date=2027-01-10")
        body = r.json()
        by_id = {m["id"]: m for m in body["mushrooms"]}
        assert by_id["camagroc"]["availability"] > by_id["rossinyol"]["availability"]


class TestRecommendMushroomParam:
    def test_unknown_mushroom_422(self, client):
        r = client.get(
            "/api/recommend",
            params={"lat": 41.3851, "lon": 2.1734, "date": "2026-10-31", "mushroom": "moixern"},
        )
        assert r.status_code == 422
        assert "moixern" in r.json()["detail"]

    def test_mushroom_echoed_and_ranking_differs(self, client):
        common = {"lat": 41.3851, "lon": 2.1734, "date": "2026-10-31", "limit": 20}
        base = client.get("/api/recommend", params={**common, "mushroom": "rovello"}).json()
        cam = client.get("/api/recommend", params={**common, "mushroom": "camagroc"}).json()
        assert base["mushroom"] == "rovello"
        assert cam["mushroom"] == "camagroc"
        top_base = [r["zone"]["id"] for r in base["results"][:10]]
        top_cam = [r["zone"]["id"] for r in cam["results"][:10]]
        assert top_base != top_cam
        # scores come from the species-tuned axes
        for rec in cam["results"]:
            assert 0 <= rec["scores"]["season"] <= 100

    def test_default_is_rovello(self, client):
        r = client.get(
            "/api/recommend",
            params={"lat": 41.3851, "lon": 2.1734, "date": "2026-10-31", "limit": 5},
        )
        assert r.status_code == 200
        assert r.json()["mushroom"] == "rovello"
