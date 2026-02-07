"""
Test 03: SpecValidator - Core validation engine.
"""

import pytest
from lib.validator import SpecValidator, ValidationResult, CertValidation, format_validation_report


class TestValidationResult:
    def test_pass_status(self):
        vr = ValidationResult(property_name="C", status="PASS")
        assert vr.is_pass()
        assert not vr.is_fail()

    def test_fail_status(self):
        vr = ValidationResult(property_name="C", status="FAIL")
        assert vr.is_fail()
        assert not vr.is_pass()

    def test_missing_status(self):
        vr = ValidationResult(property_name="C", status="MISSING")
        assert not vr.is_pass()
        assert not vr.is_fail()


class TestCertValidation:
    def test_all_results_combines_lists(self):
        cv = CertValidation(
            spec_id="X", heat_number="H1", material_grade="G1",
            chemistry_results=[ValidationResult("C", status="PASS")],
            mechanical_results=[ValidationResult("ys", status="FAIL")],
            special_results=[ValidationResult("nace", status="MISSING")],
        )
        assert len(cv.all_results) == 3

    def test_pass_count(self):
        cv = CertValidation(
            spec_id="X", heat_number="H1", material_grade="G1",
            chemistry_results=[
                ValidationResult("C", status="PASS"),
                ValidationResult("Cr", status="PASS"),
                ValidationResult("Mo", status="FAIL"),
            ],
        )
        assert cv.pass_count == 2
        assert cv.fail_count == 1
        assert cv.missing_count == 0

    def test_to_dict(self):
        cv = CertValidation(spec_id="X", heat_number="H1", material_grade="G1")
        d = cv.to_dict()
        assert d["spec_id"] == "X"
        assert d["heat_number"] == "H1"
        assert isinstance(d["chemistry"], list)


class TestCheckRange:
    def test_within_range_passes(self):
        vr = ValidationResult("C", spec_min=0.38, spec_max=0.43)
        SpecValidator._check_range(vr, 0.40)
        assert vr.status == "PASS"
        assert vr.actual_value == 0.40

    def test_below_min_fails(self):
        vr = ValidationResult("C", spec_min=0.38, spec_max=0.43)
        SpecValidator._check_range(vr, 0.35)
        assert vr.status == "FAIL"
        assert "Below minimum" in vr.note

    def test_above_max_fails(self):
        vr = ValidationResult("C", spec_min=0.38, spec_max=0.43)
        SpecValidator._check_range(vr, 0.50)
        assert vr.status == "FAIL"
        assert "Above maximum" in vr.note

    def test_at_exact_min_passes(self):
        vr = ValidationResult("C", spec_min=0.38, spec_max=0.43)
        SpecValidator._check_range(vr, 0.38)
        assert vr.status == "PASS"

    def test_at_exact_max_passes(self):
        vr = ValidationResult("C", spec_min=0.38, spec_max=0.43)
        SpecValidator._check_range(vr, 0.43)
        assert vr.status == "PASS"

    def test_none_min_ignores_lower(self):
        vr = ValidationResult("C", spec_min=None, spec_max=0.43)
        SpecValidator._check_range(vr, 0.001)
        assert vr.status == "PASS"

    def test_none_max_ignores_upper(self):
        vr = ValidationResult("C", spec_min=0.38, spec_max=None)
        SpecValidator._check_range(vr, 999.0)
        assert vr.status == "PASS"


class TestValidate4140:
    """Validate the 4140 test MTR against ES-M0001C and ES-M0001G."""

    def test_validate_4140_vs_es_m0001g(self, mtr_4140, specs_dir):
        v = SpecValidator(specs_dir)
        result = v.validate(mtr_4140, "ES-M0001G")
        assert result.overall_status in ("PASS", "FAIL", "INCOMPLETE")
        assert result.heat_number == "D2213660"
        assert result.spec_id == "ES-M0001G"
        assert len(result.chemistry_results) > 0
        assert len(result.mechanical_results) > 0

    def test_validate_4140_vs_es_m0001c(self, mtr_4140, specs_dir):
        v = SpecValidator(specs_dir)
        result = v.validate(mtr_4140, "ES-M0001C")
        assert result.overall_status in ("PASS", "FAIL", "INCOMPLETE")
        # C should be within range (0.38-0.43, actual 0.42)
        c_result = next(r for r in result.chemistry_results if r.property_name == "C")
        assert c_result.status == "PASS"

    def test_missing_spec_returns_error(self, mtr_4140, specs_dir):
        v = SpecValidator(specs_dir)
        result = v.validate(mtr_4140, "NONEXISTENT")
        assert result.overall_status == "ERROR"
        assert len(result.errors) > 0


class TestValidate303:
    """Validate the 303 SS test MTR against ES-M0003A."""

    def test_validate_303_vs_es_m0003a(self, mtr_303, specs_dir):
        v = SpecValidator(specs_dir)
        result = v.validate(mtr_303, "ES-M0003A")
        assert result.overall_status in ("PASS", "FAIL", "INCOMPLETE")
        assert result.heat_number == "Y75T"

    def test_wrong_spec_should_fail(self, mtr_303, specs_dir):
        """303 SS validated against a 4140 spec should fail or be incomplete."""
        v = SpecValidator(specs_dir)
        result = v.validate(mtr_303, "ES-M0001C")
        # 303 SS won't meet 4140 chemistry (C too low, no Mo match, etc.)
        assert result.overall_status in ("FAIL", "INCOMPLETE")


class TestFormatReport:
    def test_format_with_color(self, mtr_4140, specs_dir):
        v = SpecValidator(specs_dir)
        result = v.validate(mtr_4140, "ES-M0001C")
        report = format_validation_report(result, use_color=True)
        assert "MATERIAL CERT VALIDATION REPORT" in report
        assert "D2213660" in report

    def test_format_without_color(self, mtr_4140, specs_dir):
        v = SpecValidator(specs_dir)
        result = v.validate(mtr_4140, "ES-M0001C")
        report = format_validation_report(result, use_color=False)
        assert "\033[" not in report  # No ANSI codes
        assert "CHEMISTRY" in report
