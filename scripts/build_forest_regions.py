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


def stage_split(args) -> None:
    """Split regions larger than --max-area ha by recursive geometric cuts.

    Mega-regions are lace meshes of stands: any stand subset disconnects,
    so pieces are cut from the region polygon itself. Each cut halves the
    area with a straight line perpendicular to the minimum rotated
    rectangle's long axis (binary search on the cut position); recursion
    stops below --max-area. Pieces tile the parent exactly and may be
    MultiPolygons (a cut can detach mesh strands). Numbering is stable:
    unsplit regions keep their ids (r0001…), pieces get a letter suffix
    (r0123a…), and the stage is idempotent.
    """
    import geopandas as gpd
    from shapely.geometry import MultiPolygon, Polygon

    def piece_suffix(i: int) -> str:
        letters = ""
        i += 1
        while i:
            i, rem = divmod(i - 1, 26)
            letters = chr(ord("a") + rem) + letters
        return letters

    def make_poly(geom):
        """Keep only polygonal parts (cuts can yield degenerate slivers)."""
        if geom is None or geom.is_empty:
            return None
        geoms = geom.geoms if hasattr(geom, "geoms") else [geom]
        parts = []
        for g in geoms:
            if g.geom_type == "Polygon":
                parts.append(g)
            elif g.geom_type == "MultiPolygon":
                parts.extend(g.geoms)
        if not parts:
            return None
        return parts[0] if len(parts) == 1 else MultiPolygon(parts)

    def cut_in_half(poly):
        """Cut poly into two halves of ~equal area along its long axis."""
        mrr = poly.minimum_rotated_rectangle
        c = list(mrr.exterior.coords) if hasattr(mrr, "exterior") else None
        if c is None:
            return None
        # rectangle corners c0..c3; pick the longer edge as the u axis
        e1 = ((c[1][0] - c[0][0]) ** 2 + (c[1][1] - c[0][1]) ** 2) ** 0.5
        e2 = ((c[2][0] - c[1][0]) ** 2 + (c[2][1] - c[1][1]) ** 2) ** 0.5
        if e1 >= e2:
            o, u, v, length = c[0], (c[1][0] - c[0][0], c[1][1] - c[0][1]), (c[3][0] - c[0][0], c[3][1] - c[0][1]), e1
        else:
            o, u, v, length = c[1], (c[2][0] - c[1][0], c[2][1] - c[1][1]), (c[0][0] - c[1][0], c[0][1] - c[1][1]), e2
        ux, uy = u[0] / length, u[1] / length
        w = ((v[0] ** 2 + v[1] ** 2) ** 0.5) * 1.5
        vx, vy = v[0] / ((v[0] ** 2 + v[1] ** 2) ** 0.5), v[1] / ((v[0] ** 2 + v[1] ** 2) ** 0.5)
        half = poly.area / 2
        lo, hi = 0.05 * length, 0.95 * length
        best = None
        for _ in range(40):
            t = (lo + hi) / 2
            side = Polygon(
                [
                    (o[0] + ux * (t - length), o[1] + uy * (t - length)),
                    (o[0] + ux * t, o[1] + uy * t),
                    (o[0] + ux * t + vx * w, o[1] + uy * t + vy * w),
                    (o[0] + ux * (t - length) + vx * w, o[1] + uy * (t - length) + vy * w),
                ]
            )
            a = make_poly(poly.intersection(side))
            if a is None or a.area == 0:
                lo = t
                continue
            best = (a, make_poly(poly.difference(side)))
            if abs(a.area - half) < 0.005 * poly.area:
                break
            if a.area < half:
                lo = t
            else:
                hi = t
        if best is None or best[1] is None or best[1].area == 0:
            return None
        return best

    def split_poly(poly, depth=0):
        if poly.area / 1e4 <= args.max_area or poly.is_empty or depth >= 10:
            return [poly]
        halves = cut_in_half(poly)
        if halves is None:
            return [poly]
        a, b = halves
        if max(a.area, b.area) > 0.98 * poly.area:
            return [poly]
        return split_poly(a, depth + 1) + split_poly(b, depth + 1)

    offset = 0
    for comp_class in args.classes:
        gdf = gpd.read_file(WORK_DIR / f"regions_{comp_class}.geojson")
        had_base_id = "base_id" in gdf.columns
        if not had_base_id:
            gdf["base_id"] = [f"r{offset + i + 1:04d}" for i in range(len(gdf))]
        # advance by parent count: split files hold pieces sharing a prefix
        offset += gdf["base_id"].str.slice(0, 5).nunique()
        mega = gdf[gdf.geometry.area / 1e4 > args.max_area]
        if len(mega) == 0:
            if not had_base_id:
                gdf.to_file(WORK_DIR / f"regions_{comp_class}.geojson", driver="GeoJSON")
            print(f"class {comp_class}: no regions > {args.max_area:g} ha", flush=True)
            continue
        rows = []
        replaced = 0
        for _, row in gdf.iterrows():
            if row.geometry.area / 1e4 <= args.max_area:
                rows.append({"base_id": row["base_id"], "comp_class": comp_class, "geometry": row.geometry})
                continue
            replaced += 1
            pieces = [p for p in split_poly(row.geometry) if not p.is_empty and p.area / 1e4 >= args.min_area]
            pieces.sort(key=lambda p: (-p.area, p.centroid.x, p.centroid.y))
            if not pieces:
                rows.append({"base_id": row["base_id"], "comp_class": comp_class, "geometry": row.geometry})
                continue
            for i, p in enumerate(pieces):
                rows.append(
                    {"base_id": f"{row['base_id']}{piece_suffix(i)}", "comp_class": comp_class, "geometry": p}
                )
        out = gpd.GeoDataFrame(rows, crs=MFE_CRS)
        out.to_file(WORK_DIR / f"regions_{comp_class}.geojson", driver="GeoJSON")
        print(
            f"class {comp_class}: split {replaced} regions > {args.max_area:g} ha into "
            f"{sum(1 for r in rows if len(r['base_id']) > 5)} pieces ({len(out)} regions total)",
            flush=True,
        )


def stage_finalize(args) -> None:
    import geopandas as gpd
    import pandas as pd

    region_frames = [gpd.read_file(WORK_DIR / f"regions_{c}.geojson") for c in args.classes]
    regions = pd.concat(region_frames, ignore_index=True)
    del region_frames
    regions = regions.reset_index(drop=True)
    if "base_id" not in regions.columns:
        regions["base_id"] = [f"r{i + 1:04d}" for i in range(len(regions))]
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
                    "region_id": row["base_id"],
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
    parser.add_argument("--stage", choices=("stands", "merge", "split", "finalize"), required=True)
    parser.add_argument("--min-area", type=float, default=25.0, help="minimum region area in hectares")
    parser.add_argument("--max-area", type=float, default=5000.0, help="split regions above this area (hectares)")
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
    elif args.stage == "split":
        stage_split(args)
    else:
        stage_finalize(args)


if __name__ == "__main__":
    main()
