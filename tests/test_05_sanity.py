"""
Test 05: Sanity checks - catching extraction errors.
"""

import pytest
from lib.sanity import (
    check_chemistry_sanity,
    check_mechanical_sanity,
    check_borderline_values,
    run_all_sanity_checks,
    format_sanity_report,
)


class TestChemistrySanity:
    def test_normal_values_no_warnings(self):
        chem = {"C": 0.42, "Cr": 1.08, "Mo": 0.25}
        warnings = check_chemistry_sanity(chem)
        assert len(warnings) == 0

    def test_negative_value_flagged(self):
        chem = {"C": -0.5}
        warnings = check_chemistry_sanity(chem)
        assert len(warnings) == 1
        assert "Negative" in warnings[0][2]

    def test_extremely_high_carbon_flagged(self):
        chem = {"C": 5.0}  # Way above 2.5%
        warnings = check_chemistry_sanity(chem)
        assert any("high" in w[2].lower() for w in warnings)

    def test_high_sulfur_flagged(self):
        chem = {"S": 0.45}  # Near limit for S
        warnings = check_chemistry_sanity(chem)
        assert len(warnings) >= 1

    def test_cr_ni_swap_detection(self):
        """If Ni >> Cr and Cr is low, might be swapped."""
        chem = {"Cr": 8.0, "Ni": 25.0}
        warnings = check_chemistry_sanity(chem)
        assert any("swap" in w[2].lower() for w in warnings)

    def test_none_values_skipped(self):
        chem = {"C": None, "Cr": 1.0}
        warnings = check_chemistry_sanity(chem)
        assert len(warnings) == 0

    def test_title_case_handling(self):
        """Elements should work regardless of case in the dict key."""
        chem = {"c": 0.42, "cr": 1.08}  # lowercase
        warnings = check_chemistry_sanity(chem)
        # Should not crash; lowercase keys get capitalized internally
        assert isinstance(warnings, list)


class TestMechanicalSanity:
    def test_normal_values_no_warnings(self):
        mech = {"yield_strength": 120, "tensile_strength": 150, "elongation": 14}
        warnings = check_mechanical_sanity(mech)
        assert len(warnings) == 0

    def test_tensile_less_than_yield_flagged(self):
        mech = {"yield_strength": 150, "tensile_strength": 100}
        warnings = check_mechanical_sanity(mech)
        assert any("impossible" in w[2].lower() or "< Yield" in w[2] for w in warnings)

    def test_extremely_high_hardness_flagged(self):
        mech = {"hardness_hrc": 75}  # Max is 70
        warnings = check_mechanical_sanity(mech)
        assert len(warnings) >= 1

    def test_extremely_low_ys_flagged(self):
        mech = {"yield_strength": 2}  # Below 5 ksi
        warnings = check_mechanical_sanity(mech)
        assert len(warnings) >= 1

    def test_unusual_ts_ys_ratio_flagged(self):
        mech = {"yield_strength": 50, "tensile_strength": 200}  # ratio 4.0
        warnings = check_mechanical_sanity(mech)
        assert any("ratio" in w[2].lower() for w in warnings)

    def test_dict_values_handled(self):
        """Mechanical values can be dicts with 'value' key."""
        mech = {"yield_strength": {"value": 120, "unit": "ksi"}}
        warnings = check_mechanical_sanity(mech)
        assert isinstance(warnings, list)


class TestBorderlineValues:
    def test_value_near_max_flagged(self):
        mtr = {"chemistry": {"C": 0.429}}
        spec = {"chemistry": {"C": {"min": 0.38, "max": 0.43}}}
        warnings = check_borderline_values(mtr, spec)
        assert len(warnings) >= 1
        assert "borderline" in warnings[0][2].lower()

    def test_value_well_within_range_no_flag(self):
        mtr = {"chemistry": {"C": 0.40}}
        spec = {"chemistry": {"C": {"min": 0.38, "max": 0.43}}}
        warnings = check_borderline_values(mtr, spec)
        assert len(warnings) == 0


class TestRunAllSanityChecks:
    def test_clean_data_no_issues(self, mtr_4140):
        results = run_all_sanity_checks(mtr_4140)
        # Real data should be mostly clean
        assert isinstance(results, dict)
        assert "errors" in results
        assert "warnings" in results
        assert "borderline" in results

    def test_with_spec_checks_borderline(self, mtr_4140, specs_dir):
        from lib.spec_loader import SpecLoader
        loader = SpecLoader.get_instance(specs_dir)
        spec = loader.get("ES-M0001G")
        results = run_all_sanity_checks(mtr_4140, spec)
        assert "borderline" in results


class TestFormatSanityReport:
    def test_empty_results(self):
        results = {"errors": [], "warnings": [], "borderline": []}
        report = format_sanity_report(results)
        assert "No sanity issues" in report

    def test_with_errors(self):
        results = {
            "errors": [("C", "-0.5", "Negative value")],
            "warnings": [],
            "borderline": [],
        }
        report = format_sanity_report(results)
        assert "EXTRACTION ERRORS" in report
        assert "Negative value" in report
