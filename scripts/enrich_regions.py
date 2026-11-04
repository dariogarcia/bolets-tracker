"""Enrich forest regions with measured terrain, soil, admin, names and roads.

Consumes the region geometry built by scripts/build_forest_regions.py
(<work-dir>/forest_regions.geojson) and measures, per region:

- geology   ICGC 1:50.000 lithological unit at the centroid, classified
            into acidic / neutral / basic bedrock (app/habitat.py)
- comarca   ICGC comarca polygons (local point-in-polygon)
- roads     ICGC 1:5.000 transport axes near the region: distance to
            the nearest road/track, the staging point on that road and
            the walking distance to the forest edge
- terrain   Open-Meteo elevation API on a 3x3 grid at the centroid:
            elevation, slope and downhill aspect
- names     ICGC nomenclàtor toponyms near the centroid, ranked by
            concept priority and distance (for region naming)

Every stage caches into data/forest_regions_attrs.json and can be
re-run; only missing regions are fetched. The geology, comarca and
roads stages need every region; run terrain and names after the Stage C
pre-selection to skip regions that will not become zones.

Usage (extra deps are not project dependencies):

    uv run --with shapely --with pyproj \
        python scripts/enrich_regions.py --stage geology
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


WORK_DIR = Path("/tmp/opencode/regions-tmp")
REGIONS_FILE = WORK_DIR / "forest_regions.geojson"
ATTRS_FILE = ROOT / "data" / "forest_regions_attrs.json"

GEOLOGY_URL = (
    "https://geoserveis.icgc.cat/vector01/rest/services/"
    "geologia_territorial/MapServer/38/query"
)
COMARQUES_URL = (
    "https://geoserveis.icgc.cat/vector01/rest/services/"
    "divisions_administratives_wfs/MapServer/10/query"
)
ROADS_URL = (
    "https://geoserveis.icgc.cat/vector01/rest/services/"
    "topografia_territorial/MapServer/25/query"
)
NAMES_URL = (
    "https://geoserveis.icgc.cat/vector01/rest/services/"
    "noms_geografics/MapServer/2/query"
)
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"

UTM = 25831
ROAD_TYPES = ("mca", "cor", "mvi", "fac")
ACCESS_BUFFER_M = 1500.0
LARGE_REGION_KM2 = 400.0
NAME_BOX_M = 1500.0
GRID_SPACING_M = 200.0

# Toponym concept -> distance penalty in metres (lower wins).
CONCEPT_PRIORITY = {
    "Massís, serra": 0,
    "Indret": 100,
    "Orografia (altres)": 200,
    "Cim": 300,
    "Edificació històrica": 800,
    "Disseminat": 900,
    "Edificació": 1500,
    "Entitat de població": 2000,
    "Barri": 2500,
    "Cap de municipi": 2500,
}

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

UA = {"User-Agent": "bolets-tracker/1.0 (region enrichment)"}


def http_json(url: str, params: dict, timeout: int = 30) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            req = urllib.request.Request(full, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:  # noqa: BLE001 - non-JSON error body
                body = {}
            if e.code == 429 or body.get("reason", "").startswith("Hourly API"):
                return {"_ratelimit": True}
            if attempt == 2:
                return {}
            time.sleep(2.0 * (attempt + 1))
        except Exception:  # noqa: BLE001 - network retries
            if attempt == 2:
                return {}
            time.sleep(2.0 * (attempt + 1))
    return {}


def load_regions() -> list[dict]:
    payload = json.loads(REGIONS_FILE.read_text(encoding="utf-8"))
    return payload["features"]


def load_attrs() -> dict:
    if ATTRS_FILE.exists():
        return json.loads(ATTRS_FILE.read_text(encoding="utf-8"))
    return {}


def save_attrs(attrs: dict) -> None:
    ATTRS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ATTRS_FILE.write_text(json.dumps(attrs, ensure_ascii=False, indent=1), encoding="utf-8")


def region_centroid_utm(feature: dict):
    """Centroid in EPSG:25831 (mean of exterior ring vertices is fine
    for naming and queries; the polygon itself is used for distances)."""
    from pyproj import Transformer

    ring = feature["geometry"]["coordinates"][0]
    to_utm = Transformer.from_crs(4326, UTM, always_xy=True)
    xs = [to_utm.transform(lon, lat)[0] for lon, lat in ring]
    ys = [to_utm.transform(lon, lat)[1] for lon, lat in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def region_polygon_utm(feature: dict):
    from pyproj import Transformer
    from shapely.geometry import Polygon
    from shapely.ops import transform as shp_transform

    to_utm = Transformer.from_crs(4326, UTM, always_xy=True)
    poly = Polygon(feature["geometry"]["coordinates"][0])
    return shp_transform(lambda x, y, z=None: to_utm.transform(x, y), poly)


def utm_to_wgs(x: float, y: float) -> tuple[float, float]:
    from pyproj import Transformer

    lon, lat = Transformer.from_crs(UTM, 4326, always_xy=True).transform(x, y)
    return round(lat, 6), round(lon, 6)


def stage_geology(args) -> None:
    regions = load_regions()
    attrs = load_attrs()
    todo = []
    for f in regions:
        rid = f["properties"]["region_id"]
        if not (attrs.get(rid, {}).get("geol")):
            todo.append((rid, f))
    print(f"geology: {len(regions) - len(todo)} cached, {len(todo)} to fetch")

    def work(item):
        rid, feature = item
        cx, cy = region_centroid_utm(feature)
        params = {
            "f": "json",
            "where": "1=1",
            "outFields": "Codi,Descripcio,Edat",
            "returnGeometry": "false",
            "geometryType": "esriGeometryPoint",
            "geometry": json.dumps({"x": cx, "y": cy}),
            "inSR": UTM,
            "spatialRel": "esriSpatialRelIntersects",
        }
        payload = http_json(GEOLOGY_URL, params)
        feats = payload.get("features") or []
        entry = attrs.setdefault(rid, {})
        if feats:
            a = feats[0]["attributes"]
            entry["geol"] = {
                "codi": a.get("Codi"),
                "descripcio": a.get("Descripcio"),
                "edat": a.get("Edat"),
            }
        else:
            entry["geol"] = None
        return entry["geol"] is not None

    done = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for ok in pool.map(work, todo):
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(todo)}")
                save_attrs(attrs)
    save_attrs(attrs)
    hits = sum(1 for rid, _ in todo if attrs.get(rid, {}).get("geol"))
    print(f"geology: fetched {hits}/{len(todo)} with a unit")


def stage_comarca(args) -> None:
    regions = load_regions()
    attrs = load_attrs()
    todo = [f for f in regions if not attrs.get(f["properties"]["region_id"], {}).get("comarca")]
    if not todo:
        print("comarca: all cached")
        return

    payload = http_json(
        COMARQUES_URL,
        {
            "f": "geojson",
            "where": "1=1",
            "outFields": "NOMCOMAR",
            "returnGeometry": "true",
            "outSR": UTM,
            "resultRecordCount": 100,
        },
        timeout=60,
    )
    comarques = []
    from shapely.geometry import shape
    from shapely.prepared import prep

    for f in payload.get("features", []):
        if f.get("geometry") is None:
            continue
        poly = shape(f["geometry"])
        comarques.append((f["properties"]["NOMCOMAR"], poly, prep(poly)))
    print(f"comarca: {len(comarques)} polygons loaded")

    from shapely.geometry import Point

    misses = 0
    for f in todo:
        rid = f["properties"]["region_id"]
        cx, cy = region_centroid_utm(f)
        pt = Point(cx, cy)
        for name, poly, prepared in comarques:
            if prepared.contains(pt) or poly.contains(pt):
                attrs.setdefault(rid, {})["comarca"] = name
                break
        else:
            misses += 1
            attrs.setdefault(rid, {})["comarca"] = None
    save_attrs(attrs)
    print(f"comarca: assigned {len(todo) - misses}/{len(todo)} ({misses} outside)")


def parse_polyline(geom: dict):
    from shapely.geometry import LineString, MultiLineString

    if geom is None:
        return None
    paths = geom.get("paths")
    if not paths:
        return None
    lines = [LineString(p) for p in paths if len(p) >= 2]
    if not lines:
        return None
    return lines[0] if len(lines) == 1 else MultiLineString(lines)


def fetch_roads(bbox: tuple[float, float, float, float], partial: bool) -> list[dict]:
    xmin, ymin, xmax, ymax = bbox
    features: list[dict] = []
    offset = 0
    for _ in range(3):
        params = {
            "f": "json",
            "where": "tipus IN ('mca','cor','mvi','fac')",
            "outFields": "tipus,nom",
            "returnGeometry": "true",
            "outSR": UTM,
            "maxAllowableOffset": 20,
            "geometry": json.dumps({"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}),
            "geometryType": "esriGeometryEnvelope",
            "inSR": UTM,
            "spatialRel": "esriSpatialRelIntersects",
            "resultRecordCount": 2000,
            "resultOffset": offset,
        }
        payload = http_json(ROADS_URL, params, timeout=60)
        feats = payload.get("features") or []
        features.extend(feats)
        if len(feats) < 2000 or not payload.get("exceededTransferLimit"):
            break
        offset += 2000
        partial = True
    return features, partial


def fetch_roads_intersecting(poly) -> list[dict]:
    """Roads that cross or touch the region polygon itself (small result)."""
    from shapely.geometry import mapping

    params = {
        "f": "json",
        "where": "tipus IN ('mca','cor','mvi','fac')",
        "outFields": "tipus,nom",
        "returnGeometry": "true",
        "outSR": UTM,
        "maxAllowableOffset": 20,
        "geometry": json.dumps(mapping(poly)),
        "geometryType": "esriGeometryPolygon",
        "inSR": UTM,
        "spatialRel": "esriSpatialRelIntersects",
        "resultRecordCount": 2000,
    }
    payload = http_json(ROADS_URL, params, timeout=60)
    return payload.get("features") or []


def stage_roads(args) -> None:
    from shapely.ops import nearest_points

    regions = load_regions()
    attrs = load_attrs()
    todo = []
    for f in regions:
        rid = f["properties"]["region_id"]
        if "roads" not in attrs.get(rid, {}):
            todo.append((rid, f))
    print(f"roads: {len(regions) - len(todo)} cached, {len(todo)} to fetch")

    def work(item):
        rid, feature = item
        cx, cy = region_centroid_utm(feature)
        poly = region_polygon_utm(feature)
        feats = fetch_roads_intersecting(poly)
        partial = False
        if not feats:
            minx, miny, maxx, maxy = poly.bounds
            partial = (maxx - minx) * (maxy - miny) / 1e6 > LARGE_REGION_KM2
            if partial:
                minx, miny, maxx, maxy = cx - 5000, cy - 5000, cx + 5000, cy + 5000
            else:
                minx, miny = minx - ACCESS_BUFFER_M, miny - ACCESS_BUFFER_M
                maxx, maxy = maxx + ACCESS_BUFFER_M, maxy + ACCESS_BUFFER_M
            feats, partial = fetch_roads((minx, miny, maxx, maxy), partial)
        best = None
        for f in feats:
            line = parse_polyline(f.get("geometry"))
            if line is None:
                continue
            d = poly.distance(line)
            if best is None or d < best[0]:
                best = (d, line, f["attributes"])
        entry = attrs.setdefault(rid, {})
        if best is None:
            entry["roads"] = {"dist_m": None, "partial": partial}
        else:
            dist, line, a = best
            staging = nearest_points(line, poly)[0]
            entry["roads"] = {
                "dist_m": round(dist, 1),
                "staging": utm_to_wgs(staging.x, staging.y),
                "tipus": a.get("tipus"),
                "nom": (a.get("nom") or "").strip() or None,
                "partial": partial,
            }
        return entry["roads"]["dist_m"] is not None

    done = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for ok in pool.map(work, todo):
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(todo)}")
                save_attrs(attrs)
    save_attrs(attrs)
    hits = sum(1 for rid, _ in todo if (attrs.get(rid, {}).get("roads") or {}).get("dist_m") is not None)
    print(f"roads: {hits}/{len(todo)} with a road in range")


def stage_terrain(args) -> None:
    regions = load_regions()
    attrs = load_attrs()
    only = set(args.regions) if args.regions else None
    todo = []
    for f in regions:
        rid = f["properties"]["region_id"]
        if only is not None and rid not in only:
            continue
        if not attrs.get(rid, {}).get("terrain"):
            todo.append((rid, f))
    print(f"terrain: {len(todo)} to fetch")

    import math

    from pyproj import Transformer

    to_utm = Transformer.from_crs(4326, UTM, always_xy=True)
    to_wgs = Transformer.from_crs(UTM, 4326, always_xy=True)

    jobs = []
    for rid, feature in todo:
        ring = feature["geometry"]["coordinates"][0]
        lat = sum(p[1] for p in ring) / len(ring)
        lon = sum(p[0] for p in ring) / len(ring)
        cx, cy = to_utm.transform(lon, lat)
        pts = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                x, y = to_wgs.transform(cx + dx * GRID_SPACING_M, cy + dy * GRID_SPACING_M)
                pts.append((x, y))
        jobs.append((rid, cx, cy, pts))

    def compute(rid, cx, cy, pts, elevations):
        c = 4
        dzdx = (elevations[5] - elevations[3]) / (2 * GRID_SPACING_M)
        dzdy = (elevations[7] - elevations[1]) / (2 * GRID_SPACING_M)
        slope = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
        bearing = (math.degrees(math.atan2(-dzdx, -dzdy)) + 360.0) % 360.0
        if slope < 1.5:
            aspect = "flat"
        else:
            aspect = COMPASS[int(((bearing + 22.5) % 360.0) // 45)]
        attrs.setdefault(rid, {})["terrain"] = {
            "elev": round(elevations[c], 1),
            "slope": round(slope, 1),
            "aspect": aspect,
        }

    batch = 11
    for i in range(0, len(jobs), batch):
        chunk = jobs[i : i + batch]
        lats, lons = [], []
        for _, _, _, pts in chunk:
            for lon, lat in pts:
                lats.append(f"{lat:.5f}")
                lons.append(f"{lon:.5f}")
        payload = http_json(ELEVATION_URL, {"latitude": ",".join(lats), "longitude": ",".join(lons)})
        if payload.get("_ratelimit"):
            print("  hourly API limit reached — stopping this pass, will resume later")
            break
        elevations = payload.get("elevation") or []
        if len(elevations) != len(lats):
            print(f"  batch {i}: got {len(elevations)}/{len(lats)} elevations, skipping")
            continue
        for j, (rid, cx, cy, pts) in enumerate(chunk):
            compute(rid, cx, cy, pts, elevations[j * 9 : (j + 1) * 9])
        if (i // batch) % 20 == 0:
            print(f"  {i + len(chunk)}/{len(jobs)}")
            save_attrs(attrs)
    save_attrs(attrs)
    print(f"terrain: done ({sum(1 for rid, _ in todo if attrs.get(rid, {}).get('terrain'))}/{len(todo)})")


def stage_names(args) -> None:
    regions = load_regions()
    attrs = load_attrs()
    only = set(args.regions) if args.regions else None
    todo = []
    for f in regions:
        rid = f["properties"]["region_id"]
        if only is not None and rid not in only:
            continue
        if not attrs.get(rid, {}).get("names"):
            todo.append((rid, f))
    print(f"names: {len(todo)} to fetch")

    from shapely.geometry import Point

    def work(item):
        rid, feature = item
        cx, cy = region_centroid_utm(feature)
        params = {
            "f": "json",
            "where": "1=1",
            "outFields": "Toponim,Concepte",
            "returnGeometry": "true",
            "outSR": UTM,
            "geometry": json.dumps(
                {"xmin": cx - NAME_BOX_M, "ymin": cy - NAME_BOX_M, "xmax": cx + NAME_BOX_M, "ymax": cy + NAME_BOX_M}
            ),
            "geometryType": "esriGeometryEnvelope",
            "inSR": UTM,
            "spatialRel": "esriSpatialRelIntersects",
            "resultRecordCount": 500,
        }
        payload = http_json(NAMES_URL, params)
        pt = Point(cx, cy)
        candidates = []
        for f in payload.get("features", []):
            a = f["attributes"]
            penalty = CONCEPT_PRIORITY.get(a.get("Concepte"))
            if penalty is None:
                continue
            geom = f.get("geometry")
            if not geom or not geom.get("paths"):
                continue
            best_d = None
            for path in geom["paths"]:
                for x, y in path:
                    d = pt.distance(Point(x, y))
                    if best_d is None or d < best_d:
                        best_d = d
            if best_d is not None:
                candidates.append((best_d + penalty, round(best_d, 0), a.get("Toponim"), a.get("Concepte")))
        candidates.sort()
        attrs.setdefault(rid, {})["names"] = [
            {"t": t, "c": c, "d": d} for _, d, t, c in candidates[:5]
        ]

    done = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for _ in pool.map(work, todo):
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(todo)}")
                save_attrs(attrs)
    save_attrs(attrs)
    print(f"names: done ({sum(1 for rid, _ in todo if attrs.get(rid, {}).get('names'))}/{len(todo)})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("geology", "comarca", "roads", "terrain", "names"), required=True)
    parser.add_argument("--regions", nargs="*", help="restrict terrain/names to these region ids")
    args = parser.parse_args()
    {"geology": stage_geology, "comarca": stage_comarca, "roads": stage_roads, "terrain": stage_terrain, "names": stage_names}[
        args.stage
    ](args)


if __name__ == "__main__":
    main()
