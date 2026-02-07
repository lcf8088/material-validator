"""
Test 10: TIFF export - filename generation and sanitization.
"""

import pytest
from gui.tiff_export import sanitize_filename, generate_archive_filename


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
    def test_heat_and_po(self):
        result = generate_archive_filename("D2213660", "PO-12345")
        assert result == "D2213660-PO-12345.tiff"

    def test_heat_only(self):
        result = generate_archive_filename("Y75T")
        assert result == "Y75T.tiff"

    def test_heat_none_po(self):
        result = generate_archive_filename("Y75T", None)
        assert result == "Y75T.tiff"

    def test_empty_heat(self):
        result = generate_archive_filename("")
        assert "UNKNOWN" in result

    def test_none_heat(self):
        result = generate_archive_filename(None)
        assert "UNKNOWN" in result

    def test_custom_extension(self):
        result = generate_archive_filename("H1", "P1", extension=".pdf")
        assert result.endswith(".pdf")

    def test_special_chars_in_heat(self):
        result = generate_archive_filename("H/1:2", "PO?3")
        assert "/" not in result
        assert ":" not in result
        assert "?" not in result
