from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Place, RouteInfo, ZoneWeather
from app.zones import ZONES

TODAY = date.today()
GOOD_WEATHER = ZoneWeather(
    precip_14d_mm=65,
    rain_days_14d=5,
    precip_target_mm=0,
    temp_max_c=15,
    temp_min_c=8,
    rh_mean_pct=80,
    source="forecast",
)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fake_externals(monkeypatch):
    async def fake_weather(client_, lat, lon, target, today=None):
        precip = 90.0 if lat > 42.0 else 20.0
        return ZoneWeather(
            precip_14d_mm=precip,
            rain_days_14d=5,
            temp_max_c=15,
            temp_min_c=8,
            rh_mean_pct=80,
            source="forecast",
        )

    async def fake_routes(client_, lat, lon, zones):
        return {
            z.id: RouteInfo(
                distance_km=10.0 + z.lat,
                duration_min=20.0 + z.lat,
                source="osrm",
            )
            for z in zones
        }

    monkeypatch.setattr("app.main.weather.fetch_zone_weather", fake_weather)
    monkeypatch.setattr("app.main.routing.fetch_route_table", fake_routes)


class TestBasics:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["zones"] == len(ZONES)

    def test_zones_list(self, client):
        r = client.get("/api/zones")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == len(body["zones"]) >= 150
        first = body["zones"][0]
        for field in ("area", "walk_min", "access"):
            assert field in first

    def test_zone_detail(self, client):
        r = client.get("/api/zone/obaga-del-bac-broadleaf")
        assert r.status_code == 200
        assert r.json()["comarca"] == "Ripollès"
        assert "Directions" not in r.json()["access"]
        assert r.json()["walk_min"] >= 0

    def test_zone_detail_404(self, client):
        assert client.get("/api/zone/nope").status_code == 404

    def test_index_served(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Rovelló Tracker" in r.text
        assert "lang-switch" in r.text
        assert 'data-i18n="searchBtn"' in r.text
        assert 'id="weights-panel"' in r.text
        assert 'id="w-preset-balanced"' in r.text

    def test_static_assets(self, client):
        assert client.get("/static/app.js").status_code == 200
        js = client.get("/static/app.js").text
        assert '"ca"' in js and '"es"' in js
        assert "sectorPolygon" in js
        assert "rank-label" in js
        assert "applyWeights" in js
        assert "DEFAULT_WEIGHTS" in js
        assert client.get("/static/style.css").status_code == 200
        css = client.get("/static/style.css").text
        assert "weights-panel" in css


class TestGeocode:
    def test_geocode(self, client, monkeypatch):
        async def fake_geocode(client_, q, limit=8):
            return [Place(name="Vic", admin="Osona", lat=41.93, lon=2.254, country="Espanya")]

        monkeypatch.setattr("app.main.geocoding.geocode", fake_geocode)
        r = client.get("/api/geocode", params={"q": "vic"})
        assert r.status_code == 200
        assert r.json()["results"][0]["name"] == "Vic"

    def test_geocode_too_short(self, client):
        assert client.get("/api/geocode", params={"q": "v"}).status_code == 422


class TestRecommend:
    def test_recommend_happy_path(self, client):
        r = client.get(
            "/api/recommend",
            params={"date": TODAY.isoformat(), "lat": 41.3851, "lon": 2.1734, "limit": 1000},
        )
        assert r.status_code == 200
        body = r.json()
        # the API caps results at 1000 of the 2000 ranked zones
        assert body["count"] == len(body["results"]) == 1000
        overalls = [res["scores"]["overall"] for res in body["results"]]
        assert overalls == sorted(overalls, reverse=True)
        assert [res["rank"] for res in body["results"]] == list(range(1, 1001))
        first = body["results"][0]
        for axis in (
            "rain", "humidity", "temperature", "sunlight", "habitat",
            "season", "crowding", "accessibility", "distance", "overall",
        ):
            assert 0 <= first["scores"][axis] <= 100
        assert first["zone"]["name"]
        assert first["zone"]["area"]
        assert first["zone"]["access"]
        assert 0 <= first["zone"]["walk_min"] <= 180
        assert first["route"]["distance_km"] > 0
        assert first["weather"]["precip_14d_mm"] > 0

    def test_recommend_weather_dedup_per_grid_cell(self, client, monkeypatch):
        calls = []

        async def counting_weather(client_, lat, lon, target, today=None):
            calls.append((lat, lon))
            return ZoneWeather(precip_14d_mm=50, source="forecast")

        monkeypatch.setattr("app.main.weather.fetch_zone_weather", counting_weather)
        r = client.get("/api/recommend", params={"lat": 41.3851, "lon": 2.1734, "limit": 1000})
        assert r.status_code == 200
        assert r.json()["count"] == 1000
        # weather is deduplicated per ~0.1° cell across all 2000 zones
        assert 0 < len(calls) < len(ZONES)
        assert len({(round(lat / 0.1), round(lon / 0.1)) for lat, lon in calls}) == len(calls)

    def test_recommend_north_wins_with_north_rain(self, client):
        r = client.get(
            "/api/recommend",
            params={"lat": 41.3851, "lon": 2.1734},
        )
        assert r.status_code == 200
        results = r.json()["results"]
        assert results[0]["weather"]["precip_14d_mm"] == 90.0

    def test_recommend_temperatures_adjusted_per_zone_elevation(self, client, monkeypatch):
        async def cell_weather(client_, lat, lon, target, today=None):
            return ZoneWeather(
                precip_14d_mm=60,
                rain_days_14d=4,
                precip_target_mm=0,
                temp_max_c=20.0,
                temp_min_c=10.0,
                rh_mean_pct=80,
                grid_elevation_m=500.0,
                source="forecast",
            )

        monkeypatch.setattr("app.main.weather.fetch_zone_weather", cell_weather)
        r = client.get(
            "/api/recommend", params={"lat": 41.3851, "lon": 2.1734, "limit": 1000}
        )
        assert r.status_code == 200
        by_id = {res["zone"]["id"]: res for res in r.json()["results"]}
        low = min(by_id.values(), key=lambda res: res["zone"]["elevation_m"])
        high = max(by_id.values(), key=lambda res: res["zone"]["elevation_m"])
        lapse = 0.0065
        assert low["weather"]["temp_max_c"] == pytest.approx(
            20.0 - (low["zone"]["elevation_m"] - 500) * lapse, abs=0.06
        )
        assert high["weather"]["temp_max_c"] == pytest.approx(
            20.0 - (high["zone"]["elevation_m"] - 500) * lapse, abs=0.06
        )
        assert high["weather"]["temp_max_c"] < low["weather"]["temp_max_c"]

    def test_recommend_limit(self, client):
        r = client.get("/api/recommend", params={"lat": 41.3851, "lon": 2.1734, "limit": 5})
        assert r.status_code == 200
        assert len(r.json()["results"]) == 5

    def test_recommend_custom_weights_rerank(self, client):
        import json as jsonlib

        r = client.get(
            "/api/recommend",
            params={
                "lat": 41.3851,
                "lon": 2.1734,
                "limit": 1000,
                "weights": jsonlib.dumps({"distance": 1.0}),
            },
        )
        assert r.status_code == 200
        results = r.json()["results"]
        first = results[0]
        assert first["scores"]["overall"] == first["scores"]["distance"]
        overalls = [res["scores"]["overall"] for res in results]
        assert overalls == sorted(overalls, reverse=True)

    def test_recommend_custom_weights_partial(self, client):
        import json as jsonlib

        r = client.get(
            "/api/recommend",
            params={
                "lat": 41.3851,
                "lon": 2.1734,
                "weights": jsonlib.dumps({"rain": 3, "distance": 1}),
            },
        )
        assert r.status_code == 200
        first = r.json()["results"][0]
        expected = round(0.75 * first["scores"]["rain"] + 0.25 * first["scores"]["distance"], 1)
        assert abs(first["scores"]["overall"] - expected) < 0.2

    def test_recommend_weights_validation(self, client):
        import json as jsonlib

        base = {"lat": 41.3851, "lon": 2.1734}
        bad_payloads = [
            "not json",
            jsonlib.dumps({"sunlight": 1, "wrong_axis": 1}),
            jsonlib.dumps({"rain": -1}),
            jsonlib.dumps({"rain": 0}),
            jsonlib.dumps({}),
            jsonlib.dumps([1, 2]),
        ]
        for payload in bad_payloads:
            r = client.get("/api/recommend", params={**base, "weights": payload})
            assert r.status_code == 422, payload
            assert "weight" in r.json()["detail"] or "weights" in r.json()["detail"]


    def test_recommend_max_distance(self, client):
        r = client.get("/api/recommend", params={"lat": 41.3851, "lon": 2.1734, "max_distance_km": 52.0})
        assert r.status_code == 200
        for res in r.json()["results"]:
            assert res["route"]["distance_km"] <= 52.0

    def test_recommend_missing_latlon(self, client):
        assert client.get("/api/recommend").status_code == 422

    def test_recommend_outside_catalonia(self, client):
        r = client.get("/api/recommend", params={"lat": 43.5, "lon": 2.0})
        assert r.status_code == 422
        assert "Catalonia" in r.json()["detail"]

    def test_recommend_far_future(self, client):
        future = (TODAY + timedelta(days=40)).isoformat()
        r = client.get("/api/recommend", params={"date": future, "lat": 41.3851, "lon": 2.1734})
        assert r.status_code == 422
        assert "forecast horizon" in r.json()["detail"]

    def test_recommend_far_past(self, client):
        r = client.get("/api/recommend", params={"date": "2010-01-01", "lat": 41.3851, "lon": 2.1734})
        assert r.status_code == 422

    def test_recommend_bad_date_format(self, client):
        r = client.get("/api/recommend", params={"date": "not-a-date", "lat": 41.3851, "lon": 2.1734})
        assert r.status_code == 422
