from app.zones import ZONES

CATALONIA_BBOX = {"lat_min": 40.4, "lat_max": 42.9, "lon_min": 0.1, "lon_max": 3.4}
VALID_ASPECTS = {"N", "NE", "NW", "E", "W", "SE", "SW", "S"}
VALID_COVERS = {"dense", "moderate", "open"}


def test_at_least_150_sectors():
    assert len(ZONES) >= 830


def test_at_least_55_areas():
    areas = {z.area for z in ZONES}
    assert len(areas) >= 380


def test_unique_ids():
    ids = [z.id for z in ZONES]
    assert len(ids) == len(set(ids))


def test_coords_inside_catalonia():
    for z in ZONES:
        assert CATALONIA_BBOX["lat_min"] <= z.lat <= CATALONIA_BBOX["lat_max"], z.id
        assert CATALONIA_BBOX["lon_min"] <= z.lon <= CATALONIA_BBOX["lon_max"], z.id


def test_elevation_plausible():
    for z in ZONES:
        assert 300 <= z.elevation_m <= 1900, z.id


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


def test_sector_metadata_non_empty():
    for z in ZONES:
        assert z.area and z.area.strip(), z.id
        assert z.access and z.access.strip(), z.id
        assert z.notes and z.notes.strip(), z.id


def test_areas_have_multiple_slopes():
    from collections import defaultdict

    by_area = defaultdict(list)
    for z in ZONES:
        by_area[z.area].append(z)
    for area, zones in by_area.items():
        if len(zones) > 1:
            assert len({z.aspect for z in zones}) >= 2, area


def test_covers_all_comarcas():
    comarcas = {z.comarca for z in ZONES}
    assert len(comarcas) >= 42


def test_cerdanya_fully_covered():
    """Every Baixa Cerdanya municipality with real rovelló forest has sectors."""
    cerdanya_areas = {z.area for z in ZONES if z.comarca == "Baixa Cerdanya"}
    required = {
        "Bellver de Cerdanya",
        "Alp",
        "Das",
        "Isòvol",
        "Lles de Cerdanya",
        "Meranges",
        "Guils de Cerdanya",
        "Fontanals de Cerdanya",
        "Bolvir · Urús",
        "Montellà i Martinet",
        "Ger",
        "Prullans",
        "Riu de Cerdanya",
    }
    missing = required - cerdanya_areas
    assert not missing, f"Cerdanya areas missing sectors: {missing}"
