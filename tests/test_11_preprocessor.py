"""
Test 11: Preprocessor - Document type detection and image preprocessing.
"""

import pytest
from unittest.mock import patch, MagicMock
from lib.preprocessor import is_digital_native, preprocess_images


class TestIsDigitalNative:
    def test_digital_pdf_detected(self, tmp_path):
        """A PDF with substantial text should be detected as digital-native."""
        import fitz
        # Create a simple PDF with text
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "This is a material test report with lots of text content. " * 10)
        pdf_path = str(tmp_path / "digital.pdf")
        doc.save(pdf_path)
        doc.close()

        assert is_digital_native(pdf_path) is True

    def test_empty_pdf_detected_as_scanned(self, tmp_path):
        """A PDF with no extractable text should be detected as scanned."""
        import fitz
        doc = fitz.open()
        doc.new_page()  # Blank page
        pdf_path = str(tmp_path / "scanned.pdf")
        doc.save(pdf_path)
        doc.close()

        assert is_digital_native(pdf_path) is False

    def test_minimal_text_detected_as_scanned(self, tmp_path):
        """A PDF with very little text (< 50 chars) should be detected as scanned."""
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hi")
        pdf_path = str(tmp_path / "minimal.pdf")
        doc.save(pdf_path)
        doc.close()

        assert is_digital_native(pdf_path) is False


class TestPreprocessImages:
    @pytest.fixture
    def _skip_no_cv2(self):
        """Skip tests if OpenCV is not installed."""
        pytest.importorskip("cv2")

    @pytest.mark.usefixtures("_skip_no_cv2")
    def test_preprocess_creates_output_files(self, tmp_path):
        import cv2
        import numpy as np

        # Create a test image (white page with black text-like noise)
        img = np.ones((800, 600, 3), dtype=np.uint8) * 255
        cv2.putText(img, "TEST MTR", (100, 400), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
        input_path = str(tmp_path / "test_input.png")
        cv2.imwrite(input_path, img)

        output_dir = str(tmp_path / "preprocessed")
        results = preprocess_images([input_path], output_dir)

        assert len(results) == 1
        assert "preprocessed" in results[0]
        from pathlib import Path
        assert Path(results[0]).exists()

    @pytest.mark.usefixtures("_skip_no_cv2")
    def test_missing_image_passed_through(self, tmp_path):
        """If an image can't be read, it should be passed through unchanged."""
        results = preprocess_images(["/nonexistent/image.png"], str(tmp_path / "out"))
        assert len(results) == 1
        assert results[0] == "/nonexistent/image.png"

    @pytest.mark.usefixtures("_skip_no_cv2")
    def test_multiple_images(self, tmp_path):
        import cv2
        import numpy as np

        paths = []
        for i in range(3):
            img = np.ones((200, 200, 3), dtype=np.uint8) * 200
            p = str(tmp_path / f"page{i}.png")
            cv2.imwrite(p, img)
            paths.append(p)

        results = preprocess_images(paths, str(tmp_path / "out"))
        assert len(results) == 3
