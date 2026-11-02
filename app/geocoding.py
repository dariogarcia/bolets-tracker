from __future__ import annotations

import httpx

from .models import Place

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

PRESET_PLACES: list[Place] = [
    Place(name="Barcelona", admin="Barcelonès", lat=41.3851, lon=2.1734, country="Espanya", population=1620343),
    Place(name="Girona", admin="Gironès", lat=41.9793, lon=2.8214, country="Espanya", population=103361),
    Place(name="Lleida", admin="Segrià", lat=41.6176, lon=0.6200, country="Espanya", population=140546),
    Place(name="Tarragona", admin="Tarragonès", lat=41.1189, lon=1.2445, country="Espanya", population=134770),
    Place(name="Vic", admin="Osona", lat=41.9300, lon=2.2540, country="Espanya", population=46942),
    Place(name="Manresa", admin="Bages", lat=41.7250, lon=1.8266, country="Espanya", population=78661),
    Place(name="Sabadell", admin="Vallès Occidental", lat=41.5430, lon=2.1090, country="Espanya", population=216520),
    Place(name="Terrassa", admin="Vallès Occidental", lat=41.5667, lon=2.0167, country="Espanya", population=224111),
    Place(name="Reus", admin="Baix Camp", lat=41.1561, lon=1.1069, country="Espanya", population=106168),
    Place(name="Mataró", admin="Maresme", lat=41.5330, lon=2.4450, country="Espanya", population=129101),
    Place(name="Berga", admin="Berguedà", lat=42.1010, lon=1.8460, country="Espanya", population=16235),
    Place(name="Ripoll", admin="Ripollès", lat=42.1967, lon=2.2232, country="Espanya", population=10625),
    Place(name="Olot", admin="Garrotxa", lat=42.1810, lon=2.4870, country="Espanya", population=34447),
    Place(name="Solsona", admin="Solsonès", lat=41.9934, lon=1.5171, country="Espanya", population=9482),
    Place(name="La Seu d'Urgell", admin="Alt Urgell", lat=42.3672, lon=1.4648, country="Espanya", population=12077),
    Place(name="Puigcerdà", admin="Cerdanya", lat=42.4280, lon=1.7990, country="Espanya", population=9563),
    Place(name="Riu de Cerdanya", admin="Baixa Cerdanya", lat=42.3475, lon=1.8275, country="Espanya", population=94),
    Place(name="Sort", admin="Pallars Sobirà", lat=42.4197, lon=1.1069, country="Espanya", population=2283),
    Place(name="Tremp", admin="Pallars Jussà", lat=42.1080, lon=0.9290, country="Espanya", population=6415),
    Place(name="Figueres", admin="Alt Empordà", lat=42.2660, lon=2.9580, country="Espanya", population=44888),
    Place(name="Cervera", admin="Segarra", lat=41.6700, lon=1.2690, country="Espanya", population=9374),
    Place(name="Igualada", admin="Anoia", lat=41.5800, lon=1.6200, country="Espanya", population=39641),
    Place(name="Vilafranca del Penedès", admin="Alt Penedès", lat=41.3450, lon=1.6970, country="Espanya", population=39634),
    Place(name="Tortosa", admin="Baix Ebre", lat=40.8110, lon=0.5210, country="Espanya", population=33333),
    Place(name="Sant Cugat del Vallès", admin="Vallès Occidental", lat=41.4700, lon=2.0800, country="Espanya", population=89116),
    Place(name="Gavà", admin="Baix Llobregat", lat=41.3050, lon=2.0010, country="Espanya", population=46697),
    Place(name="Granollers", admin="Vallès Oriental", lat=41.6080, lon=2.2870, country="Espanya", population=60641),
]


def _preset_matches(query: str) -> list[Place]:
    q = query.strip().lower()
    if not q:
        return []
    return [p for p in PRESET_PLACES if q in p.name.lower()]


async def geocode(client: httpx.AsyncClient, query: str, limit: int = 8) -> list[Place]:
    presets = _preset_matches(query)
    results: list[Place] = list(presets)
    seen = {(round(p.lat, 3), round(p.lon, 3)) for p in presets}

    try:
        resp = await client.get(
            GEOCODE_URL,
            params={"name": query, "count": limit, "language": "ca", "format": "json"},
        )
        resp.raise_for_status()
        payload = resp.json()
        for item in payload.get("results", []):
            if item.get("country_code") != "ES":
                continue
            if item.get("admin1") != "Catalunya":
                continue
            key = (round(item["latitude"], 3), round(item["longitude"], 3))
            if key in seen:
                continue
            seen.add(key)
            results.append(
                Place(
                    name=item.get("name", ""),
                    admin=item.get("admin3") or item.get("admin2") or "",
                    lat=item["latitude"],
                    lon=item["longitude"],
                    country=item.get("country"),
                    population=item.get("population"),
                )
            )
    except (httpx.HTTPError, ValueError, KeyError):
        pass

    return results[:limit]
