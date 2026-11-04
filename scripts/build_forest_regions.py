"""Build forest regions from MFE50 stands: contiguous forest split by composition.

The 819 hand-curated zones had stylized geometry (1.4 x 1 km rectangles).
This script replaces that arbitrariness with regions derived from the
MFE50 forest stand polygons themselves:

1. Load every tree-covered stand of the four Catalan provinces
   (TFCCARB > 0 and SP1 > 0 — same filter as the habitat ingestion).
2. Classify each stand by tree composition: the dominant pine group
   when it holds >= 60% of the occupancy, else "mixed".
3. Merge contiguous stands of the same class (bridging 10 m slivers
   of the 1:50.000 cartography with a buffer, then one global shrink),
   and split the result into connected polygons — one forest region each.
4. Aggregate per region: area, area-weighted composition shares,
   area-weighted canopy cover (TFCCARB), stand count.
5. Keep regions >= --min-area hectares (default 25).

Stages (run in order; intermediates live in --work-dir, only the final
file is committed):

    build_forest_regions.py --stage stands     # shapefiles -> stands.pkl
    build_forest_regions.py --stage merge      # per-class unions -> regions_*.geojson
    build_forest_regions.py --stage finalize   # join + aggregate -> data/forest_regions.geojson

Stands are simplified to --simplify m tolerance before merging: the
1:50.000 cartography carries far more vertices than a region outline
needs, and the reduction keeps the unions inside a desktop's memory.

Usage (extra deps are not project dependencies):

    uv run --with geopandas --with pyshp \
        python scripts/build_forest_regions.py --stage stands
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.habitat import GROUPS, pine_composition

GIS_DIR = Path("/tmp/opencode/gis")
PROVINCES = ("08", "17", "25", "43")
MFE_CRS = 25830
WORK_DIR = Path("/tmp/opencode/regions-tmp")
OUT_FILE = WORK_DIR / "forest_regions.geojson"
BRIDGE_M = 10.0
DOMINANT_SHARE = 0.60
CELL_M = 10000.0
KEEP_COLS = ("TFCCARB", "SP1", "SP2", "SP3", "O1", "O2", "O3")


def stand_species(row) -> list[list[float]]:
    species = []
    for rank in (1, 2, 3):
        sp = row.get(f"SP{rank}")
        occ = row.get(f"O{rank}")
        if sp and sp > 0:
            species.append([int(sp), float(occ)])
    return species


def composition_class(shares: dict[str, float]) -> str:
    ranked = sorted(shares.items(), key=lambda kv: kv[1], reverse=True)
    group, share = ranked[0]
    if share >= DOMINANT_SHARE:
        return group
    return "mixed"


def load_stands(simplify: float):
    import geopandas as gpd
    import pandas as pd

    frames = []
    for prov in PROVINCES:
        candidates = sorted(GIS_DIR.glob(f"MFE50_{prov}_*/mfe50_{prov}.shp"))
        if not candidates:
            raise FileNotFoundError(f"MFE50 shapefile for province {prov} not found under {GIS_DIR}")
        gdf = gpd.read_file(candidates[0], columns=list(KEEP_COLS))
        frames.append(gdf)
        print(f"province {prov}: {len(gdf)} polygons", flush=True)
    allp = pd.concat(frames, ignore_index=True)
    del frames
    trees = allp[(allp["TFCCARB"].fillna(0) > 0) & (allp["SP1"].fillna(0) > 0)].copy()
    del allp
    print(f"tree-covered stands: {len(trees)}", flush=True)
    trees["shares"] = trees.apply(lambda r: pine_composition(stand_species(r)), axis=1)
    trees["comp_class"] = trees["shares"].map(composition_class)
    print(trees["comp_class"].value_counts().to_string(), flush=True)
    trees["geometry"] = trees.geometry.simplify(simplify)
    trees["rep_point"] = trees.geometry.representative_point()
    return trees


def stage_stands(args) -> None:
    trees = load_stands(args.simplify)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    trees.to_pickle(WORK_DIR / "stands.pkl")
    print(f"wrote {WORK_DIR / 'stands.pkl'}", flush=True)


def stage_merge(args) -> None:
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box
    from shapely.ops import unary_union

    trees = pd.read_pickle(WORK_DIR / "stands.pkl")
    xmin, ymin, xmax, ymax = trees.total_bounds
    nx = math.ceil((xmax - xmin) / CELL_M)
    ny = math.ceil((ymax - ymin) / CELL_M)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    for comp_class in sorted(trees["comp_class"].unique()):
        t0 = time.time()
        class_gdf = trees[trees["comp_class"] == comp_class]
        class_sidx = class_gdf.sindex
        cell_polys = []
        for ix in range(nx):
            for iy in range(ny):
                cx0, cy0 = xmin + ix * CELL_M, ymin + iy * CELL_M
                pos = class_sidx.query(box(cx0, cy0, cx0 + CELL_M, cy0 + CELL_M), predicate="intersects")
                if len(pos) == 0:
                    continue
                sel = class_gdf.iloc[pos]
                u = sel.geometry.buffer(BRIDGE_M).union_all()
                if not u.is_empty:
                    cell_polys.append(u)
        merged = unary_union(cell_polys)
        del cell_polys
        merged = merged.buffer(-BRIDGE_M)
        parts = [p for p in (merged.geoms if hasattr(merged, "geoms") else [merged]) if p.geom_type == "Polygon"]
        del merged
        kept = [p for p in parts if p.area / 1e4 >= args.min_area]
        print(f"class {comp_class}: {len(class_gdf)} stands -> {len(kept)} regions >= {args.min_area:g} ha ({time.time() - t0:.0f}s)", flush=True)
        gpd.GeoDataFrame({"comp_class": [comp_class] * len(kept)}, geometry=kept, crs=MFE_CRS).to_file(
            WORK_DIR / f"regions_{comp_class}.geojson", driver="GeoJSON"
        )
        del class_gdf, parts, kept


def stage_finalize(args) -> None:
    import geopandas as gpd
    import pandas as pd

    region_frames = [gpd.read_file(WORK_DIR / f"regions_{c}.geojson") for c in args.classes]
    regions = pd.concat(region_frames, ignore_index=True)
    del region_frames
    regions = regions.reset_index(drop=True)
    print(f"total regions: {len(regions)}", flush=True)

    trees = pd.read_pickle(WORK_DIR / "stands.pkl")
    pts = gpd.GeoDataFrame(
        {
            "tfccarb": trees["TFCCARB"].fillna(0.0).values,
            "stand_area": trees.geometry.area,
            "shares": trees["shares"].values,
        },
        geometry=trees["rep_point"].values,
        crs=MFE_CRS,
    )
    del trees
    joined = gpd.sjoin(pts, regions, how="inner", predicate="within")
    print(f"stands assigned: {len(joined)} / {len(pts)}", flush=True)

    from pyproj import Transformer
    from shapely.ops import transform as shp_transform

    proj = Transformer.from_crs(MFE_CRS, 4326, always_xy=True)

    def to_wgs(poly):
        return shp_transform(lambda x, y, z=None: proj.transform(x, y), poly)

    def weighted_share(sel, w, group):
        vals = sel["shares"].map(lambda s: s.get(group, 0.0)).values
        return float((w * vals).sum() / w.sum())

    out_features = []
    for idx, row in regions.iterrows():
        sel = joined[joined["index_right"] == idx]
        if len(sel) == 0:
            continue
        w = sel["stand_area"].values
        shares = {g: weighted_share(sel, w, g) for g in GROUPS}
        tfccarb = float((w * sel["tfccarb"].values).sum() / w.sum())
        poly84 = to_wgs(row.geometry.simplify(args.out_simplify))
        out_features.append(
            {
                "properties": {
                    "region_id": f"r{len(out_features) + 1:04d}",
                    "comp_class": row["comp_class"],
                    "area_ha": round(row.geometry.area / 1e4, 1),
                    "tfccarb": round(tfccarb, 1),
                    "n_stands": len(sel),
                    "shares": {g: round(v, 3) for g, v in shares.items() if v >= 0.005},
                },
                "geometry": json.loads(gpd.GeoSeries([poly84], crs=4326).to_json())["features"][0]["geometry"],
            }
        )

    payload = {
        "generated": time.strftime("%Y-%m-%d"),
        "crs": "EPSG:4326",
        "min_area_ha": args.min_area,
        "features": out_features,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    total_ha = sum(f["properties"]["area_ha"] for f in out_features)
    print(f"wrote {OUT_FILE}: {len(out_features)} regions, {total_ha:,.0f} ha total", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("stands", "merge", "finalize"), required=True)
    parser.add_argument("--min-area", type=float, default=25.0, help="minimum region area in hectares")
    parser.add_argument("--simplify", type=float, default=25.0, help="stand simplification tolerance in metres")
    parser.add_argument("--out-simplify", type=float, default=50.0, help="region outline simplification tolerance in metres")
    parser.add_argument(
        "--classes",
        nargs="*",
        default=["aleppo", "black", "broadleaf", "coastal", "mixed", "scots"],
        help="composition classes to load in the finalize stage",
    )
    args = parser.parse_args()
    if args.stage == "stands":
        stage_stands(args)
    elif args.stage == "merge":
        stage_merge(args)
    else:
        stage_finalize(args)


if __name__ == "__main__":
    main()
