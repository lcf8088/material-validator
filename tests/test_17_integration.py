"""
Test 17: Integration tests - End-to-end workflows using real test data.
"""

import json
import pytest
from pathlib import Path
from lib.spec_loader import SpecLoader
from lib.validator import SpecValidator, format_validation_report
from lib.matcher import SpecMatcher
from lib.sanity import run_all_sanity_checks, format_sanity_report
from lib.extractor import normalize_extracted_data
from lib.history import ValidationHistory


class TestFullValidationWorkflow4140:
    """Full workflow: load MTR -> auto-detect spec -> validate -> history."""

    def test_4140_full_workflow(self, mtr_4140, specs_dir, tmp_path):
        # 1. Normalize data
        normalized = normalize_extracted_data(mtr_4140)
        assert normalized["heat_number"] == "D2213660"
        assert "C" in normalized["chemistry"]

        # 2. Auto-detect spec
        matcher = SpecMatcher(specs_dir)
        match = matcher.select_best_spec(normalized)
        assert match is not None
        spec_id, confidence, reason = match
        assert spec_id == "ES-M0001G"  # Should match the 110 MYS spec
        assert confidence > 0.5

        # 3. Validate
        validator = SpecValidator(specs_dir)
        result = validator.validate(normalized, spec_id)
        assert result.overall_status in ("PASS", "FAIL", "INCOMPLETE")
        assert result.heat_number == "D2213660"
        assert len(result.chemistry_results) > 0
        assert len(result.mechanical_results) > 0

        # 4. Sanity checks
        loader = SpecLoader.get_instance(specs_dir)
        spec = loader.get(spec_id)
        sanity = run_all_sanity_checks(normalized, spec)
        assert isinstance(sanity, dict)

        # 5. Record to history
        history = ValidationHistory(str(tmp_path / "history"))
        vid = history.record(result, normalized, spec, "test.pdf")
        assert vid is not None

        # 6. Retrieve from history
        record = history.get(vid)
        assert record["heat_number"] == "D2213660"
        assert record["spec_id"] == "ES-M0001G"

        # 7. Format report
        report = format_validation_report(result, use_color=False)
        assert "D2213660" in report
        assert "CHEMISTRY" in report


class TestFullValidationWorkflow303:
    """Full workflow for 303 SS."""

    def test_303_full_workflow(self, mtr_303, specs_dir, tmp_path):
        normalized = normalize_extracted_data(mtr_303)
        assert normalized["heat_number"] == "Y75T"

        matcher = SpecMatcher(specs_dir)
        match = matcher.select_best_spec(normalized)
        assert match is not None
        spec_id, _, _ = match
        assert "ES-M0003" in spec_id

        validator = SpecValidator(specs_dir)
        result = validator.validate(normalized, spec_id)
        assert result.overall_status in ("PASS", "FAIL", "INCOMPLETE")


class TestCrossSpecValidation:
    """Verify that wrong spec assignments correctly fail."""

    def test_4140_against_303_spec(self, mtr_4140, specs_dir):
        """4140 steel validated against 303 SS spec should fail/incomplete."""
        validator = SpecValidator(specs_dir)
        result = validator.validate(mtr_4140, "ES-M0003A")
        # Chemistry will totally mismatch (Cr range, etc.)
        assert result.overall_status in ("FAIL", "INCOMPLETE")

    def test_303_against_4140_spec(self, mtr_303, specs_dir):
        """303 SS validated against 4140 spec should fail/incomplete."""
        validator = SpecValidator(specs_dir)
        result = validator.validate(mtr_303, "ES-M0001C")
        assert result.overall_status in ("FAIL", "INCOMPLETE")


class TestSanityOnRealData:
    def test_4140_sanity_clean(self, mtr_4140):
        """Real 4140 data should have no extraction errors."""
        results = run_all_sanity_checks(mtr_4140)
        # Should have zero hard errors (values are real)
        assert len(results["errors"]) == 0

    def test_303_sanity_clean(self, mtr_303):
        results = run_all_sanity_checks(mtr_303)
        assert len(results["errors"]) == 0


class TestEdgeCases:
    def test_empty_mtr_data(self, specs_dir):
        validator = SpecValidator(specs_dir)
        result = validator.validate({}, "ES-M0001C")
        # Should handle gracefully - everything MISSING
        assert result.overall_status in ("INCOMPLETE", "UNKNOWN")

    def test_minimal_mtr_data(self, specs_dir):
        data = {"heat_number": "X", "material_grade": "4140"}
        validator = SpecValidator(specs_dir)
        result = validator.validate(data, "ES-M0001C")
        assert result.overall_status == "INCOMPLETE"
        assert result.missing_count > 0

    def test_extra_chemistry_elements_ignored(self, specs_dir):
        """MTR may have elements not in the spec - should not cause errors."""
        data = {
            "heat_number": "X",
            "material_grade": "4140",
            "chemistry": {
                "C": 0.42, "Cr": 1.08, "Mo": 0.25,
                "W": 0.01, "Co": 0.005, "Sn": 0.002,  # Extra elements
            },
        }
        validator = SpecValidator(specs_dir)
        result = validator.validate(data, "ES-M0001C")
        # Should not crash; extra elements just ignored
        assert result.heat_number == "X"

    def test_mechanical_with_mpa_units(self, specs_dir):
        """MTR data in MPa should be auto-converted to ksi during normalization."""
        data = {
            "heat_number": "X",
            "material_grade": "4140",
            "chemistry": {"C": 0.42, "Cr": 1.0, "Mo": 0.2},
            "mechanical": {
                "yield_strength": 827,  # ~120 ksi in MPa
                "yield_strength_unit": "MPa",
                "tensile_strength": 1034,  # ~150 ksi in MPa
                "tensile_strength_unit": "MPa",
            },
        }
        normalized = normalize_extracted_data(data)
        # MPa values converted to ksi (3-decimal precision preserves
        # psi-level accuracy for low-stress polymer specs).
        assert normalized["mechanical"]["yield_strength"] == pytest.approx(119.946, abs=0.01)
        assert normalized["mechanical"]["tensile_strength"] == pytest.approx(149.969, abs=0.01)
