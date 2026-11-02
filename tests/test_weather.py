from datetime import date, timedelta

import httpx
import pytest

from app import weather
from app.models import ZoneWeather


def build_daily(start: date, end: date, precip=None, tmax=None, tmin=None, rh=None):
    days, cur = [], start
    while cur <= end:
        days.append(cur.isoformat())
        cur += timedelta(days=1)
    n = len(days)
    return {
        "daily": {
            "time": days,
            "precipitation_sum": precip if precip is not None else [0.0] * n,
            "temperature_2m_max": tmax if tmax is not None else [15.0] * n,
            "temperature_2m_min": tmin if tmin is not None else [7.0] * n,
            "relative_humidity_2m_mean": rh if rh is not None else [75.0] * n,
        }
    }


@pytest.fixture(autouse=True)
def fresh_cache():
    weather.clear_cache()
    yield
    weather.clear_cache()


class TestWeatherMode:
    def test_future_within_horizon_is_forecast(self):
        assert weather.weather_mode(date(2026, 11, 4), date(2026, 10, 31)) == "forecast"

    def test_recent_past_is_forecast(self):
        assert weather.weather_mode(date(2026, 10, 28), date(2026, 10, 31)) == "forecast"

    def test_older_past_is_archive(self):
        assert weather.weather_mode(date(2026, 6, 1), date(2026, 10, 31)) == "archive"

    def test_beyond_horizon_raises(self):
        with pytest.raises(weather.DateTooFarAhead):
            weather.weather_mode(date(2027, 1, 1), date(2026, 10, 31))

    def test_ancient_date_raises(self):
        with pytest.raises(weather.DateTooOld):
            weather.weather_mode(date(2000, 1, 1), date(2026, 10, 31))


class TestFetch:
    async def test_forecast_parse(self):
        today = date(2026, 10, 31)
        target = date(2026, 11, 4)

        def handler(request: httpx.Request) -> httpx.Response:
            assert "forecast" in str(request.url)
            precip = [0.0, 5.0, 0.0, 10.0, 0.0, 0.5, 0.0, 8.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            payload = build_daily(
                date(2026, 10, 21),
                target,
                precip=precip,
                tmax=[15.0] * 14 + [14.0],
                tmin=[7.0] * 14 + [6.0],
                rh=[75.0] * 14 + [78.0],
            )
            return httpx.Response(200, json=payload)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            w = await weather.fetch_zone_weather(client, 42.0, 1.5, target, today)

        assert isinstance(w, ZoneWeather)
        assert w.source == "forecast"
        assert w.precip_14d_mm == 23.5
        assert w.rain_days_14d == 3
        assert w.precip_7d_mm == 8.5
        assert w.rain_days_7d == 1
        assert w.temp_max_c == 14.0
        assert w.temp_min_c == 6.0
        assert w.rh_mean_pct == 78.0

    async def test_cache_hit_single_call(self):
        today = date(2026, 10, 31)
        target = date(2026, 11, 2)
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, json=build_daily(date(2026, 10, 19), target))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            w1 = await weather.fetch_zone_weather(client, 41.5, 1.5, target, today)
            w2 = await weather.fetch_zone_weather(client, 41.5, 1.5, target, today)

        assert len(calls) == 1
        assert w1 == w2

    async def test_network_failure_is_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            w = await weather.fetch_zone_weather(client, 42.0, 1.5, date(2026, 11, 2), date(2026, 10, 31))

        assert w.source == "unavailable"
        assert w.precip_14d_mm is None

    async def test_far_future_rejected_before_request(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request should be made")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(weather.DateTooFarAhead):
                await weather.fetch_zone_weather(
                    client, 42.0, 1.5, date(2027, 5, 1), date(2026, 10, 31)
                )


class TestElevationAdjustment:
    async def test_parse_captures_grid_elevation(self):
        today = date(2026, 10, 31)
        target = date(2026, 11, 2)

        def handler(request: httpx.Request) -> httpx.Response:
            payload = build_daily(date(2026, 10, 19), target)
            payload["elevation"] = 725.5
            return httpx.Response(200, json=payload)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            w = await weather.fetch_zone_weather(client, 42.0, 1.5, target, today)

        assert w.grid_elevation_m == 725.5

    def test_zone_above_grid_cell_gets_colder(self):
        w = ZoneWeather(temp_max_c=20.0, temp_min_c=10.0, grid_elevation_m=600.0)
        adj = weather.adjust_to_elevation(w, 1200.0)
        assert adj.temp_max_c == pytest.approx(20.0 - 600 * 0.0065, abs=0.05)
        assert adj.temp_min_c == pytest.approx(10.0 - 600 * 0.0065, abs=0.05)

    def test_zone_below_grid_cell_gets_warmer(self):
        w = ZoneWeather(temp_max_c=20.0, temp_min_c=10.0, grid_elevation_m=1200.0)
        adj = weather.adjust_to_elevation(w, 600.0)
        assert adj.temp_max_c == pytest.approx(20.0 + 3.9, abs=0.05)
        assert adj.temp_min_c == pytest.approx(10.0 + 3.9, abs=0.05)

    def test_missing_grid_elevation_is_identity(self):
        w = ZoneWeather(temp_max_c=20.0, source="forecast")
        assert weather.adjust_to_elevation(w, 1500.0) is w

    def test_missing_temps_is_identity(self):
        w = ZoneWeather(precip_14d_mm=10.0, grid_elevation_m=600.0)
        assert weather.adjust_to_elevation(w, 1500.0) is w

    def test_input_not_mutated(self):
        w = ZoneWeather(temp_max_c=20.0, temp_min_c=10.0, grid_elevation_m=600.0)
        weather.adjust_to_elevation(w, 1200.0)
        assert w.temp_max_c == 20.0
        assert w.temp_min_c == 10.0
