"""
Test 10: Image export - filename generation, sanitization, and input parsing.
"""

import re
import pytest
from gui.image_export import (
    sanitize_filename, generate_archive_filename,
    generate_assembly_archive_filename, parse_input_filename,
)


class TestSanitizeFilename:
    def test_normal_string_unchanged(self):
        assert sanitize_filename("D2213660") == "D2213660"

    def test_special_chars_replaced(self):
        result = sanitize_filename('Heat:123/456\\789')
        assert ":" not in result
        assert "/" not in result
        assert "\\" not in result

    def test_question_mark_replaced(self):
        result = sanitize_filename("heat?num")
        assert "?" not in result

    def test_leading_trailing_dots_stripped(self):
        result = sanitize_filename("..heat..")
        assert not result.startswith(".")
        assert not result.endswith(".")

    def test_multiple_underscores_collapsed(self):
        result = sanitize_filename("A___B___C")
        assert "___" not in result
        assert result == "A_B_C"

    def test_empty_string(self):
        result = sanitize_filename("")
        assert isinstance(result, str)


class TestGenerateArchiveFilename:
    """Tests for YYYY.MM.PO#.LN#.ID.jpg naming scheme."""

    def test_full_metal(self):
        result = generate_archive_filename("000254", "01", "D2213660")
        # Pattern: YYYY.MM.000254.001.D2213660.jpg (base; page suffix appended by caller)
        assert result.endswith(".000254.001.D2213660.jpg")
        assert re.match(r"\d{4}\.\d{2}\.", result)

    def test_assembly_no_identifier(self):
        result = generate_archive_filename("000254", "03")
        assert result.endswith(".000254.003.jpg")
        # No extra dot before .jpg
        assert not result.endswith("..jpg")


    def test_none_identifier_omitted(self):
        result = generate_archive_filename("PO123", "05", None)
        assert result.endswith(".000123.005.jpg")

    def test_empty_po(self):
        result = generate_archive_filename("", "01", "HEAT1")
        assert "UNKNOWN" in result

    def test_none_po(self):
        result = generate_archive_filename(None, "01", "HEAT1")
        assert "UNKNOWN" in result

    def test_none_line_item_defaults(self):
        result = generate_archive_filename("PO1", None, "HEAT1")
        assert ".000." in result

    def test_custom_extension(self):
        result = generate_archive_filename("PO1", "01", "H1", extension=".pdf")
        assert result.endswith(".pdf")

    def test_special_chars_sanitized(self):
        result = generate_archive_filename("PO/1:2", "L?3", "H*4")
        assert "/" not in result
        assert ":" not in result
        assert "?" not in result
        assert "*" not in result

    def test_numeric_po_zero_padded_to_6(self):
        result = generate_archive_filename("254", "01", "HEAT1")
        assert ".000254." in result

    def test_long_numeric_po_not_truncated(self):
        result = generate_archive_filename("1234567", "01", "HEAT1")
        assert ".1234567." in result

    def test_alpha_prefix_stripped_and_padded(self):
        result = generate_archive_filename("PO-254", "01", "HEAT1")
        assert ".000254." in result


class TestGenerateAssemblyArchiveFilename:
    def test_assembly_naming(self):
        result = generate_assembly_archive_filename("000254", "03")
        assert result.endswith(".000254.003.jpg")

    def test_assembly_custom_extension(self):
        result = generate_assembly_archive_filename("PO1", "01", extension=".pdf")
        assert result.endswith(".000001.001.pdf")


class TestParseInputFilename:
    def test_metal_three_segments(self):
        result = parse_input_filename("000254.01.A1B2C3.pdf")
        assert result == {
            'po_number': '000254',
            'line_item': '01',
            'identifier': 'A1B2C3',
        }

    def test_assembly_two_segments(self):
        result = parse_input_filename("000254.03.pdf")
        assert result == {
            'po_number': '000254',
            'line_item': '03',
            'identifier': None,
        }

    def test_single_segment(self):
        result = parse_input_filename("document.pdf")
        assert result == {
            'po_number': 'document',
            'line_item': None,
            'identifier': None,
        }

    def test_extra_dots_in_identifier(self):
        result = parse_input_filename("000254.01.HEAT.123.pdf")
        assert result['po_number'] == '000254'
        assert result['line_item'] == '01'
        assert result['identifier'] == 'HEAT.123'

    def test_no_real_extension(self):
        # Path treats ".HEAT1" as extension, so stem is "000254.01"
        result = parse_input_filename("000254.01.HEAT1")
        assert result['po_number'] == '000254'
        assert result['line_item'] == '01'
        # .HEAT1 is consumed as extension by Path.stem — identifier lost
        assert result['identifier'] is None

    def test_empty_filename(self):
        result = parse_input_filename("")
        assert result['po_number'] is None
        assert result['line_item'] is None
        assert result['identifier'] is None

    def test_full_path(self):
        result = parse_input_filename("C:/folder/000254.01.ABC.pdf")
        assert result['po_number'] == '000254'
        assert result['line_item'] == '01'
        assert result['identifier'] == 'ABC'
