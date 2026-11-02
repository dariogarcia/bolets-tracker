from __future__ import annotations

from datetime import date

from .models import Scores, Zone, ZoneWeather
from .mushrooms import MUSHROOMS, MushroomProfile, get_profile, season_score

# Direct-sun exposure by aspect: north faces stay damp, south faces bake.
SUN_ASPECT = {
    "N": 95.0,
    "NE": 85.0,
    "NW": 80.0,
    "E": 60.0,
    "W": 55.0,
    "SE": 40.0,
    "SW": 32.0,
    "S": 25.0,
}
# Canopy adjustment: dense cover shades the ground, open cover lets sun in.
SUN_COVER_ADJ = {"dense": 8.0, "moderate": 0.0, "open": -10.0}

# Forest types ranked as rovelló habitat (Scots pine on acidic soil is classic).
FOREST_FACTORS = MUSHROOMS["rovello"].forest_factors

# Global ranking weights: how much each factor matters to the picker. Species
# needs live in the fit scores (season, temperature, habitat), never here.
WEIGHTS = {
    "rain": 0.22,
    "humidity": 0.10,
    "temperature": 0.10,
    "sunlight": 0.08,
    "habitat": 0.12,
    "season": 0.10,
    "crowding": 0.08,
    "accessibility": 0.04,
    "distance": 0.16,
}

NEUTRAL = 50.0


def _rain_base_14d(precip_14d_mm: float, rain_days_14d: int | None) -> float:
    """Soil-moisture component: what the past fortnight has accumulated."""
    p = precip_14d_mm
    if p <= 0:
        return 0.0
    if p < 15:
        base = p / 15 * 20
    elif p < 40:
        base = 20 + (p - 15) / 25 * 45
    elif p <= 120:
        base = 65 + (p - 40) / 80 * 35
    elif p <= 200:
        base = 100 - (p - 120) / 80 * 20
    else:
        base = max(55.0, 80 - (p - 200) / 100 * 25)
    if p < 15 or rain_days_14d is None:
        return base
    bonus = min(10.0, max(0, rain_days_14d - 1) * 2.5)
    return min(100.0, base + bonus)


def _rain_recency_7d(precip_7d_mm: float, rain_days_7d: int | None) -> float:
    """Fruiting trigger: a fresh soaking in the last week starts the flush."""
    p = precip_7d_mm
    if p <= 0:
        recency = 0.0
    elif p < 10:
        recency = 25 + p / 10 * 35
    elif p < 25:
        recency = 60 + (p - 10) / 15 * 30
    elif p <= 60:
        recency = 90 + min(10.0, (p - 25) / 35 * 10)
    else:
        recency = 100.0
    if rain_days_7d:
        recency = min(100.0, recency + rain_days_7d * 2)
    return recency


def score_rain(
    precip_14d_mm: float | None,
    rain_days_14d: int | None,
    precip_7d_mm: float | None = None,
    rain_days_7d: int | None = None,
) -> float:
    if precip_14d_mm is None:
        return NEUTRAL
    base = _rain_base_14d(precip_14d_mm, rain_days_14d)
    if precip_7d_mm is None:
        return round(base, 1)
    recency = _rain_recency_7d(precip_7d_mm, rain_days_7d)
    return round(0.65 * base + 0.35 * recency, 1)


def score_humidity(rh_mean_pct: float | None, precip_target_mm: float | None = None) -> float:
    if rh_mean_pct is None:
        return NEUTRAL
    rh = rh_mean_pct
    if rh < 40:
        base = 0.0
    elif rh < 70:
        base = (rh - 40) / 30 * 70
    elif rh <= 90:
        base = 70 + (rh - 70) / 20 * 30
    else:
        base = max(70.0, 100 - (rh - 90) / 10 * 15)
    if precip_target_mm:
        base = min(100.0, base + min(8.0, precip_target_mm * 1.5))
    return round(max(0.0, min(100.0, base)), 1)


def score_temperature(
    temp_max_c: float | None,
    temp_min_c: float | None,
    ideal: tuple[float, float] = (10, 21),
) -> float:
    """Day-temperature fit against the species' ideal band (lo, hi)."""
    if temp_max_c is None:
        return NEUTRAL
    lo, hi = ideal
    tmax = temp_max_c
    if tmax <= lo - 8:
        return 0.0
    if tmax < lo:
        base = (tmax - (lo - 8)) / 8 * 100
    elif tmax <= hi:
        base = 100.0
    elif tmax <= hi + 6:
        base = 100 - (tmax - hi) / 6 * 70
    elif tmax < hi + 14:
        base = max(0.0, 30 - (tmax - (hi + 6)) / 8 * 30)
    else:
        return 0.0
    # Night refinement: ideal nights 4-12 °C; frost damages the flush, warm nights stall it.
    if temp_min_c is not None:
        if temp_min_c < 0:
            base *= max(0.3, 1 + temp_min_c / 20)
        elif temp_min_c < 4:
            base *= 0.85 + temp_min_c / 4 * 0.15
        elif temp_min_c > 16:
            base *= 0.85
        elif temp_min_c > 12:
            base *= 1 - (temp_min_c - 12) / 4 * 0.1
    return round(max(0.0, min(100.0, base)), 1)


def score_sunlight(zone: Zone) -> float:
    """Direct-sun exposure of the slope: rovellons fruit on shaded ground."""
    base = SUN_ASPECT.get(zone.aspect, 55.0)
    base += SUN_COVER_ADJ.get(zone.cover, 0.0)
    return round(max(5.0, min(100.0, base)), 1)


def score_habitat(zone: Zone, forest_factors: dict[str, float] | None = None) -> float:
    factors = forest_factors if forest_factors is not None else FOREST_FACTORS
    forest = factors.get(zone.forest, 0.75)
    quality = zone.habitat_quality / 5
    value = 100 * (0.60 * quality + 0.40 * forest)
    return round(value, 1)


def score_season(
    target: date,
    elevation_m: int,
    windows: dict[str, tuple[int, float]] | None = None,
) -> float:
    return season_score(target, elevation_m, windows or MUSHROOMS["rovello"].season_windows)


def score_crowding(popularity: int) -> float:
    return round(100 - (popularity - 1) * 100 / 9, 1)


def score_accessibility(accessibility: int) -> float:
    return round(accessibility * 10, 1)


def score_distance(duration_min: float) -> float:
    d = duration_min
    if d <= 30:
        return 100.0
    if d <= 90:
        return round(100 - (d - 30) / 60 * 40, 1)
    if d <= 180:
        return round(60 - (d - 90) / 90 * 35, 1)
    if d <= 300:
        return round(25 - (d - 180) / 120 * 25, 1)
    return 0.0


def compute_scores(
    zone: Zone,
    weather: ZoneWeather,
    target: date,
    duration_min: float,
    weights: dict[str, float] | None = None,
    mushroom: str | MushroomProfile = "rovello",
) -> Scores:
    profile = mushroom if isinstance(mushroom, MushroomProfile) else get_profile(mushroom)
    rain = score_rain(
        weather.precip_14d_mm,
        weather.rain_days_14d,
        weather.precip_7d_mm,
        weather.rain_days_7d,
    )
    humidity = score_humidity(weather.rh_mean_pct, weather.precip_target_mm)
    temperature = score_temperature(weather.temp_max_c, weather.temp_min_c, profile.temp_ideal)
    sunlight = score_sunlight(zone)
    habitat = score_habitat(zone, profile.forest_factors)
    season = score_season(target, zone.elevation_m, profile.season_windows)
    crowding = score_crowding(zone.popularity)
    accessibility = score_accessibility(zone.accessibility)
    distance = score_distance(duration_min)

    axes = {
        "rain": rain,
        "humidity": humidity,
        "temperature": temperature,
        "sunlight": sunlight,
        "habitat": habitat,
        "season": season,
        "crowding": crowding,
        "accessibility": accessibility,
        "distance": distance,
    }
    w = weights if weights is not None else WEIGHTS
    overall = sum(w.get(axis, 0.0) * value for axis, value in axes.items())

    return Scores(
        rain=rain,
        humidity=humidity,
        temperature=temperature,
        sunlight=sunlight,
        habitat=habitat,
        season=season,
        crowding=crowding,
        accessibility=accessibility,
        distance=distance,
        overall=round(max(0.0, min(100.0, overall)), 1),
    )
