from app.habitat import (
    classify_soil,
    derive_cover,
    derive_forest,
    derive_habitat_quality,
    pine_composition,
)


class TestPineComposition:
    def test_groups_and_normalisation(self):
        # 60% Scots (21), 30% black (22+25), 10% beech (71 -> broadleaf).
        shares = pine_composition([[21, 60.0], [22, 20.0], [25, 10.0], [71, 10.0]])
        assert abs(shares["scots"] - 0.6) < 1e-9
        assert abs(shares["black"] - 0.3) < 1e-9
        assert abs(shares["broadleaf"] - 0.1) < 1e-9
        assert abs(sum(shares.values()) - 1.0) < 1e-9

    def test_species_codes_map_to_groups(self):
        assert pine_composition([[21, 100.0]])["scots"] == 1.0
        assert pine_composition([[22, 100.0]])["black"] == 1.0
        assert pine_composition([[25, 100.0]])["black"] == 1.0
        assert pine_composition([[24, 100.0]])["aleppo"] == 1.0
        for code in (23, 26, 27, 28):
            assert pine_composition([[code, 100.0]])["coastal"] == 1.0

    def test_empty_stand(self):
        shares = pine_composition([])
        assert sum(shares.values()) == 0.0


class TestDeriveForest:
    def test_broadleaf_label_when_pine_minority(self):
        assert derive_forest({"broadleaf": 0.9, "scots": 0.1}) == "Broadleaf woods"

    def test_pure_pine_labels(self):
        assert derive_forest({"scots": 1.0}) == "Scots pine"
        assert derive_forest({"black": 1.0}) == "Black pine"
        assert derive_forest({"aleppo": 1.0}) == "Aleppo pine"

    def test_mixed_label_when_second_pine_substantial(self):
        assert derive_forest({"scots": 0.6, "black": 0.4}) == "Scots & black pine"

    def test_single_label_when_second_pine_minority(self):
        assert derive_forest({"scots": 0.9, "black": 0.1}) == "Scots pine"


class TestDeriveCover:
    def test_thresholds(self):
        assert derive_cover(70.0) == "dense"
        assert derive_cover(45.0) == "dense"
        assert derive_cover(44.9) == "moderate"
        assert derive_cover(20.0) == "moderate"
        assert derive_cover(19.9) == "open"
        assert derive_cover(0.0) == "open"


class TestDeriveHabitatQuality:
    def test_bounds(self):
        assert derive_habitat_quality(0.0) == 1
        assert derive_habitat_quality(-5.0) == 1
        assert derive_habitat_quality(70.0) == 5
        assert derive_habitat_quality(100.0) == 5

    def test_monotonic(self):
        assert derive_habitat_quality(20.0) < derive_habitat_quality(50.0)
        assert derive_habitat_quality(50.0) < derive_habitat_quality(80.0)


class TestClassifySoil:
    def test_basic_markers(self):
        assert classify_soil("Calcàries noduloses i lutites") == "basic"
        assert classify_soil("Margues i margocalcàries amb gres") == "basic"
        assert classify_soil("Dolomies i calcàries") == "basic"

    def test_acidic_markers(self):
        assert classify_soil("Granodiorites hercíniques") == "acidic"
        assert classify_soil("Gresos arcòsics, lutites vermelles") == "acidic"
        assert classify_soil("Pissarres paleozoiques") == "acidic"

    def test_basic_wins_over_acidic(self):
        # Mixed descriptions default to the more decisive calcareous signal.
        assert classify_soil("Calcàries amb nivells de pissarra") == "basic"

    def test_neutral_fallback(self):
        assert classify_soil("Lutites vermelles i argiles") == "neutral"
        assert classify_soil("Dipòsits al·luvials") == "neutral"
        assert classify_soil(None) == "neutral"
        assert classify_soil("") == "neutral"

    def test_gres_is_acidic(self):
        assert classify_soil("Lutites i gresos") == "acidic"
