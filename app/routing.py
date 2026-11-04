from __future__ import annotations

import asyncio
import math

import httpx

from .models import RouteInfo, Zone

OSRM_TABLE_URL = "https://router.project-osrm.org/table/v1/driving/{coords}"
# Live OSRM routing is only fetched for the zones nearest the origin.
ROUTE_ZONES_CAP = 1000
EARTH_RADIUS_KM = 6371.0
ROAD_FACTOR = 1.35
FALLBACK_SPEED_KMH = 50.0
MAX_TABLE_SIZE = 95


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_route(lat1: float, lon1: float, lat2: float, lon2: float) -> RouteInfo:
    straight = haversine_km(lat1, lon1, lat2, lon2)
    distance = straight * ROAD_FACTOR
    duration = distance / FALLBACK_SPEED_KMH * 60.0
    return RouteInfo(distance_km=round(distance, 1), duration_min=round(duration, 1), source="estimate")


def _parse_table(payload: dict, zone_ids: list[str]) -> dict[str, RouteInfo]:
    durations = payload["durations"][0][1:]
    distances = payload["distances"][0][1:]
    routes: dict[str, RouteInfo] = {}
    for zone_id, dur, dist in zip(zone_ids, durations, distances, strict=False):
        if dur is None or dist is None:
            continue
        routes[zone_id] = RouteInfo(
            distance_km=round(dist / 1000.0, 1),
            duration_min=round(dur / 60.0, 1),
            source="osrm",
        )
    return routes


async def fetch_route_table(
    client: httpx.AsyncClient,
    origin_lat: float,
    origin_lon: float,
    zones: list[Zone],
) -> dict[str, RouteInfo]:
    routes: dict[str, RouteInfo] = {}
    # Cap the live table to the zones nearest the origin (straight
    # line): far zones would score poorly on distance anyway and the
    # public OSRM table endpoint should not be hammered with thousands
    # of destinations per search. The rest use the haversine estimate.
    ranked = sorted(zones, key=lambda z: haversine_km(origin_lat, origin_lon, z.lat, z.lon))
    table_zones = ranked[:ROUTE_ZONES_CAP]
    batch_size = MAX_TABLE_SIZE - 1
    batches = [table_zones[i : i + batch_size] for i in range(0, len(table_zones), batch_size)]

    async def fetch_batch(batch: list[Zone]) -> dict[str, RouteInfo]:
        coords = f"{origin_lon},{origin_lat};"
        coords += ";".join(f"{z.lon},{z.lat}" for z in batch)
        url = OSRM_TABLE_URL.format(coords=coords)
        try:
            resp = await client.get(url, params={"annotations": "distance,duration"})
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != "Ok":
                raise ValueError(payload.get("code", "unknown"))
            return _parse_table(payload, [z.id for z in batch])
        except (httpx.HTTPError, ValueError, KeyError):
            return {}

    sem = asyncio.Semaphore(6)

    async def guarded(batch: list[Zone]) -> dict[str, RouteInfo]:
        async with sem:
            return await fetch_batch(batch)

    for chunk in await asyncio.gather(*(guarded(b) for b in batches)):
        routes.update(chunk)

    for z in zones:
        if z.id not in routes:
            routes[z.id] = estimate_route(origin_lat, origin_lon, z.lat, z.lon)
    return routes
