"""
Test 12: PaddleOCR wrapper - Text extraction and line reconstruction.

Updated for PaddleOCR 3.x result format:
  result objects with rec_texts, rec_scores, dt_polys attributes.
"""

import pytest
from unittest.mock import patch, MagicMock
from lib.paddle_ocr import _extract_lines_from_result, extract_text, release_model


def _make_result(items):
    """
    Build a PaddleOCR 3.x-style result object from (text, score, poly) tuples.

    Args:
        items: list of (text, score, poly) where poly is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]

    Returns:
        A dict mimicking PaddleOCR 3.x result with rec_texts, rec_scores, dt_polys.
    """
    return {
        'rec_texts': [t for t, s, p in items],
        'rec_scores': [s for t, s, p in items],
        'dt_polys': [p for t, s, p in items],
    }


class TestExtractLinesFromResult:
    """Test the line reconstruction logic without needing PaddleOCR installed."""

    def test_single_line(self):
        result = _make_result([
            ("Hello World", 0.99, [[10, 10], [100, 10], [100, 30], [10, 30]]),
        ])
        lines = _extract_lines_from_result([result])
        assert len(lines) == 1
        assert "Hello World" in lines[0]

    def test_multiple_lines_sorted_vertically(self):
        result = _make_result([
            ("Line 2", 0.95, [[10, 100], [200, 100], [200, 120], [10, 120]]),
            ("Line 1", 0.99, [[10, 10], [200, 10], [200, 30], [10, 30]]),
        ])
        lines = _extract_lines_from_result([result])
        assert len(lines) == 2
        assert "Line 1" in lines[0]
        assert "Line 2" in lines[1]

    def test_items_on_same_line_merged(self):
        """Items within 15px vertically should be on the same line."""
        result = _make_result([
            ("Heat:", 0.99, [[10, 10], [80, 10], [80, 30], [10, 30]]),
            ("D2213660", 0.99, [[100, 12], [200, 12], [200, 32], [100, 32]]),
        ])
        lines = _extract_lines_from_result([result])
        assert len(lines) == 1
        assert "Heat:" in lines[0]
        assert "D2213660" in lines[0]

    def test_items_sorted_left_to_right(self):
        """Items on the same line should be sorted by x position."""
        result = _make_result([
            ("World", 0.99, [[200, 10], [300, 10], [300, 30], [200, 30]]),
            ("Hello", 0.99, [[10, 10], [80, 10], [80, 30], [10, 30]]),
        ])
        lines = _extract_lines_from_result([result])
        assert lines[0].startswith("Hello")

    def test_empty_result(self):
        lines = _extract_lines_from_result([])
        assert lines == []

    def test_none_page(self):
        lines = _extract_lines_from_result([None])
        assert lines == []

    def test_multi_page_result(self):
        result1 = _make_result([
            ("Page 1 text", 0.99, [[10, 10], [100, 10], [100, 30], [10, 30]]),
        ])
        result2 = _make_result([
            ("Page 2 text", 0.99, [[10, 10], [100, 10], [100, 30], [10, 30]]),
        ])
        lines = _extract_lines_from_result([result1, result2])
        assert any("Page 1" in l for l in lines)
        assert any("Page 2" in l for l in lines)


class TestExtractTextMocked:
    """Test extract_text with mocked PaddleOCR."""

    @patch("lib.paddle_ocr._get_ocr")
    def test_extract_returns_text(self, mock_get_ocr, tmp_path):
        # Create a dummy image file
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake image")

        result = _make_result([
            ("Heat Number: D2213660", 0.99, [[10, 10], [200, 10], [200, 30], [10, 30]]),
            ("Grade: 4140", 0.95, [[10, 50], [200, 50], [200, 70], [10, 70]]),
        ])

        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [result]
        mock_get_ocr.return_value = mock_ocr

        text = extract_text([str(img_path)])
        assert "D2213660" in text
        assert "4140" in text

    @patch("lib.paddle_ocr._get_ocr")
    def test_missing_file_skipped(self, mock_get_ocr):
        mock_get_ocr.return_value = MagicMock()
        text = extract_text(["/nonexistent/image.png"])
        assert text.strip() == ""  # No content from missing file

    @patch("lib.paddle_ocr._get_ocr")
    def test_multi_page_headers(self, mock_get_ocr, tmp_path):
        p1 = tmp_path / "page1.png"
        p2 = tmp_path / "page2.png"
        p1.write_bytes(b"img1")
        p2.write_bytes(b"img2")

        result = _make_result([
            ("text", 0.99, [[10, 10], [100, 10], [100, 30], [10, 30]]),
        ])

        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [result]
        mock_get_ocr.return_value = mock_ocr

        text = extract_text([str(p1), str(p2)])
        assert "Page 1" in text
        assert "Page 2" in text


class TestReleaseModel:
    def test_release_does_not_crash(self):
        release_model()  # Should not raise
