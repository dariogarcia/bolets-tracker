"""Regenerate app/zones.py from GIS forest regions.

Replaces the hand-curated 819-sector dataset with regions derived from
MFE50 forest stands (scripts/build_forest_regions.py) enriched with
measured terrain, soil, comarca, road access and toponyms
(scripts/enrich_regions.py).

Selection (--stage select):
    keep regions with a road/track within 1 km (the accessible forests),
    rank by measured habitat quality x log(area) and keep the top
    --target (default 2000). Regions containing the staging point of a
    legacy curated zone (data/legacy_zones.json) inherit its name,
    notes, access text and popularity — the picker lore survives the
    regeneration. Non-legacy zones get a computed crowd pressure
    (see the crowd-pressure model below). Writes data/region_selection.json.

Build (--stage build):
    needs terrain and names for every selected region (run
    scripts/enrich_regions.py --stage terrain/names --regions <ids>
    in between) and writes app/zones.py + data/zone_polygons.json.

Run from the project root:

    uv run --with shapely python scripts/rebuild_zones_from_regions.py --stage select
    uv run --with shapely --with pyproj python scripts/enrich_regions.py \
        --stage terrain --regions $(cat /tmp/opencode/regions-tmp/selected.txt | tr '\n' ' ')
    ...
    uv run --with shapely python scripts/rebuild_zones_from_regions.py --stage build
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from bisect import bisect_left
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.habitat import (
    GROUPS,
    classify_soil,
    derive_cover,
    derive_forest,
    derive_habitat_quality,
)

WORK_DIR = ROOT / ".work" / "regions"
REGIONS_FILE = WORK_DIR / "forest_regions.geojson"
SELECTED_FILE = WORK_DIR / "selected.txt"
ATTRS_FILE = ROOT / "data" / "forest_regions_attrs.json"
LEGACY_FILE = ROOT / "data" / "legacy_zones.json"
SELECTION_FILE = ROOT / "data" / "region_selection.json"
POLYGONS_FILE = ROOT / "data" / "zone_polygons.json"
ZONES_FILE = ROOT / "app" / "zones.py"

MAX_ROAD_DIST_M = 1000.0
WALK_M_PER_MIN = 50.0
CITIES_FILE = ROOT / "data" / "cities_cat.json"
FAME_FILE = ROOT / "data" / "toponym_fame.json"

# Crowd-pressure model weights: day-trip demand, internet salience,
# ease of walking in. Legacy zones keep their curated popularity.
W_PULL, W_FAME, W_ACCESS = 0.40, 0.35, 0.25
MAX_CITY_KM = 60.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def city_pull_log(lat: float, lon: float, cities: list[dict]) -> float:
    """log of the day-trip demand: sum of population/(distance+5km)."""
    pull = sum(
        c["pop_k"] / (haversine_km(lat, lon, c["lat"], c["lon"]) + 5.0)
        for c in cities
        if haversine_km(lat, lon, c["lat"], c["lon"]) <= MAX_CITY_KM
    )
    return math.log1p(pull)


def fame_log(a: dict, fame: dict) -> float:
    """log of internet salience: Wikipedia pageviews (ca+es, 12 months)
    of the nearest toponym, with a 25% comarca floor."""
    ns = a.get("names") or []
    top = fame.get((ns[0] or {}).get("t", ""), {}) if ns else {}
    com = fame.get(a.get("comarca") or "", {})
    views = max(
        top.get("ca", 0) + top.get("es", 0),
        0.25 * (com.get("ca", 0) + com.get("es", 0)),
    )
    return math.log1p(views)


def pct_ranks(values: dict[str, float]) -> dict[str, float]:
    """Percentile rank of each value within the dict (0..1)."""
    ordered = sorted(values.values())
    n = len(ordered)
    if n < 2:
        return {k: 1.0 for k in values}
    pos = {}
    for k, v in values.items():
        pos[k] = bisect_left(ordered, v) / (n - 1)
    return pos

CLASS_LABEL = {
    "scots": "Scots pine",
    "black": "black pine",
    "aleppo": "Aleppo pine",
    "coastal": "coastal pine",
    "broadleaf": "broadleaf",
    "mixed": "mixed pine",
}


def load_regions() -> list[dict]:
    return json.loads(REGIONS_FILE.read_text(encoding="utf-8"))["features"]


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "bosc"


def region_exterior(feature: dict) -> list[list[float]]:
    """Exterior ring of the largest polygon part as [lat, lon] pairs."""
    from shapely.geometry import shape

    geom = shape(feature["geometry"])
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda g: g.area)
    return [[round(lat, 6), round(lon, 6)] for lon, lat in geom.exterior.coords]


def stage_select(args) -> None:
    from shapely.geometry import shape

    regions = load_regions()
    attrs = json.loads(ATTRS_FILE.read_text(encoding="utf-8"))
    legacy = json.loads(LEGACY_FILE.read_text(encoding="utf-8"))

    polys = {f["properties"]["region_id"]: shape(f["geometry"]) for f in regions}

    # Legacy lore: a curated zone's staging point inside a region passes
    # its name, notes, access text and popularity on to that region.
    from shapely import STRtree
    from shapely.geometry import Point

    rids = list(polys)
    tree = STRtree([polys[r] for r in rids])
    inherited: dict[str, dict] = {}
    for z in legacy:
        pt = Point(z["lon"], z["lat"])
        idx = tree.query(pt, predicate="within")
        if len(idx):
            inherited.setdefault(rids[int(idx[0])], z)

    accessible = []
    for f in regions:
        rid = f["properties"]["region_id"]
        roads = (attrs.get(rid) or {}).get("roads") or {}
        dist = roads.get("dist_m")
        if dist is None or dist > MAX_ROAD_DIST_M:
            continue
        p = f["properties"]
        quality = derive_habitat_quality(p["tfccarb"])
        score = quality * math.log1p(p["area_ha"])
        accessible.append((score, rid))

    accessible.sort(reverse=True)
    selected = accessible[: args.target]
    print(f"accessible regions: {len(accessible)}; selecting {len(selected)} of target {args.target}")

    out = {}
    for _, rid in selected:
        entry = {"region_id": rid}
        if rid in inherited:
            src = inherited[rid]
            entry["legacy"] = {
                "id": src["id"],
                "name": src["name"],
                "notes": src["notes"],
                "access": src["access"],
                "popularity": src["popularity"],
            }
        out[rid] = entry
    SELECTION_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    SELECTED_FILE.write_text("\n".join(e["region_id"] for e in out.values()), encoding="utf-8")
    n_legacy = sum(1 for e in out.values() if "legacy" in e)
    print(f"wrote {SELECTION_FILE} ({len(out)} regions, {n_legacy} with inherited lore)")


def stage_build(args) -> None:
    from shapely.geometry import Polygon
    from shapely.ops import transform as shp_transform

    regions = {f["properties"]["region_id"]: f for f in load_regions()}
    attrs = json.loads(ATTRS_FILE.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION_FILE.read_text(encoding="utf-8"))

    from pyproj import Transformer

    to_utm = Transformer.from_crs(4326, 25831, always_xy=True)
    to_wgs = Transformer.from_crs(25831, 4326, always_xy=True)

    missing_terrain = [rid for rid in selection if not (attrs.get(rid) or {}).get("terrain")]
    if missing_terrain:
        raise SystemExit(
            f"{len(missing_terrain)} selected regions lack terrain data — run "
            "scripts/enrich_regions.py --stage terrain first"
        )

    used_names: dict[str, int] = {}
    polygons: dict[str, list[list[float]]] = {}
    records = []
    crowd_signals: dict[str, tuple[float, float, float]] = {}
    cities = json.loads(CITIES_FILE.read_text(encoding="utf-8"))["cities"]
    if FAME_FILE.exists():
        fame = json.loads(FAME_FILE.read_text(encoding="utf-8"))
    else:
        print(f"warning: {FAME_FILE} missing — run scripts/fetch_fame.py; fame term will be flat")
        fame = {}

    for rid, sel in selection.items():
        feature = regions[rid]
        p = feature["properties"]
        a = attrs[rid]
        terrain = a["terrain"]
        roads = a["roads"]
        shares = {g: float(v) for g, v in (p.get("shares") or {}).items()}
        tfccarb = p["tfccarb"]
        legacy = sel.get("legacy")

        comarca = a.get("comarca") or (legacy or {}).get("comarca") or "Catalunya"
        names = a.get("names") or []
        if legacy and legacy.get("name"):
            name = legacy["name"]
        elif names:
            name = names[0]["t"]
        else:
            name = f"Bosc de {comarca}"
        base_name = name
        n = used_names.get(base_name, 0) + 1
        used_names[base_name] = n
        if n > 1:
            name = f"{base_name} {['II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'][min(n - 2, 8)]}"

        zone_id = f"{slugify(name)}-{p['comp_class']}"
        if zone_id in polygons:
            zone_id = f"{zone_id}-{n}"

        dist_m = roads.get("dist_m") or 0.0
        walk_min = min(90, round(dist_m / WALK_M_PER_MIN))
        if roads.get("tipus") == "cor":
            # corriol (footpath): parked at the track head, walk in on foot
            walk_min = min(90, walk_min + 15)
        accessibility = max(1, 10 - round(walk_min / 5))

        if legacy:
            notes = legacy["notes"]
            access = legacy["access"]
            popularity = legacy["popularity"]
        else:
            soil = classify_soil((a.get("geol") or {}).get("descripcio"))
            notes = (
                f"{p['area_ha']:.0f} ha of continuous {CLASS_LABEL.get(p['comp_class'], 'forest')} "
                f"on {soil} bedrock; measured canopy {tfccarb:.0f}%."
            )
            road_nom = roads.get("nom")
            road_kind = "footpath" if roads.get("tipus") == "cor" else "track"
            if dist_m <= 1.0:
                access = (
                    f"A {road_kind} crosses the forest"
                    + (f" ({road_nom})" if road_nom else "")
                    + " — park at the marked access point."
                )
            else:
                access = (
                    f"Forest starts {dist_m:.0f} m from the nearest {road_kind}"
                    + (f" ({road_nom})" if road_nom else "")
                    + " — park at the marked access point and walk in."
                )
            popularity = None  # computed after the loop from crowd signals

        staging = roads.get("staging")
        if not staging:
            ring = region_exterior(feature)
            staging = [sum(q[1] for q in ring) / len(ring), sum(q[0] for q in ring) / len(ring)]

        if popularity is None:
            crowd_signals[zone_id] = (
                city_pull_log(staging[0], staging[1], cities),
                fame_log(a, fame),
                1.0 - walk_min / 90.0,
            )

        ring = region_exterior(feature)
        poly_utm = shp_transform(lambda x, y, z=None: to_utm.transform(x, y), Polygon([(q[1], q[0]) for q in ring]))
        simple = poly_utm.simplify(args.poly_tolerance)
        pts = [
            [round(lat, 4), round(lon, 4)]
            for lon, lat in [
                to_wgs.transform(x, y) for x, y in simple.exterior.coords
            ]
        ]
        if len(pts) > 3:
            polygons[zone_id] = pts

        records.append(
            {
                "id": zone_id,
                "name": name,
                "comarca": comarca,
                "lat": round(staging[0], 5),
                "lon": round(staging[1], 5),
                "elevation_m": round(terrain["elev"]),
                "aspect": terrain["aspect"],
                "forest": derive_forest(shares),
                "cover": derive_cover(tfccarb),
                "habitat_quality": derive_habitat_quality(tfccarb),
                "popularity": popularity,
                "accessibility": accessibility,
                "walk_min": walk_min,
                "access": access,
                "notes": notes,
                "soil": classify_soil((a.get("geol") or {}).get("descripcio")),
                "forest_shares": {g: round(v, 3) for g, v in shares.items() if v >= 0.005},
                "geology": (a.get("geol") or {}).get("descripcio") or "",
                "forest_desc": "",
            }
        )

    # Crowd-pressure model: percentile-rank the three signals, blend with
    # fixed weights, then map the blended score onto the 1-10 popularity
    # scale (again by percentile, so the crowded decile of zones gets 10).
    if crowd_signals:
        pull_pct = pct_ranks({k: s[0] for k, s in crowd_signals.items()})
        fame_pct = pct_ranks({k: s[1] for k, s in crowd_signals.items()})
        blended = {
            k: W_PULL * pull_pct[k] + W_FAME * fame_pct[k] + W_ACCESS * s[2]
            for k, s in crowd_signals.items()
        }
        crowd_pct = pct_ranks(blended)
        for r in records:
            if r["id"] in crowd_pct:
                r["popularity"] = 1 + round(9 * crowd_pct[r["id"]])
        hist: dict[int, int] = {}
        for r in records:
            hist[r["popularity"]] = hist.get(r["popularity"], 0) + 1
        print("popularity histogram:", dict(sorted(hist.items())))

    POLYGONS_FILE.write_text(json.dumps(polygons, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {POLYGONS_FILE} ({POLYGONS_FILE.stat().st_size / 1024:.0f} KiB)")

    lines = [HEADER]
    for r in records:
        lines.append(
            f"    sector({r['id']!r}, {r['name']!r}, {r['comarca']!r}, {r['comarca']!r},\n"
            f"           {r['lat']}, {r['lon']}, {r['elevation_m']}, {r['aspect']!r}, "
            f"{r['forest']!r}, {r['cover']!r}, {r['habitat_quality']},\n"
            f"           {r['popularity']}, {r['accessibility']}, {r['walk_min']},\n"
            f"           {r['access']!r},\n"
            f"           {r['notes']!r},\n"
            f"           soil={r['soil']!r}, forest_shares={fmt_shares(r['forest_shares'])},\n"
            f"           geology={r['geology']!r}, forest_desc={r['forest_desc']!r}),\n"
        )
    lines.append("]\n")
    lines.append(FOOTER)
    ZONES_FILE.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {len(records)} zones to {ZONES_FILE}")


HEADER = '''"""Forest regions with measured habitat attributes.

Generated by scripts/rebuild_zones_from_regions.py — do not edit by
hand. Each zone is a contiguous MFE50 forest region of coherent tree
composition (MITECO, 1:50.000) with:

- measured composition, canopy and habitat quality (MFE50)
- measured bedrock chemistry and lithology (ICGC geology 1:50.000)
- measured elevation, slope and aspect (Open-Meteo DEM)
- real road access: staging point, walk distance (ICGC topography 1:5.000)
- toponym names (ICGC nomenclàtor), comarca boundaries (ICGC)
- picker lore inherited from the legacy curated sectors where a region
  contains one of their staging points (data/legacy_zones.json)
- crowd pressure for non-legacy zones, computed from: day-trip demand
  (population of nearby cities, data/cities_cat.json, IDESCAT),
  internet salience (Wikipedia pageviews of the toponym/comarca,
  data/toponym_fame.json via scripts/fetch_fame.py) and walking effort
  (walk_min); blended 40/35/25 and percentile-mapped onto 1-10

Region outlines live in data/zone_polygons.json and are attached to the
zones at import time.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Zone

_POLYGONS = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "zone_polygons.json").read_text(encoding="utf-8")
)


def sector(
    id: str,
    name: str,
    area: str,
    comarca: str,
    lat: float,
    lon: float,
    elevation_m: int,
    aspect: str,
    forest: str,
    cover: str,
    habitat_quality: int,
    popularity: int,
    accessibility: int,
    walk_min: int,
    access: str,
    notes: str,
    soil: str = "neutral",
    forest_shares: dict[str, float] | None = None,
    geology: str = "",
    forest_desc: str = "",
) -> Zone:
    return Zone(
        id=id,
        name=name,
        area=area,
        comarca=comarca,
        lat=lat,
        lon=lon,
        elevation_m=elevation_m,
        aspect=aspect,
        forest=forest,
        cover=cover,
        habitat_quality=habitat_quality,
        popularity=popularity,
        accessibility=accessibility,
        walk_min=walk_min,
        access=access,
        notes=notes,
        soil=soil,
        forest_shares=forest_shares or {},
        geology=geology,
        forest_desc=forest_desc,
        polygon=_POLYGONS.get(id, []),
    )


ZONES: list[Zone] = [
'''

FOOTER = '''

def get_zone(zone_id: str) -> Zone | None:
    """Look up a zone by id."""
    return next((z for z in ZONES if z.id == zone_id), None)
'''


def fmt_shares(shares: dict[str, float]) -> str:
    items = [f'"{g}": {shares[g]:.3f}' for g in GROUPS if shares.get(g, 0.0) >= 0.0005]
    return "{" + ", ".join(items) + "}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("select", "build"), required=True)
    parser.add_argument("--target", type=int, default=2000, help="number of regions to keep")
    parser.add_argument("--poly-tolerance", type=float, default=60.0, help="polygon simplification in metres")
    args = parser.parse_args()
    if args.stage == "select":
        stage_select(args)
    else:
        stage_build(args)


if __name__ == "__main__":
    main()
