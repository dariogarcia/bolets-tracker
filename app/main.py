from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import geocoding, routing, weather
from .models import Recommendation, RecommendResponse
from .mushrooms import MUSHROOMS, availability
from .scoring import WEIGHTS, compute_scores
from .zones import ZONES, get_zone

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

ORIGIN_BBOX = {"lat_min": 40.4, "lat_max": 42.9, "lon_min": 0.0, "lon_max": 3.5}
WEATHER_GRID_DEG = 0.1

_lifespan_client: httpx.AsyncClient | None = None


def _weather_cell(lat: float, lon: float) -> tuple[int, int]:
    return (round(lat / WEATHER_GRID_DEG), round(lon / WEATHER_GRID_DEG))


async def _fetch_zone_weathers(
    client: httpx.AsyncClient, target: date, today: date
) -> list:
    cells: dict[tuple[int, int], tuple[float, float]] = {}
    for z in ZONES:
        cells.setdefault(_weather_cell(z.lat, z.lon), (z.lat, z.lon))
    fetched = await asyncio.gather(
        *[weather.fetch_zone_weather(client, lat, lon, target, today) for lat, lon in cells.values()]
    )
    by_cell = dict(zip(cells.keys(), fetched, strict=True))
    return [by_cell[_weather_cell(z.lat, z.lon)] for z in ZONES]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _lifespan_client
    _lifespan_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True)
    yield
    await _lifespan_client.aclose()
    _lifespan_client = None


app = FastAPI(title="Rovelló Tracker", version="1.0.0", lifespan=lifespan)


def http_client() -> httpx.AsyncClient:
    if _lifespan_client is None or _lifespan_client.is_closed:
        return httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True)
    return _lifespan_client


@app.get("/api/health")
async def health():
    return {"status": "ok", "zones": len(ZONES)}


@app.get("/api/zones")
async def list_zones():
    return {"count": len(ZONES), "zones": [z.model_dump() for z in ZONES]}


@app.get("/api/zone/{zone_id}")
async def zone_detail(zone_id: str):
    zone = get_zone(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"unknown zone id: {zone_id}")
    return zone.model_dump()


@app.get("/api/geocode")
async def geocode_endpoint(q: str = Query(min_length=2, max_length=64)):
    client = http_client()
    places = await geocoding.geocode(client, q)
    return {"query": q, "results": [p.model_dump() for p in places]}


def _parse_weights(raw: str | None) -> dict[str, float] | None:
    """Parse a JSON object of axis multipliers into normalized weights."""
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"weights must be a JSON object of axis multipliers: {exc}"
        ) from exc
    if not isinstance(data, dict) or not data:
        raise HTTPException(
            status_code=422,
            detail=(
                "weights must be a non-empty JSON object, e.g. "
                '{"rain": 30, "distance": 10}; valid axes: ' + ", ".join(sorted(WEIGHTS))
            ),
        )
    parsed: dict[str, float] = {}
    for axis, value in data.items():
        if axis not in WEIGHTS:
            raise HTTPException(
                status_code=422,
                detail=f"unknown weight axis '{axis}'; valid axes: {', '.join(sorted(WEIGHTS))}",
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise HTTPException(
                status_code=422, detail=f"weight for '{axis}' must be a number >= 0"
            )
        parsed[axis] = float(value)
    total = sum(parsed.values())
    if total <= 0:
        raise HTTPException(status_code=422, detail="weights must not all be zero")
    return {axis: value / total for axis, value in parsed.items()}


@app.get("/api/mushrooms")
async def mushrooms_endpoint(
    dt: Annotated[date | None, Query(alias="date")] = None,
):
    """Per-species availability for a date, plus the profile the UI needs."""
    target = dt or date.today()
    return {
        "date": target,
        "mushrooms": [
            {
                "id": m.id,
                "names": m.names,
                "scientific": m.scientific,
                "emoji": m.emoji,
                "note": m.note,
                "temp_ideal": list(m.temp_ideal),
                **availability(m, target),
            }
            for m in MUSHROOMS.values()
        ],
    }


@app.get("/api/recommend")
async def recommend(
    lat: Annotated[float, Query(ge=35, le=44)],
    lon: Annotated[float, Query(ge=-2, le=4)],
    dt: Annotated[date | None, Query(alias="date")] = None,
    max_distance_km: Annotated[float | None, Query(gt=0, le=500)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    weights: Annotated[str | None, Query(max_length=512)] = None,
    mushroom: Annotated[str, Query(max_length=24)] = "rovello",
):
    target = dt or date.today()
    today = date.today()

    if mushroom not in MUSHROOMS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown mushroom '{mushroom}'; valid ids: {', '.join(sorted(MUSHROOMS))}",
        )

    if not (ORIGIN_BBOX["lat_min"] <= lat <= ORIGIN_BBOX["lat_max"]) or not (
        ORIGIN_BBOX["lon_min"] <= lon <= ORIGIN_BBOX["lon_max"]
    ):
        raise HTTPException(
            status_code=422,
            detail="origin must be inside Catalonia (lat 40.4-42.9, lon 0.0-3.5)",
        )

    try:
        weather.weather_mode(target, today)
    except weather.DateTooFarAhead as exc:
        raise HTTPException(
            status_code=422,
            detail=f"date is beyond the {weather.FORECAST_HORIZON_DAYS}-day weather forecast horizon: {exc}",
        ) from exc
    except weather.DateTooOld as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    client = http_client()
    custom_weights = _parse_weights(weights)

    weather_task = asyncio.ensure_future(_fetch_zone_weathers(client, target, today))
    routes = await routing.fetch_route_table(client, lat, lon, ZONES)
    weathers = await weather_task

    results: list[Recommendation] = []
    for zone, cell_weather in zip(ZONES, weathers, strict=True):
        route = routes[zone.id]
        if max_distance_km is not None and route.distance_km > max_distance_km:
            continue
        zone_weather = weather.adjust_to_elevation(cell_weather, zone.elevation_m)
        scores = compute_scores(
            zone, zone_weather, target, route.duration_min, custom_weights, mushroom
        )
        results.append(
            Recommendation(zone=zone, scores=scores, weather=zone_weather, route=route, rank=0)
        )

    results.sort(key=lambda r: r.scores.overall, reverse=True)
    for i, r in enumerate(results, start=1):
        r.rank = i

    return RecommendResponse(
        date=target,
        mushroom=mushroom,
        origin={"lat": lat, "lon": lon},
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        count=len(results[:limit]),
        results=results[:limit],
    ).model_dump(mode="json")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
