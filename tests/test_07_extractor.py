"""
Test 07: Extractor - PDF conversion and data normalization.
"""

import json
import pytest
from lib.extractor import parse_extraction_response, normalize_extracted_data, pdf_to_images


class TestParseExtractionResponse:
    def test_clean_json(self):
        raw = '{"heat_number": "ABC123", "chemistry": {"C": 0.42}}'
        result = parse_extraction_response(raw)
        assert result["heat_number"] == "ABC123"
        assert result["_extraction_status"] == "success"

    def test_json_in_code_block(self):
        raw = '```json\n{"heat_number": "ABC123"}\n```'
        result = parse_extraction_response(raw)
        assert result["heat_number"] == "ABC123"

    def test_json_in_generic_code_block(self):
        raw = '```\n{"heat_number": "ABC123"}\n```'
        result = parse_extraction_response(raw)
        assert result["heat_number"] == "ABC123"

    def test_json_with_surrounding_text(self):
        raw = 'Here is the data:\n{"heat_number": "ABC123"}\nEnd of data.'
        result = parse_extraction_response(raw)
        assert result["heat_number"] == "ABC123"

    def test_invalid_json_returns_error(self):
        raw = "This is not JSON at all"
        result = parse_extraction_response(raw)
        assert result["_extraction_status"] == "error"
        assert "_error" in result

    def test_empty_string_returns_error(self):
        result = parse_extraction_response("")
        assert result["_extraction_status"] == "error"

    def test_truncated_json(self):
        raw = '{"heat_number": "ABC'  # Truncated
        result = parse_extraction_response(raw)
        assert result["_extraction_status"] == "error"


class TestNormalizeExtractedData:
    def test_basic_normalization(self):
        data = {
            "heat_number": "H123",
            "material_grade": "4140",
            "chemistry": {"C": 0.42, "cr": 1.08},
            "mechanical": {"yield_strength": 120},
        }
        norm = normalize_extracted_data(data)
        assert norm["heat_number"] == "H123"
        # Chemistry keys should be title case
        assert "Cr" in norm["chemistry"]
        assert "cr" not in norm["chemistry"]
        assert norm["chemistry"]["C"] == 0.42

    def test_element_case_normalization(self):
        """All element keys should be title-cased."""
        data = {
            "chemistry": {"c": 0.42, "CR": 1.08, "mo": 0.25, "NI": 0.18}
        }
        norm = normalize_extracted_data(data)
        for key in norm["chemistry"]:
            assert key == key.capitalize(), f"Key '{key}' not title case"

    def test_mechanical_unit_handling(self):
        data = {
            "mechanical": {
                "yield_strength": 120,
                "yield_strength_unit": "ksi",
                "tensile_strength": 150,
            }
        }
        norm = normalize_extracted_data(data)
        assert norm["mechanical"]["yield_strength"] == 120
        assert norm["mechanical"]["tensile_strength"] == 150

    def test_mpa_unit_preserved(self):
        data = {
            "mechanical": {
                "yield_strength": 827,
                "yield_strength_unit": "MPa",
            }
        }
        norm = normalize_extracted_data(data)
        assert norm["mechanical"].get("yield_strength_unit") == "MPa"

    def test_special_fields_preserved(self):
        data = {
            "charpy_impact": {"avg": 45, "temperature": -20},
            "temper_temperature": 1166,
            "nace_compliant": True,
            "grain_size": "7-8",
        }
        norm = normalize_extracted_data(data)
        assert norm["charpy_impact"]["avg"] == 45
        assert norm["temper_temperature"] == 1166
        assert norm["nace_compliant"] is True
        assert norm["grain_size"] == "7-8"

    def test_null_fields_excluded(self):
        data = {
            "heat_number": "H1",
            "uns": None,
            "supplier": None,
            "chemistry": {},
        }
        norm = normalize_extracted_data(data)
        assert "uns" not in norm
        assert "supplier" not in norm

    def test_empty_data(self):
        norm = normalize_extracted_data({})
        assert isinstance(norm, dict)

    def test_dict_mechanical_value(self):
        """Yield strength can come as {"value": 120, "unit": "ksi"}."""
        data = {
            "mechanical": {
                "yield_strength": {"value": 120, "unit": "ksi"},
            }
        }
        norm = normalize_extracted_data(data)
        assert norm["mechanical"]["yield_strength"] == 120


class TestPdfToImages:
    def test_nonexistent_pdf_raises(self):
        with pytest.raises(FileNotFoundError):
            pdf_to_images("/nonexistent/file.pdf")

    def test_non_pdf_raises_or_handles(self, tmp_path):
        """Passing a non-PDF file should raise an error."""
        fake = tmp_path / "fake.pdf"
        fake.write_text("not a pdf")
        with pytest.raises(Exception):
            pdf_to_images(str(fake))
