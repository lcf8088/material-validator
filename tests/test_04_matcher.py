"""
Test 04: SpecMatcher - Auto-detection of specs from MTR data.
"""

import pytest
from lib.matcher import SpecMatcher


class TestUNSMatching:
    def test_match_4140_by_uns(self, mtr_4140, specs_dir):
        m = SpecMatcher(specs_dir)
        matches = m.find_matching_specs(mtr_4140)
        spec_ids = [sid for sid, _, _ in matches]
        # G41400 should match both ES-M0001C and ES-M0001G
        assert "ES-M0001C" in spec_ids or "ES-M0001G" in spec_ids

    def test_match_303_by_uns(self, mtr_303, specs_dir):
        m = SpecMatcher(specs_dir)
        matches = m.find_matching_specs(mtr_303)
        spec_ids = [sid for sid, _, _ in matches]
        assert "ES-M0003A" in spec_ids or "ES-M0003E" in spec_ids

    def test_no_match_for_unknown(self, specs_dir):
        m = SpecMatcher(specs_dir)
        data = {"heat_number": "X", "material_grade": "UNOBTANIUM", "uns": "Z99999"}
        matches = m.find_matching_specs(data)
        assert len(matches) == 0


class TestGradeMatching:
    def test_match_by_grade_name(self, specs_dir):
        m = SpecMatcher(specs_dir)
        data = {"material_grade": "4140", "mechanical": {"yield_strength": 90}}
        matches = m.find_matching_specs(data)
        assert len(matches) >= 1

    def test_partial_grade_match(self, specs_dir):
        m = SpecMatcher(specs_dir)
        data = {"material_grade": "AISI 4140"}
        matches = m.find_matching_specs(data)
        assert len(matches) >= 1


class TestSelectBestSpec:
    def test_select_best_for_110mys_4140(self, mtr_4140, specs_dir):
        """High-strength 4140 (YS=119.7) should prefer ES-M0001G (110 MYS spec)."""
        m = SpecMatcher(specs_dir)
        result = m.select_best_spec(mtr_4140)
        assert result is not None
        spec_id, confidence, reason = result
        assert spec_id == "ES-M0001G"
        assert confidence > 0.5

    def test_select_best_for_303(self, mtr_303, specs_dir):
        m = SpecMatcher(specs_dir)
        result = m.select_best_spec(mtr_303)
        assert result is not None
        spec_id, confidence, reason = result
        assert "ES-M0003" in spec_id

    def test_select_best_returns_none_for_unknown(self, specs_dir):
        m = SpecMatcher(specs_dir)
        result = m.select_best_spec({"material_grade": "UNOBTANIUM"})
        assert result is None

    def test_low_ys_prefers_standard_spec(self, specs_dir):
        """Standard-strength 4140 (YS=85) should prefer ES-M0001C over ES-M0001G."""
        m = SpecMatcher(specs_dir)
        data = {
            "material_grade": "4140",
            "uns": "G41400",
            "mechanical": {"yield_strength": 85.0},
        }
        result = m.select_best_spec(data)
        assert result is not None
        spec_id, _, _ = result
        assert spec_id == "ES-M0001C"


class TestSpecSummary:
    def test_get_spec_summary(self, specs_dir):
        m = SpecMatcher(specs_dir)
        s = m.get_spec_summary("ES-M0001C")
        assert s is not None
        assert s["id"] == "ES-M0001C"
        assert "4140" in s["grades"]

    def test_summary_returns_none_for_invalid(self, specs_dir):
        m = SpecMatcher(specs_dir)
        assert m.get_spec_summary("FAKE") is None

    def test_suggest_specs(self, specs_dir):
        m = SpecMatcher(specs_dir)
        suggestions = m.suggest_specs("4140")
        assert len(suggestions) >= 1
