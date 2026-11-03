from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class Zone(BaseModel):
    id: str
    name: str
    area: str
    comarca: str
    lat: float
    lon: float
    elevation_m: int
    aspect: str
    forest: str
    cover: str
    habitat_quality: int = Field(ge=1, le=5)
    popularity: int = Field(ge=1, le=10)
    accessibility: int = Field(ge=1, le=10)
    walk_min: int = Field(ge=0, le=180)
    access: str
    notes: str
    # Measured attributes (MFE50 forest map + ICGC geology); defaults keep
    # legacy constructions working. `forest`, `cover` and `habitat_quality`
    # above are themselves derived from the same measurements.
    soil: str = "neutral"
    forest_shares: dict[str, float] = Field(default_factory=dict)
    geology: str = ""
    forest_desc: str = ""


class ZoneWeather(BaseModel):
    precip_14d_mm: float | None = None
    rain_days_14d: int | None = None
    precip_7d_mm: float | None = None
    rain_days_7d: int | None = None
    precip_target_mm: float | None = None
    temp_max_c: float | None = None
    temp_min_c: float | None = None
    rh_mean_pct: float | None = None
    grid_elevation_m: float | None = None
    source: str = "unavailable"


class RouteInfo(BaseModel):
    distance_km: float
    duration_min: float
    source: str


class Scores(BaseModel):
    rain: float
    humidity: float
    temperature: float
    sunlight: float
    habitat: float
    season: float
    crowding: float
    accessibility: float
    distance: float
    overall: float


class Recommendation(BaseModel):
    rank: int
    zone: Zone
    scores: Scores
    weather: ZoneWeather
    route: RouteInfo


class RecommendResponse(BaseModel):
    date: date
    mushroom: str = "rovello"
    origin: dict
    generated_at: str
    count: int
    results: list[Recommendation]


class Place(BaseModel):
    name: str
    admin: str
    lat: float
    lon: float
    country: str | None = None
    population: int | None = None
