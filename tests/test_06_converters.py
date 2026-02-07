"""
Test 06: Converters - Unit and hardness conversions.
"""

import pytest
from lib.converters import convert_stress, normalize_hardness, hrc_to_hbw, hbw_to_hrc


class TestStressConversion:
    def test_ksi_to_mpa(self):
        result = convert_stress(100, "ksi", "mpa")
        assert 689 < result < 690  # 100 ksi ~ 689.5 MPa

    def test_mpa_to_ksi(self):
        result = convert_stress(689.5, "mpa", "ksi")
        assert 99.9 < result < 100.1

    def test_same_unit_no_change(self):
        result = convert_stress(100, "ksi", "ksi")
        assert result == 100

    def test_case_insensitive(self):
        result = convert_stress(100, "KSI", "MPa")
        assert result > 600


class TestHardnessConversion:
    def test_hrc_to_hbw(self):
        result = hrc_to_hbw(30)
        assert result is not None
        assert 280 < result < 310  # ~293 HBW for 30 HRc

    def test_hbw_to_hrc(self):
        result = hbw_to_hrc(293)
        assert result is not None
        assert 28 < result < 32

    def test_normalize_hardness_from_hrc(self):
        result = normalize_hardness(30, "HRC")
        assert "hrc" in result
        assert "hbw" in result
        assert result["hrc"] == 30
        assert result["hbw"] is not None

    def test_normalize_hardness_from_hbw(self):
        result = normalize_hardness(200, "HBW")
        assert "hrc" in result
        assert "hbw" in result
        assert result["hbw"] == 200

    def test_extreme_hrc_value(self):
        """Very low HRc may not have a conversion."""
        result = hrc_to_hbw(5)
        # Should return None or a value, not crash
        assert result is None or isinstance(result, (int, float))
