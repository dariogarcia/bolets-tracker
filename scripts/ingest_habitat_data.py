"""Ingest measured forest and soil data for every zone centroid.

Two authoritative sources:

1. MFE50 — Mapa Forestal de España 1:50.000 (MITECO). Provincial
   shapefiles (EPSG:25830) sampled at each zone centroid: dominant tree
   species with occupancy, tree canopy cover (TFCCARB) and the forest
   formation name. Download the four Catalan provinces (08, 17, 25, 43)
   from https://www.miteco.gob.es/es/biodiversidad/servicios/banco-datos-naturaleza/informacion-disponible/mfe50_descargas_catalugna.html
   and unzip them into one directory before running.

2. ICGC — Servei de geologia territorial, geological units 1:50.000
   (layer 38 of the geologia_territorial MapServer). Point queries over
   HTTPS give the lithological unit (code + description) under each
   centroid, which is classified into acidic / neutral / basic bedrock.

Output: data/habitat_gis.json — the raw measured table consumed by
scripts/rebuild_zones_from_gis.py. The ICGC stage caches per zone, so
re-running only re-fetches what is missing.

Usage (extra deps are not project dependencies):

    uv run --with geopandas --with pyshp --with xlrd \
        python scripts/ingest_habitat_data.py --gis-dir /path/to/gis

    uv run python scripts/ingest_habitat_data.py --geol-only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_OUT = ROOT / "data" / "habitat_gis.json"
GEOLOGY_URL = (
    "https://geoserveis.icgc.cat/vector01/rest/services/"
    "geologia_territorial/MapServer/38/query"
)
MFE50_URLS = {
    "08": "https://www.miteco.gob.es/content/dam/miteco/es/biodiversidad/servicios/banco-datos-naturaleza/MFE50_08_tcm30-200111.zip",
    "17": "https://www.miteco.gob.es/content/dam/miteco/es/biodiversidad/servicios/banco-datos-naturaleza/MFE50_17_tcm30-200090.zip",
    "25": "https://www.miteco.gob.es/content/dam/miteco/es/biodiversidad/servicios/banco-datos-naturaleza/MFE50_25_tcm30-200080.zip",
    "43": "https://www.miteco.gob.es/content/dam/miteco/es/biodiversidad/servicios/banco-datos-naturaleza/MFE50_43_tcm30-200092.zip",
}


def load_zones():
    from app.zones import ZONES

    return ZONES


def ingest_mfe(gis_dir: Path, zones) -> dict[str, dict]:
    import geopandas as gpd
    from pyproj import Transformer
    from shapely.geometry import Point

    frames = []
    for prov, _ in sorted(MFE50_URLS.items()):
        candidates = sorted(gis_dir.glob(f"MFE50_{prov}_*/mfe50_{prov}.shp"))
        if not candidates:
            raise FileNotFoundError(f"MFE50 shapefile for province {prov} not found under {gis_dir}")
        gdf = gpd.read_file(candidates[0])
        gdf["PROV"] = prov
        frames.append(gdf)
        print(f"  province {prov}: {len(gdf)} polygons")

    import pandas as pd

    all_polys = pd.concat(frames, ignore_index=True)
    sidx = all_polys.sindex

    has_trees = (all_polys["TFCCARB"].fillna(0) > 0) & all_polys["SP1"].fillna(0) > 0
    tree_gdf = all_polys[has_trees]
    from shapely import STRtree

    tree_strtree = STRtree(tree_gdf.geometry.values)

    to_utm = Transformer.from_crs(4326, 25830, always_xy=True)
    out: dict[str, dict] = {}
    misses = 0
    for zone in zones:
        x, y = to_utm.transform(zone.lon, zone.lat)
        pt = Point(x, y)
        idx = next(iter(sidx.query(pt, predicate="intersects")), None)
        source = "contains"
        distance_m = 0.0
        if idx is None or not has_trees.iloc[idx]:
            # Centroid fell outside the map or on a treeless polygon:
            # fall back to the nearest tree-covered stand within 2 km.
            near = tree_strtree.query_nearest(pt, max_distance=2000, return_distance=True)
            if len(near[0]) == 0:
                out[zone.id] = {"mfe": None}
                misses += 1
                continue
            pos, distance_m = int(near[0][0]), float(near[1][0])
            row = tree_gdf.iloc[pos]
            source = "nearest"
        else:
            row = all_polys.iloc[idx]

        species = []
        for rank in (1, 2, 3):
            sp = row.get(f"SP{rank}")
            occ = row.get(f"O{rank}")
            if sp and sp > 0:
                # O is occupancy in tenths of a percent of the tree cover.
                species.append([int(sp), float(occ) / 10.0])
        out[zone.id] = {
            "mfe": {
                "source": source,
                "distance_m": round(distance_m, 1),
                "province": str(row.get("PROV", "")),
                "tfccarb": float(row.get("TFCCARB") or 0.0),
                "tipestr": int(row.get("TIPESTR") or 0),
                "species": species,
                "formation": str(row.get("NOM_FORARB") or "").strip() or None,
            }
        }
    print(f"  matched {len(zones) - misses}/{len(zones)} zones ({misses} without a stand within 2 km)")
    return out


def fetch_geology(zone, cache: dict) -> dict | None:
    if zone.id in cache and cache[zone.id] is not None:
        return cache[zone.id]
    params = {
        "f": "json",
        "where": "1=1",
        "outFields": "Codi,Descripcio,Edat",
        "returnGeometry": "false",
        "geometryType": "esriGeometryPoint",
        "geometry": json.dumps({"x": zone.lon, "y": zone.lat}),
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
    }
    url = GEOLOGY_URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bolets-tracker/1.0 (habitat ingestion)"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            feats = payload.get("features") or []
            if not feats:
                return None
            attrs = feats[0]["attributes"]
            return {
                "codi": attrs.get("Codi"),
                "descripcio": attrs.get("Descripcio"),
                "edat": attrs.get("Edat"),
            }
        except Exception as exc:  # noqa: BLE001 - network retries
            if attempt == 2:
                print(f"    geology query failed for {zone.id}: {exc}")
                return None
            time.sleep(2.0 * (attempt + 1))
    return None


def ingest_geology(zones, cache: dict) -> dict:
    missing = [z for z in zones if z.id not in cache]
    print(f"  geology: {len(cache)} cached, {len(missing)} to fetch")
    for fetched, zone in enumerate(missing, start=1):
        cache[zone.id] = fetch_geology(zone, cache)
        if fetched % 100 == 0:
            print(f"    {fetched}/{len(missing)}")
        time.sleep(0.15)
    return cache


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gis-dir", type=Path, default=Path("/tmp/opencode/gis"))
    parser.add_argument("--geol-only", action="store_true", help="only run the ICGC stage")
    args = parser.parse_args()

    zones = load_zones()
    print(f"loaded {len(zones)} zones")

    merged: dict[str, dict] = {}
    geol_cache: dict[str, dict | None] = {}
    if DATA_OUT.exists():
        old = json.loads(DATA_OUT.read_text(encoding="utf-8"))
        geol_cache = {zid: e.get("geol") for zid, e in old.get("zones", {}).items()}
        if not args.geol_only:
            merged = {zid: e for zid, e in old.get("zones", {}).items()}

    if not args.geol_only:
        print("MFE50 stage:")
        mfe = ingest_mfe(args.gis_dir, zones)
        for zid, rec in mfe.items():
            merged.setdefault(zid, {})["mfe"] = rec["mfe"]

    print("ICGC geology stage:")
    geol = ingest_geology(zones, geol_cache)

    zones_out = {}
    for zone in zones:
        entry = merged.get(zone.id, {})
        entry["geol"] = geol.get(zone.id)
        zones_out[zone.id] = entry

    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "retrieved": date.today().isoformat(),
        "sources": {
            "mfe50": {
                "title": "Mapa Forestal de España 1:50.000",
                "provider": "Ministerio para la Transición Ecológica y el Reto Demográfico",
                "licence": "free reuse with attribution (© MITECO)",
                "urls": MFE50_URLS,
            },
            "icgc_geology": {
                "title": "Unitats geològiques 1:50.000 (Servei de geologia territorial)",
                "provider": "Institut Cartogràfic i Geològic de Catalunya",
                "licence": "CC-BY 4.0 (© Institut Cartogràfic i Geològic de Catalunya)",
                "url": GEOLOGY_URL,
            },
        },
        "zones": zones_out,
    }
    DATA_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    n_mfe = sum(1 for z in zones_out.values() if z.get("mfe"))
    n_geo = sum(1 for z in zones_out.values() if z.get("geol"))
    print(f"wrote {DATA_OUT}: {n_mfe} zones with MFE50 data, {n_geo} with geology")


if __name__ == "__main__":
    main()
