"""
Main OCR pipeline orchestrator.

Ties together: preprocessor -> PaddleOCR -> Claude parser -> validation -> TIFF -> staging.
Single entry point for processing MTR documents end-to-end.
"""

import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .extractor import pdf_to_images, normalize_extracted_data
from .preprocessor import extract_native_text, is_digital_native, preprocess_images, fix_rotated_pages
from .paddle_ocr import extract_text as ocr_extract_text
from .claude_parser import parse_and_validate
from .matcher import SpecMatcher
from .validator import SpecValidator, CertValidation
from .sanity import run_all_sanity_checks
from .spec_loader import SpecLoader

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result from a full pipeline run."""
    success: bool = False
    source_file: str = ""
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    normalized_data: Dict[str, Any] = field(default_factory=dict)
    spec_id: Optional[str] = None
    spec_match_confidence: float = 0.0
    validation: Optional[CertValidation] = None
    sanity: Dict[str, List] = field(default_factory=dict)
    compliance_flags: List[Dict[str, Any]] = field(default_factory=list)
    output_tiff_path: Optional[str] = None
    archive_filename: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def overall_status(self) -> str:
        if not self.success:
            return "ERROR"
        if self.validation:
            return self.validation.overall_status
        return "UNKNOWN"


def _haiku_mtr_check(text: str, api_key: str) -> bool:
    """Ask Haiku if text contains readable MTR data. ~2s, ~$0.001."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        snippet = text[:2000]
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content":
                f"Does this text contain readable Material Test Report (MTR) data "
                f"with identifiable values like heat numbers, chemistry, or "
                f"mechanical properties? Reply ONLY: YES or NO\n\n{snippet}"}],
        )
        answer = resp.content[0].text.strip().upper()
        return answer.startswith("YES")
    except Exception as e:
        logger.warning("Haiku MTR check failed (%s), assuming text is OK", e)
        return True


def _text_quality_ok(text: str, api_key: str, page_texts: Optional[List[str]] = None) -> bool:
    """Two-tier quality check: length pre-filter + page coverage + Haiku verification.

    If page_texts is provided (multi-page docs), checks that at least half
    the pages have meaningful content. This catches partially-scanned PDFs
    where page 1 has text but remaining pages are scanned images.
    """
    if len(text.strip()) < 200:
        return False
    # Page coverage check: if most pages are blank, direct text is incomplete
    if page_texts and len(page_texts) > 1:
        pages_with_text = sum(1 for p in page_texts if len(p.strip()) > 50)
        if pages_with_text < len(page_texts) / 2:
            logger.info("Page coverage too low: %d/%d pages have text",
                        pages_with_text, len(page_texts))
            return False
    return _haiku_mtr_check(text, api_key)


def pre_extract(
    pdf_path: str,
    api_key: str,
    paddle_model_path: Optional[str] = None,
    preprocessing_dpi: int = 300,
) -> tuple:
    """Phase A: Staged text extraction from a document.

    Tries stages in order: direct text -> OCR@200 -> OCR@300.
    Returns (ocr_text, image_paths, is_pdf, stage_used).
    """
    pdf_path_obj = Path(pdf_path)
    is_pdf = pdf_path_obj.suffix.lower() == '.pdf'

    # --- Stage 1: Direct text extraction (digital-native PDFs) ---
    direct_text = ""
    page_texts = []
    if is_pdf:
        direct_text, page_texts = extract_native_text(pdf_path, return_page_texts=True)
        if _text_quality_ok(direct_text, api_key, page_texts=page_texts):
            # Still need images for Claude vision — render at 200 DPI (cheaper)
            image_paths = pdf_to_images(pdf_path, dpi=200)
            image_paths = fix_rotated_pages(image_paths)
            logger.info("Stage 1 PASSED: direct text (%d chars)", len(direct_text))
            return direct_text, image_paths, is_pdf, "direct"
        logger.info("Stage 1 FAILED: direct text (%d chars), escalating to OCR@200",
                     len(direct_text))

    # Determine if PDF is scanned (very little embedded text)
    scanned = len(direct_text.strip()) < 50

    # --- Stage 2: PaddleOCR at 200 DPI ---
    if is_pdf:
        image_paths = pdf_to_images(pdf_path, dpi=200)
    else:
        image_paths = [pdf_path]

    image_paths = fix_rotated_pages(image_paths)

    if scanned:
        ocr_images = preprocess_images(image_paths)
    else:
        ocr_images = image_paths

    ocr_text = ocr_extract_text(ocr_images, model_path=paddle_model_path)
    if _text_quality_ok(ocr_text, api_key):
        logger.info("Stage 2 PASSED: OCR@200 (%d chars)", len(ocr_text))
        return ocr_text, image_paths, is_pdf, "ocr_200"
    logger.info("Stage 2 FAILED: OCR@200 (%d chars), escalating to OCR@300",
                 len(ocr_text))

    # --- Stage 3: PaddleOCR at 300 DPI (accept unconditionally) ---
    if is_pdf:
        image_paths = pdf_to_images(pdf_path, dpi=preprocessing_dpi)
        image_paths = fix_rotated_pages(image_paths)
        if scanned:
            ocr_images = preprocess_images(image_paths)
        else:
            ocr_images = image_paths
    else:
        ocr_images = image_paths

    ocr_text = ocr_extract_text(ocr_images, model_path=paddle_model_path)
    logger.info("Stage 3: OCR@300 (%d chars) — accepted", len(ocr_text))
    return ocr_text, image_paths, is_pdf, "ocr_300"


def process_document(
    pdf_path: str,
    output_dir: str = "",
    spec_id: Optional[str] = None,
    anthropic_api_key: str = "",
    paddle_model_path: Optional[str] = None,
    preprocessing_dpi: int = 300,
    tiff_dpi: int = 300,
    tiff_compression: str = "lzw",
    on_progress: Optional[callable] = None,
    po_number: Optional[str] = None,
    organize_by_po: bool = False,
    extraction_model: str = "sonnet",
    pre_extracted: Optional[tuple] = None,
) -> PipelineResult:
    """
    Process an MTR document through the full pipeline.

    Steps:
    1. Document type detection (digital vs scanned)
    2. PDF -> images at target DPI
    3. Preprocess if scanned
    4. PaddleOCR text extraction
    5. Claude structured parsing + optional spec validation
    6. Normalize extracted data
    7. Auto-detect spec if not provided
    8. Validate against spec
    9. Sanity checks
    10. PDF -> TIFF to staging directory (for user review before archive)

    History recording and final archiving are handled by the GUI approve step.

    Args:
        pdf_path: Path to the input PDF or image file.
        output_dir: Non-empty value triggers TIFF generation to staging.
        spec_id: Specification ID to validate against (None for auto-detect).
        anthropic_api_key: Anthropic API key for Claude parsing.
        paddle_model_path: Optional custom PaddleOCR model path.
        preprocessing_dpi: DPI for rendering PDF pages for OCR.
        tiff_dpi: DPI for TIFF archive output.
        tiff_compression: TIFF compression method.
        on_progress: Optional callback(step: str, pct: float) for progress.
        po_number: Explicit PO override (e.g. from GUI sticky field).
        organize_by_po: If True, create PO subfolder in output_dir.
        pre_extracted: Optional (ocr_text, image_paths, is_pdf, stage_used)
            from pre_extract(). If provided, skips Steps 1-4.

    Returns:
        PipelineResult with all outputs and status.
    """
    result = PipelineResult(source_file=pdf_path)

    def _progress(step: str, pct: float):
        logger.info("Pipeline [%.0f%%] %s", pct * 100, step)
        if on_progress:
            on_progress(step, pct)

    try:
        pdf_path_obj = Path(pdf_path)
        if not pdf_path_obj.exists():
            result.errors.append(f"File not found: {pdf_path}")
            return result

        # Steps 1-4: Text extraction (staged or pre-computed)
        if pre_extracted is not None:
            ocr_text, image_paths, is_pdf, stage_used = pre_extracted
            _progress(f"Using pre-extracted text ({stage_used})...", 0.30)
            logger.info("Using pre-extracted text (%s, %d chars)", stage_used, len(ocr_text))
        else:
            _progress("Extracting text (staged)...", 0.05)
            ocr_text, image_paths, is_pdf, stage_used = pre_extract(
                pdf_path,
                api_key=anthropic_api_key,
                paddle_model_path=paddle_model_path,
                preprocessing_dpi=preprocessing_dpi,
            )
            logger.info("Staged extraction complete (%s, %d chars)", stage_used, len(ocr_text))
            _progress("Text extraction complete.", 0.30)

        if not image_paths:
            result.errors.append("No pages/images extracted from document.")
            return result

        if not ocr_text.strip():
            result.errors.append("OCR extracted no text from document.")
            return result

        # Detect Vendor Spec mode (extract only, no validation)
        vendor_spec_mode = (spec_id == "Vendor Spec")

        # Step 5: Claude structured parsing
        _progress("Parsing with Claude...", 0.45)
        spec_loader = SpecLoader.get_instance()
        spec_data = None
        if spec_id and not vendor_spec_mode:
            spec_data = spec_loader.get(spec_id)

        raw_data = parse_and_validate(
            ocr_text=ocr_text,
            api_key=anthropic_api_key,
            spec=spec_data,
            spec_id=spec_id if not vendor_spec_mode else None,
            image_paths=image_paths,
            model=extraction_model,
        )

        if raw_data.get('_extraction_status') == 'error':
            result.errors.append(f"Claude parsing failed: {raw_data.get('_error', 'Unknown')}")
            result.extracted_data = raw_data
            return result

        result.extracted_data = raw_data
        result.compliance_flags = raw_data.pop('compliance_flags', [])

        # Step 6: Normalize extracted data
        _progress("Normalizing data...", 0.55)
        normalized = normalize_extracted_data(raw_data)

        result.normalized_data = normalized

        # Step 6b: Detect suspicious chemistry and retry with Opus if needed
        from .sanity import detect_suspicious_chemistry
        spec_chem = spec_data.get('chemistry') if spec_data else None
        if (extraction_model != 'opus'
                and not vendor_spec_mode
                and normalized.get('chemistry')
                and detect_suspicious_chemistry(normalized['chemistry'], spec_chem)):
            logger.warning("Suspicious chemistry detected — retrying with Opus...")
            _progress("Suspicious chemistry detected, retrying with Opus...", 0.50)
            raw_data_opus = parse_and_validate(
                ocr_text=ocr_text,
                api_key=anthropic_api_key,
                spec=spec_data,
                spec_id=spec_id if not vendor_spec_mode else None,
                image_paths=image_paths,
                model='opus',
            )
            if raw_data_opus.get('_extraction_status') != 'error':
                normalized_opus = normalize_extracted_data(raw_data_opus)
                if not detect_suspicious_chemistry(normalized_opus.get('chemistry', {}), spec_chem):
                    logger.info("Opus extraction resolved suspicious chemistry — using Opus result")
                    raw_data = raw_data_opus
                    normalized = normalized_opus
                    result.extracted_data = raw_data
                    result.compliance_flags = raw_data.pop('compliance_flags', [])
                    result.normalized_data = normalized
                else:
                    logger.warning("Opus extraction still shows suspicious chemistry — using original")

        if vendor_spec_mode:
            # Vendor Spec: skip auto-detect and validation, create review-only result
            _progress("Vendor Spec — skipping validation...", 0.70)
            result.spec_id = "Vendor Spec"
            result.spec_match_confidence = 1.0

            # Create a minimal CertValidation so the UI displays properly
            validation = CertValidation(
                spec_id="Vendor Spec",
                heat_number=normalized.get('heat_number') or normalized.get('batch_number') or 'N/A',
                material_grade=normalized.get('material_grade', 'N/A'),
                overall_status='VENDOR SPEC',
            )
            result.validation = validation
            logger.info("Vendor Spec mode — manual review required")
        else:
            # Step 7: Auto-detect spec if not provided
            if not spec_id:
                _progress("Auto-detecting spec...", 0.60)
                matcher = SpecMatcher()
                match = matcher.select_best_spec(normalized)
                if match:
                    spec_id, confidence, reason = match
                    result.spec_id = spec_id
                    result.spec_match_confidence = confidence
                    logger.info("Auto-detected spec: %s (%.0f%% - %s)", spec_id, confidence * 100, reason)
                else:
                    result.warnings.append("Could not auto-detect specification.")
            else:
                result.spec_id = spec_id
                result.spec_match_confidence = 1.0

            # Step 8: Validate against spec
            if result.spec_id:
                _progress("Validating against spec...", 0.70)
                validator = SpecValidator()
                validation = validator.validate(normalized, result.spec_id)
                result.validation = validation
                logger.info("Validation result: %s", validation.overall_status)

        # Step 9: Sanity checks
        _progress("Running sanity checks...", 0.75)
        spec_for_sanity = spec_loader.get(result.spec_id) if result.spec_id and not vendor_spec_mode else None
        sanity = run_all_sanity_checks(normalized, spec_for_sanity)
        result.sanity = sanity

        for category in ('errors', 'warnings'):
            for item in sanity.get(category, []):
                result.warnings.append(f"Sanity {category}: {item[0]} = {item[1]} - {item[2]}")

        # Step 10: PDF -> TIFF (staging — user approves before archiving)
        if output_dir and is_pdf:
            _progress("Converting to TIFF (staging)...", 0.85)
            from gui.tiff_export import pdf_to_tiff

            staging_dir = Path(tempfile.gettempdir()) / 'material-validator-staging'
            staging_dir.mkdir(parents=True, exist_ok=True)

            heat_number = normalized.get('heat_number') or normalized.get('batch_number') or 'UNKNOWN'
            staging_name = f"staging_{heat_number}_{int(time.time())}.tiff"
            staging_path = str(staging_dir / staging_name)

            success, msg = pdf_to_tiff(pdf_path, staging_path, tiff_dpi, tiff_compression)
            if success:
                result.output_tiff_path = staging_path
                logger.info("Staging TIFF saved: %s", staging_path)
            else:
                result.warnings.append(f"TIFF conversion failed: {msg}")

        result.success = True
        _progress("Complete.", 1.0)

    except Exception as e:
        logger.exception("Pipeline error: %s", e)
        result.errors.append(str(e))

    return result


