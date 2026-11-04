from app.habitat import GROUPS
from app.zones import ZONES

CATALONIA_BBOX = {"lat_min": 40.4, "lat_max": 42.9, "lon_min": 0.1, "lon_max": 3.4}
VALID_ASPECTS = {"N", "NE", "NW", "E", "W", "SE", "SW", "S", "flat"}
VALID_COVERS = {"dense", "moderate", "open"}
VALID_SOILS = {"acidic", "neutral", "basic"}


def test_zone_count():
    """Zones are GIS forest regions: the top-ranked 2,000 of the 4,167
    accessible MFE50 composition regions (see scripts/rebuild_zones_from_regions.py)."""
    assert len(ZONES) == 2000


def test_zone_ids_unique_and_stable():
    ids = [z.id for z in ZONES]
    assert len(ids) == len(set(ids))
    classes = {"scots", "black", "aleppo", "coastal", "broadleaf", "mixed"}
    for z in ZONES:
        assert set(z.id.split("-")) & classes, z.id


def test_coords_inside_catalonia():
    for z in ZONES:
        assert CATALONIA_BBOX["lat_min"] <= z.lat <= CATALONIA_BBOX["lat_max"], z.id
        assert CATALONIA_BBOX["lon_min"] <= z.lon <= CATALONIA_BBOX["lon_max"], z.id


def test_elevation_plausible():
    """From sea-level coastal pine stands to subalpine black pine."""
    for z in ZONES:
        assert 0 <= z.elevation_m <= 2500, z.id


def test_rating_fields_in_range():
    for z in ZONES:
        assert 1 <= z.habitat_quality <= 5, z.id
        assert 1 <= z.popularity <= 10, z.id
        assert 1 <= z.accessibility <= 10, z.id


def test_walk_min_plausible():
    for z in ZONES:
        assert 0 <= z.walk_min <= 180, z.id


def test_aspect_and_cover_valid():
    for z in ZONES:
        assert z.aspect in VALID_ASPECTS, z.id
        assert z.cover in VALID_COVERS, z.id


def test_measured_habitat_attributes():
    for z in ZONES:
        assert z.soil in VALID_SOILS, z.id
        assert set(z.forest_shares) <= set(GROUPS), z.id
        assert abs(sum(z.forest_shares.values()) - 1.0) < 0.01, z.id
        assert all(0.0 <= s <= 1.0 for s in z.forest_shares.values()), z.id
        assert z.geology.strip(), z.id


def test_soil_classes_balanced():
    """The ICGC lithology split must cover all three bedrock chemistries."""
    soils = {z.soil for z in ZONES}
    assert soils == VALID_SOILS


def test_zone_metadata_non_empty():
    for z in ZONES:
        assert z.area and z.area.strip(), z.id
        assert z.access and z.access.strip(), z.id
        assert z.notes and z.notes.strip(), z.id
        assert z.name and z.name.strip(), z.id


def test_comarca_is_area_grouping():
    """Generated zones group by comarca (area == comarca)."""
    comarcas = {z.comarca for z in ZONES}
    assert len(comarcas) >= 40
    for z in ZONES:
        assert z.area == z.comarca, z.id


def test_polygons_present():
    """Every zone carries its measured MFE50 region outline."""
    from app.zones import _POLYGONS

    missing = [z.id for z in ZONES if not z.polygon]
    assert not missing, f"{len(missing)} zones without polygon: {missing[:5]}"
    for z in ZONES:
        assert all(len(pt) == 2 for pt in z.polygon), z.id
        lats = [pt[0] for pt in z.polygon]
        lons = [pt[1] for pt in z.polygon]
        assert CATALONIA_BBOX["lat_min"] <= min(lats) and max(lats) <= CATALONIA_BBOX["lat_max"], z.id
        assert CATALONIA_BBOX["lon_min"] <= min(lons) and max(lons) <= CATALONIA_BBOX["lon_max"], z.id


def test_staging_point_near_polygon():
    """The routing destination must sit on or next to the region it serves."""
    for z in ZONES:
        lats = [pt[0] for pt in z.polygon]
        lons = [pt[1] for pt in z.polygon]
        assert min(lats) - 0.02 <= z.lat <= max(lats) + 0.02, z.id
        assert min(lons) - 0.02 <= z.lon <= max(lons) + 0.02, z.id


def test_inherited_lore_preserved():
    """Regions containing a legacy curated staging point keep its lore
    (generated notes start with the region area in hectares)."""
    inherited = [z for z in ZONES if not z.notes.split(" ")[0].replace(".", "").isdigit()]
    assert len(inherited) >= 100, f"only {len(inherited)} zones with inherited notes"
