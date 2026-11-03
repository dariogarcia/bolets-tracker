"""Derive measured habitat attributes from MFE50 and ICGC geology data.

The ingestion script (scripts/ingest_habitat_data.py) records, for every
zone centroid, the MFE50 forest stand (species with occupancy and canopy
cover) and the ICGC 1:50.000 lithological unit. This module turns those
raw measurements into the attributes the scoring model consumes:

- ``pine_composition`` — occupancy shares by tree group (scots, black,
  aleppo, coastal pine, broadleaf) used directly by the scoring model
- ``derive_forest`` — the display category (e.g. "Scots & black pine")
- ``derive_cover`` — canopy density class from the measured TFCCARB
- ``derive_habitat_quality`` — 1-5 from the measured tree canopy
- ``classify_soil`` — acidic / neutral / basic bedrock chemistry

MFE50 tree species codes (Ministerio de Agricultura dictionary):
21 Pinus sylvestris, 22 P. uncinata, 23 P. pinea, 24 P. halepensis,
25 P. nigra, 26 P. pinaster, 27 P. canariensis, 28 P. radiata.
Non-pine conifers are rare in the dataset and are folded into the
"broadleaf" group.
"""

from __future__ import annotations

# MFE50 species code -> tree group.
PINE_GROUPS: dict[int, str] = {
    21: "scots",
    22: "black",
    25: "black",
    24: "aleppo",
    23: "coastal",
    26: "coastal",
    27: "coastal",
    28: "coastal",
}

GROUPS = ("scots", "black", "aleppo", "coastal", "broadleaf")

# Lithology keywords from the ICGC unit descriptions, most decisive first.
# Calcareous markers make the bedrock basic; siliceous markers acidic;
# anything else (clays, alluvium, undifferentiated clastics) is neutral.
BASIC_KEYWORDS = (
    "calcàr", "calcari", "calcària", "calcarenita", "margocalcàr", "marga",
    "dolomia", "dolomític", "travertí", "tufa", "guix", "creta",
    "evaporit", "lacustre", "estromatòlit", "rudistes",
)
ACIDIC_KEYWORDS = (
    "granit", "granodiorit", "tonalita", "quars", "pissarr", "esquist",
    "esquista", "fil·lit", "leptinita", "gnèis", "riolita", "rhodolita",
    "dacita", "porfir", "arcòs", "gres",
)


def pine_composition(species: list[list[float]]) -> dict[str, float]:
    """Occupancy shares by tree group from MFE50 (code, percent) pairs."""
    totals = {g: 0.0 for g in GROUPS}
    for code, pct in species:
        group = PINE_GROUPS.get(int(code), "broadleaf")
        totals[group] += float(pct) / 100.0
    total = sum(totals.values())
    if total <= 0:
        return totals
    return {k: v / total for k, v in totals.items()}


def derive_forest(shares: dict[str, float]) -> str:
    """Display category for the stand, e.g. "Scots & black pine".

    Purely cosmetic: the scoring model uses the full share vector, this
    label only names the dominant mixture for the UI.
    """
    pine_total = sum(shares.get(g, 0.0) for g in GROUPS if g != "broadleaf")
    if pine_total < 0.30:
        return "Broadleaf woods"
    ranked = sorted(
        ((g, shares.get(g, 0.0)) for g in ("scots", "black", "aleppo", "coastal")),
        key=lambda kv: kv[1],
        reverse=True,
    )
    (top_group, top_share), (second_group, second_share) = ranked[0], ranked[1]
    if second_share >= 0.20 and second_share >= 0.5 * top_share:
        return f"{top_group.title()} & {second_group} pine"
    return f"{top_group.title()} pine"


def derive_cover(tfccarb: float) -> str:
    """Canopy density class from the measured tree cover (TFCCARB, %)."""
    if tfccarb >= 45:
        return "dense"
    if tfccarb >= 20:
        return "moderate"
    return "open"


def derive_habitat_quality(tfccarb: float) -> int:
    """1-5 scale from the measured tree canopy (TFCCARB, % of ground shaded).

    A dense stand (>=70% cover) rates 5/5; this measures how much forest
    there is, while the species mixture and soil carry the species fit.
    """
    return max(1, min(5, 1 + round(4 * min(1.0, max(0.0, tfccarb) / 70.0))))


def classify_soil(descripcio: str | None) -> str:
    """Bedrock chemistry class from the ICGC lithological description."""
    if not descripcio:
        return "neutral"
    text = descripcio.lower()
    for kw in BASIC_KEYWORDS:
        if kw in text:
            return "basic"
    for kw in ACIDIC_KEYWORDS:
        if kw in text:
            return "acidic"
    return "neutral"
