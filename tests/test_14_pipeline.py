"""
Test 14: Pipeline - End-to-end orchestration with mocked dependencies.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from lib.pipeline import process_document, PipelineResult


class TestPipelineResult:
    def test_default_result(self):
        r = PipelineResult()
        assert r.success is False
        assert r.overall_status == "ERROR"

    def test_success_with_validation(self):
        from lib.validator import CertValidation
        r = PipelineResult(
            success=True,
            validation=CertValidation(
                spec_id="X", heat_number="H", material_grade="G",
                overall_status="PASS",
            ),
        )
        assert r.overall_status == "PASS"

    def test_success_without_validation(self):
        r = PipelineResult(success=True)
        assert r.overall_status == "UNKNOWN"


class TestProcessDocumentFileErrors:
    def test_nonexistent_file(self):
        result = process_document(
            "/nonexistent/file.pdf",
            anthropic_api_key="test",
        )
        assert not result.success
        assert any("not found" in e.lower() for e in result.errors)

    def test_empty_pdf(self, tmp_path):
        """Empty/corrupt PDF should error gracefully."""
        pdf = tmp_path / "empty.pdf"
        pdf.write_text("not a pdf")
        result = process_document(
            str(pdf),
            anthropic_api_key="test",
        )
        assert not result.success
        assert len(result.errors) > 0


class TestProcessDocumentMocked:
    """Full pipeline test with all external deps mocked."""

    @patch("lib.pipeline.ocr_extract_text")
    @patch("lib.pipeline.parse_and_validate")
    @patch("lib.pipeline.is_digital_native")
    @patch("lib.pipeline.pdf_to_images")
    def test_full_pipeline_digital_pdf(
        self, mock_pdf2img, mock_is_digital, mock_claude, mock_ocr, tmp_path
    ):
        # Create a dummy PDF
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Test MTR Content")
        pdf_path = str(tmp_path / "test.pdf")
        doc.save(pdf_path)
        doc.close()

        # Mock responses
        mock_is_digital.return_value = True
        mock_pdf2img.return_value = [str(tmp_path / "page1.png")]
        # Create the fake image so OCR doesn't skip it
        (tmp_path / "page1.png").write_bytes(b"fake")

        mock_ocr.return_value = "Heat Number: D2213660\nGrade: 4140\nC: 0.42 Cr: 1.08"
        mock_claude.return_value = {
            "_extraction_status": "success",
            "heat_number": "D2213660",
            "material_grade": "4140",
            "uns": "G41400",
            "chemistry": {"C": 0.42, "Cr": 1.08, "Mo": 0.25},
            "mechanical": {"yield_strength": 120, "tensile_strength": 150},
        }

        result = process_document(
            pdf_path,
            anthropic_api_key="test-key",
        )

        assert result.success
        assert result.normalized_data["heat_number"] == "D2213660"
        assert result.spec_id is not None  # Should auto-detect
        assert result.validation is not None

    @patch("lib.pipeline.ocr_extract_text")
    @patch("lib.pipeline.parse_and_validate")
    @patch("lib.pipeline.is_digital_native")
    @patch("lib.pipeline.pdf_to_images")
    def test_pipeline_with_explicit_spec(
        self, mock_pdf2img, mock_is_digital, mock_claude, mock_ocr, tmp_path
    ):
        import fitz
        doc = fitz.open()
        doc.new_page()
        pdf_path = str(tmp_path / "test.pdf")
        doc.save(pdf_path)
        doc.close()

        mock_is_digital.return_value = True
        mock_pdf2img.return_value = [str(tmp_path / "p.png")]
        (tmp_path / "p.png").write_bytes(b"fake")
        mock_ocr.return_value = "Some OCR text"
        mock_claude.return_value = {
            "_extraction_status": "success",
            "heat_number": "H1",
            "material_grade": "4140",
            "chemistry": {"C": 0.42},
            "mechanical": {"yield_strength": 90},
        }

        result = process_document(
            pdf_path,
            spec_id="ES-M0001C",
            anthropic_api_key="test-key",
        )

        assert result.success
        assert result.spec_id == "ES-M0001C"

    @patch("lib.pipeline.ocr_extract_text")
    @patch("lib.pipeline.parse_and_validate")
    @patch("lib.pipeline.is_digital_native")
    @patch("lib.pipeline.pdf_to_images")
    def test_pipeline_claude_error(
        self, mock_pdf2img, mock_is_digital, mock_claude, mock_ocr, tmp_path
    ):
        import fitz
        doc = fitz.open()
        doc.new_page()
        pdf_path = str(tmp_path / "test.pdf")
        doc.save(pdf_path)
        doc.close()

        mock_is_digital.return_value = True
        mock_pdf2img.return_value = [str(tmp_path / "p.png")]
        (tmp_path / "p.png").write_bytes(b"fake")
        mock_ocr.return_value = "Some text"
        mock_claude.return_value = {
            "_extraction_status": "error",
            "_error": "API rate limit exceeded",
        }

        result = process_document(pdf_path, anthropic_api_key="test-key")
        assert not result.success
        assert any("rate limit" in e.lower() for e in result.errors)

    @patch("lib.pipeline.ocr_extract_text")
    @patch("lib.pipeline.is_digital_native")
    @patch("lib.pipeline.pdf_to_images")
    def test_pipeline_empty_ocr(
        self, mock_pdf2img, mock_is_digital, mock_ocr, tmp_path
    ):
        import fitz
        doc = fitz.open()
        doc.new_page()
        pdf_path = str(tmp_path / "test.pdf")
        doc.save(pdf_path)
        doc.close()

        mock_is_digital.return_value = True
        mock_pdf2img.return_value = [str(tmp_path / "p.png")]
        (tmp_path / "p.png").write_bytes(b"fake")
        mock_ocr.return_value = ""

        result = process_document(pdf_path, anthropic_api_key="test-key")
        assert not result.success
        assert any("no text" in e.lower() for e in result.errors)

    @patch("lib.pipeline.ocr_extract_text")
    @patch("lib.pipeline.parse_and_validate")
    @patch("lib.pipeline.is_digital_native")
    @patch("lib.pipeline.pdf_to_images")
    @patch("gui.tiff_export.pdf_to_tiff")
    def test_pipeline_with_tiff_output(
        self, mock_tiff, mock_pdf2img, mock_is_digital, mock_claude, mock_ocr, tmp_path
    ):
        import fitz
        doc = fitz.open()
        doc.new_page()
        pdf_path = str(tmp_path / "test.pdf")
        doc.save(pdf_path)
        doc.close()

        mock_is_digital.return_value = True
        mock_pdf2img.return_value = [str(tmp_path / "p.png")]
        (tmp_path / "p.png").write_bytes(b"fake")
        mock_ocr.return_value = "Some text"
        mock_claude.return_value = {
            "_extraction_status": "success",
            "heat_number": "H1",
            "material_grade": "4140",
            "uns": "G41400",
            "chemistry": {"C": 0.42},
            "mechanical": {"yield_strength": 90},
        }
        mock_tiff.return_value = (True, "Saved 1 page")

        output_dir = str(tmp_path / "archive")
        result = process_document(
            pdf_path,
            output_dir=output_dir,
            anthropic_api_key="test-key",
        )
        assert result.success


class TestProgressCallback:
    @patch("lib.pipeline.ocr_extract_text")
    @patch("lib.pipeline.parse_and_validate")
    @patch("lib.pipeline.is_digital_native")
    @patch("lib.pipeline.pdf_to_images")
    def test_progress_callback_called(
        self, mock_pdf2img, mock_is_digital, mock_claude, mock_ocr, tmp_path
    ):
        import fitz
        doc = fitz.open()
        doc.new_page()
        pdf_path = str(tmp_path / "test.pdf")
        doc.save(pdf_path)
        doc.close()

        mock_is_digital.return_value = True
        mock_pdf2img.return_value = [str(tmp_path / "p.png")]
        (tmp_path / "p.png").write_bytes(b"fake")
        mock_ocr.return_value = "Heat: H1"
        mock_claude.return_value = {
            "_extraction_status": "success",
            "heat_number": "H1",
            "material_grade": "4140",
            "chemistry": {},
            "mechanical": {},
        }

        progress_calls = []
        def on_progress(step, pct):
            progress_calls.append((step, pct))

        process_document(pdf_path, anthropic_api_key="k", on_progress=on_progress)
        assert len(progress_calls) > 0
        # Last call should be Complete at 100%
        assert progress_calls[-1][1] == 1.0
