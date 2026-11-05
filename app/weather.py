from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta

import httpx

from .models import ZoneWeather

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

DAILY_VARS = "precipitation_sum,temperature_2m_max,temperature_2m_min,relative_humidity_2m_mean"

# Standard atmosphere lapse rate: temperature drops ~6.5 °C per 1000 m of
# elevation gain. Open-Meteo returns temperatures for its grid-cell elevation
# (`payload["elevation"]`); zones above or below that elevation are corrected.
LAPSE_RATE_C_PER_M = 0.0065

FORECAST_HORIZON_DAYS = 15
HISTORY_DAYS = 14
FORECAST_TTL = 1800
ARCHIVE_TTL = 86400

_cache: dict[tuple, tuple[float, ZoneWeather]] = {}
_forecast_sem = asyncio.Semaphore(8)


# Epoch seconds until the Open-Meteo daily quota resets; while dead we
# return unavailable weather immediately instead of hammering a 429ing
# endpoint (324 cells x 3 attempts would burn ~1k pointless requests/h).
_quota_dead_until = 0.0


async def _get_with_retries(
    client: httpx.AsyncClient, url: str, params: dict, attempts: int = 3
) -> dict:
    global _quota_dead_until
    delay = 0.5
    for attempt in range(attempts):
        if time.time() < _quota_dead_until:
            raise QuotaExhausted()
        try:
            resp = await client.get(url, params=params)
            if resp.status_code == 429 and "daily api request limit" in resp.text.lower():
                reset = float(resp.headers.get("x-ratelimit-reset") or 0)
                _quota_dead_until = max(_quota_dead_until, reset or time.time() + 3600)
                raise QuotaExhausted()
            resp.raise_for_status()
            return resp.json()
        except QuotaExhausted:
            raise
        except (httpx.HTTPError, ValueError):
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(min(delay, 5.0))
            delay *= 2
    raise RuntimeError("unreachable")


class QuotaExhausted(Exception):
    """Open-Meteo daily request quota is exhausted (per-IP, 10k/day)."""


class DateTooFarAhead(Exception):
    pass


class DateTooOld(Exception):
    pass


def weather_mode(target: date, today: date) -> str:
    if target > today + timedelta(days=FORECAST_HORIZON_DAYS):
        raise DateTooFarAhead(
            f"date {target} is more than {FORECAST_HORIZON_DAYS} days in the future"
        )
    if target < today - timedelta(days=365 * 5):
        raise DateTooOld(f"date {target} is too far in the past")
    if target >= today - timedelta(days=5):
        return "forecast"
    return "archive"


def _history_window(target: date, today: date) -> tuple[date, date]:
    start = target - timedelta(days=HISTORY_DAYS)
    end = min(target - timedelta(days=1), today)
    return start, end


def _parse_daily(payload: dict, target: date, hist_start: date, hist_end: date) -> ZoneWeather:
    daily = payload.get("daily", {})
    times = daily.get("time", [])
    precip = daily.get("precipitation_sum", [])
    tmax = daily.get("temperature_2m_max", [])
    tmin = daily.get("temperature_2m_min", [])
    rh = daily.get("relative_humidity_2m_mean", [])

    precip_14d = 0.0
    rain_days = 0
    precip_7d = 0.0
    rain_days_7 = 0
    week_start = hist_end - timedelta(days=6)
    for i, iso in enumerate(times):
        day = date.fromisoformat(iso)
        if hist_start <= day <= hist_end:
            value = precip[i] if i < len(precip) and precip[i] is not None else 0.0
            precip_14d += value
            if value >= 2.0:
                rain_days += 1
            if week_start <= day <= hist_end:
                precip_7d += value
                if value >= 2.0:
                    rain_days_7 += 1

    tmax_t = tmin_t = rh_t = precip_t = None
    for i, iso in enumerate(times):
        if date.fromisoformat(iso) == target:
            precip_t = precip[i] if i < len(precip) else None
            tmax_t = tmax[i] if i < len(tmax) else None
            tmin_t = tmin[i] if i < len(tmin) else None
            rh_t = rh[i] if i < len(rh) else None
            break

    return ZoneWeather(
        precip_14d_mm=round(precip_14d, 1),
        rain_days_14d=rain_days,
        precip_7d_mm=round(precip_7d, 1),
        rain_days_7d=rain_days_7,
        precip_target_mm=precip_t,
        temp_max_c=tmax_t,
        temp_min_c=tmin_t,
        rh_mean_pct=rh_t,
        grid_elevation_m=payload.get("elevation"),
    )


def adjust_to_elevation(w: ZoneWeather, elevation_m: float) -> ZoneWeather:
    """Shift grid-cell temperatures to the zone's elevation (lapse rate).

    Returns a copy; the cached cell weather is never mutated. Zones without a
    grid elevation or temperature readings are returned unchanged.
    """
    if w.grid_elevation_m is None or (w.temp_max_c is None and w.temp_min_c is None):
        return w
    delta = (elevation_m - w.grid_elevation_m) * LAPSE_RATE_C_PER_M
    if abs(delta) < 0.05:
        return w
    updates: dict[str, float] = {}
    if w.temp_max_c is not None:
        updates["temp_max_c"] = round(w.temp_max_c - delta, 1)
    if w.temp_min_c is not None:
        updates["temp_min_c"] = round(w.temp_min_c - delta, 1)
    return w.model_copy(update=updates)


def _cache_get(key: tuple, ttl: int) -> ZoneWeather | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.monotonic() - ts > ttl:
        _cache.pop(key, None)
        return None
    return data


def _cache_put(key: tuple, data: ZoneWeather) -> None:
    _cache[key] = (time.monotonic(), data)


async def fetch_zone_weather(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    target: date,
    today: date | None = None,
) -> ZoneWeather:
    today = today or date.today()
    mode = weather_mode(target, today)
    hist_start, hist_end = _history_window(target, today)

    key = (round(lat, 3), round(lon, 3), target, mode)
    ttl = FORECAST_TTL if mode == "forecast" else ARCHIVE_TTL
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached

    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": DAILY_VARS,
        "timezone": "auto",
        "start_date": hist_start.isoformat(),
        "end_date": target.isoformat(),
    }
    url = FORECAST_URL if mode == "forecast" else ARCHIVE_URL

    async with _forecast_sem:
        try:
            payload = await _get_with_retries(client, url, params)
            weather = _parse_daily(payload, target, hist_start, hist_end)
            weather.source = mode
        except (httpx.HTTPError, ValueError, KeyError, QuotaExhausted):
            return ZoneWeather(source="unavailable")

    _cache_put(key, weather)
    return weather


def clear_cache() -> None:
    _cache.clear()
