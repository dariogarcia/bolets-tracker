from datetime import date

from app.models import RouteInfo, Zone, ZoneWeather
from app.scoring import (
    WEIGHTS,
    compute_scores,
    score_accessibility,
    score_crowding,
    score_distance,
    score_habitat,
    score_humidity,
    score_rain,
    score_season,
    score_sunlight,
    score_temperature,
)
from app.zones import ZONES

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


class TestRain:
    def test_no_rain_is_bad(self):
        assert score_rain(0.0, 0, 0.0, 0) == 0.0

    def test_drought_is_bad(self):
        assert score_rain(5.0, 1, 2.0, 1) < 20

    def test_ideal_rain_is_great(self):
        assert score_rain(70.0, 5, 30.0, 3) >= 85
        assert score_rain(100.0, 6, 40.0, 4) >= 90

    def test_extreme_rain_decays_but_not_zero(self):
        assert 55 <= score_rain(350.0, 12, 120.0, 6) < 80

    def test_spread_rain_days_bonus(self):
        assert score_rain(60.0, 6, 25.0, 4) > score_rain(60.0, 1, 25.0, 1)

    def test_recent_rain_matters(self):
        fresh_week = score_rain(70.0, 5, 30.0, 3)
        dry_week = score_rain(70.0, 5, 0.0, 0)
        assert fresh_week > dry_week + 15

    def test_without_7d_data_falls_back_to_14d(self):
        assert score_rain(70.0, 5, None, None) == score_rain(70.0, 5)

    def test_none_is_neutral(self):
        assert score_rain(None, None) == 50


class TestHumidity:
    def test_low_is_bad(self):
        assert score_humidity(30) == 0

    def test_ideal_band(self):
        assert score_humidity(80) >= 80
        assert score_humidity(88) >= 95

    def test_saturated_declines(self):
        assert score_humidity(100) < score_humidity(85)
        assert score_humidity(100) >= 70

    def test_rain_on_the_day_helps(self):
        assert score_humidity(75, 5.0) > score_humidity(75, 0.0)

    def test_none_is_neutral(self):
        assert score_humidity(None) == 50


class TestTemperature:
    def test_ideal_day(self):
        assert score_temperature(15, 7) == 100

    def test_freezing_night_penalised(self):
        warm_day = score_temperature(15, 8)
        frosty_night = score_temperature(15, -6)
        assert frosty_night < warm_day

    def test_hot_day_penalised(self):
        assert score_temperature(29, 20) < 30
        assert score_temperature(36, 28) == 0

    def test_cold_day_penalised(self):
        assert score_temperature(5, 1) < 50
        assert score_temperature(1, -1) == 0

    def test_none_is_neutral(self):
        assert score_temperature(None, None) == 50


class TestHabitat:
    def test_top_zone(self):
        zone = make_zone()
        assert score_habitat(zone) >= 90

    def test_poor_site_lower(self):
        assert score_habitat(make_zone(habitat_quality=2, forest="Aleppo pine")) < score_habitat(
            make_zone()
        )

    def test_scots_beats_aleppo(self):
        scots = score_habitat(make_zone(forest="Scots pine"))
        aleppo = score_habitat(make_zone(forest="Aleppo pine"))
        assert scots > aleppo

    def test_all_dataset_zones_scored(self):
        for z in ZONES:
            s = score_habitat(z)
            assert 0 < s <= 100, z.id


class TestSunlight:
    def test_north_dense_is_shady(self):
        assert score_sunlight(make_zone(aspect="N", cover="dense")) >= 95

    def test_south_open_is_sunny(self):
        assert score_sunlight(make_zone(aspect="S", cover="open")) <= 25

    def test_north_beats_south(self):
        assert score_sunlight(make_zone(aspect="N")) > score_sunlight(make_zone(aspect="S"))

    def test_dense_canopy_helps(self):
        assert score_sunlight(make_zone(cover="dense")) > score_sunlight(make_zone(cover="open"))

    def test_all_dataset_zones_scored(self):
        for z in ZONES:
            s = score_sunlight(z)
            assert 5 <= s <= 100, z.id


class TestSeason:
    def test_high_elevation_peaks_october(self):
        assert score_season(date(2026, 10, 25), 1250) >= 90
        assert score_season(date(2026, 6, 15), 1250) <= 10

    def test_low_elevation_peaks_november(self):
        assert score_season(date(2026, 11, 20), 500) >= 90
        assert score_season(date(2026, 8, 1), 500) <= 10

    def test_never_zero(self):
        assert score_season(date(2026, 2, 1), 900) >= 5

    def test_wraps_year_boundary(self):
        january = score_season(date(2027, 1, 15), 500)
        july = score_season(date(2026, 7, 15), 500)
        assert january > july
        assert january >= 10


class TestCrowdingAndAccess:
    def test_crowding_bounds(self):
        assert score_crowding(1) == 100
        assert score_crowding(10) == 0

    def test_accessibility_bounds(self):
        assert score_accessibility(10) == 100
        assert score_accessibility(1) == 10


class TestDistance:
    def test_short_is_perfect(self):
        assert score_distance(20) == 100

    def test_monotonic_decay(self):
        values = [score_distance(d) for d in (20, 60, 120, 240, 320)]
        assert values == sorted(values, reverse=True)
        assert score_distance(320) == 0


class TestComposite:
    def test_weights_sum_to_one(self):
        assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

    def test_custom_weights_override_overall(self):
        zone = ZONES[0]
        s = compute_scores(zone, BOUNTIFUL, date(2026, 11, 5), 60, weights={"rain": 1.0})
        assert s.overall == s.rain
        s2 = compute_scores(zone, BOUNTIFUL, date(2026, 11, 5), 60, weights={"distance": 1.0})
        assert s2.overall == s2.distance
        assert s.overall != s2.overall

    def test_partial_weights_ignore_other_axes(self):
        zone = ZONES[0]
        s = compute_scores(zone, BOUNTIFUL, date(2026, 11, 5), 60, weights={"rain": 0.5, "season": 0.5})
        assert s.overall == round(0.5 * s.rain + 0.5 * s.season, 1)

    def test_scores_in_bounds(self):
        for z in ZONES:
            s = compute_scores(z, BOUNTIFUL, date(2026, 11, 5), 60)
            for axis in (
                s.rain, s.humidity, s.temperature, s.sunlight, s.habitat,
                s.season, s.crowding, s.accessibility, s.distance, s.overall,
            ):
                assert 0 <= axis <= 100, (z.id, axis)

    def test_better_conditions_rank_higher(self):
        zone = ZONES[0]
        good = compute_scores(zone, BOUNTIFUL, date(2026, 11, 5), 45)
        drought = compute_scores(
            zone,
            ZoneWeather(precip_14d_mm=0, rain_days_14d=0, temp_max_c=25, temp_min_c=15, rh_mean_pct=35, source="forecast"),
            date(2026, 11, 5),
            45,
        )
        far_away = compute_scores(zone, BOUNTIFUL, date(2026, 11, 5), 290)
        assert good.overall > drought.overall
        assert good.overall > far_away.overall

    def test_unavailable_weather_is_neutral(self):
        zone = make_zone()
        unavailable = ZoneWeather(source="unavailable")
        s = compute_scores(zone, unavailable, date(2026, 11, 5), 60)
        assert s.rain == 50
        assert s.humidity == 50
        assert s.temperature == 50

    def test_route_info_model(self):
        r = RouteInfo(distance_km=80.0, duration_min=95.0, source="osrm")
        assert r.source == "osrm"
