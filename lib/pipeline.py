"""
Main OCR pipeline orchestrator.

Ties together: preprocessor -> PaddleOCR -> Claude parser -> validation -> TIFF -> rename.
Single entry point for processing MTR documents end-to-end.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .extractor import pdf_to_images, normalize_extracted_data
from .preprocessor import is_digital_native, preprocess_images
from .paddle_ocr import extract_text as ocr_extract_text
from .claude_parser import parse_and_validate
from .matcher import SpecMatcher
from .validator import SpecValidator, CertValidation
from .sanity import run_all_sanity_checks
from .spec_loader import SpecLoader
from .history import ValidationHistory

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
    10. PDF -> TIFF at archive DPI
    11. Rename with heat/PO convention
    12. Log to validation history

    Args:
        pdf_path: Path to the input PDF or image file.
        output_dir: Archive/output directory for TIFF files.
        spec_id: Specification ID to validate against (None for auto-detect).
        anthropic_api_key: Anthropic API key for Claude parsing.
        paddle_model_path: Optional custom PaddleOCR model path.
        preprocessing_dpi: DPI for rendering PDF pages for OCR.
        tiff_dpi: DPI for TIFF archive output.
        tiff_compression: TIFF compression method.
        on_progress: Optional callback(step: str, pct: float) for progress.
        po_number: Explicit PO override (e.g. from GUI sticky field).
        organize_by_po: If True, create PO subfolder in output_dir.

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

        # Step 1: Document type detection
        _progress("Detecting document type...", 0.05)
        is_pdf = pdf_path_obj.suffix.lower() == '.pdf'
        scanned = False
        if is_pdf:
            scanned = not is_digital_native(pdf_path)
            logger.info("Document type: %s", "scanned" if scanned else "digital-native")

        # Step 2: PDF -> images
        _progress("Converting to images...", 0.10)
        if is_pdf:
            image_paths = pdf_to_images(pdf_path, dpi=preprocessing_dpi)
        else:
            # Already an image
            image_paths = [pdf_path]

        if not image_paths:
            result.errors.append("No pages/images extracted from document.")
            return result

        # Step 3: Preprocess if scanned
        if scanned:
            _progress("Preprocessing scanned images...", 0.20)
            image_paths = preprocess_images(image_paths)

        # Step 4: PaddleOCR extraction
        _progress("Running OCR...", 0.30)
        ocr_text = ocr_extract_text(image_paths, model_path=paddle_model_path)

        if not ocr_text.strip():
            result.errors.append("OCR extracted no text from document.")
            return result

        logger.info("OCR extracted %d characters.", len(ocr_text))

        # Step 5: Claude structured parsing
        _progress("Parsing with Claude...", 0.45)
        spec_loader = SpecLoader.get_instance()
        spec_data = None
        if spec_id:
            spec_data = spec_loader.get(spec_id)

        raw_data = parse_and_validate(
            ocr_text=ocr_text,
            api_key=anthropic_api_key,
            spec=spec_data,
            spec_id=spec_id,
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
        spec_for_sanity = spec_loader.get(result.spec_id) if result.spec_id else None
        sanity = run_all_sanity_checks(normalized, spec_for_sanity)
        result.sanity = sanity

        for category in ('errors', 'warnings'):
            for item in sanity.get(category, []):
                result.warnings.append(f"Sanity {category}: {item[0]} = {item[1]} - {item[2]}")

        # Step 10: PDF -> TIFF
        if output_dir and is_pdf:
            _progress("Converting to TIFF...", 0.85)
            from gui.tiff_export import pdf_to_tiff, generate_archive_filename

            heat_number = normalized.get('heat_number') or normalized.get('batch_number') or 'UNKNOWN'
            effective_po = po_number or normalized.get('po_number')
            archive_name = generate_archive_filename(heat_number, effective_po)
            result.archive_filename = archive_name

            # Determine output directory (with optional PO subfolder)
            effective_output_dir = Path(output_dir)
            if organize_by_po and effective_po:
                from gui.tiff_export import sanitize_filename
                effective_output_dir = effective_output_dir / sanitize_filename(effective_po)
                effective_output_dir.mkdir(parents=True, exist_ok=True)

            tiff_path = str(effective_output_dir / archive_name)

            # Handle filename conflicts
            tiff_path_obj = Path(tiff_path)
            if tiff_path_obj.exists():
                base = tiff_path_obj.stem
                counter = 1
                while tiff_path_obj.exists():
                    tiff_path_obj = effective_output_dir / f"{base}_{counter}.tiff"
                    counter += 1
                tiff_path = str(tiff_path_obj)

            success, msg = pdf_to_tiff(pdf_path, tiff_path, tiff_dpi, tiff_compression)
            if success:
                result.output_tiff_path = tiff_path
                logger.info("TIFF saved: %s", tiff_path)
            else:
                result.warnings.append(f"TIFF conversion failed: {msg}")

        # Step 11: Log to history
        if result.validation:
            _progress("Logging to history...", 0.95)
            history = ValidationHistory()
            spec_for_history = spec_loader.get(result.spec_id) if result.spec_id else {}
            history.record(result.validation, normalized, spec_for_history, pdf_path)

        result.success = True
        _progress("Complete.", 1.0)

    except Exception as e:
        logger.exception("Pipeline error: %s", e)
        result.errors.append(str(e))

    return result


@dataclass
class BatchResult:
    """Result from processing a batch of documents."""
    total: int = 0
    success_count: int = 0
    fail_count: int = 0
    error_count: int = 0
    results: List[PipelineResult] = field(default_factory=list)


BATCH_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg'}


def process_batch(
    folder_path: str,
    output_dir: str,
    spec_id: Optional[str] = None,
    anthropic_api_key: str = "",
    po_number: Optional[str] = None,
    organize_by_po: bool = False,
    tiff_dpi: int = 300,
    tiff_compression: str = "lzw",
    preprocessing_dpi: int = 300,
    paddle_model_path: Optional[str] = None,
    on_file_start: Optional[callable] = None,
    on_file_complete: Optional[callable] = None,
    cancel_flag: Optional[callable] = None,
) -> BatchResult:
    """
    Process all supported documents in a folder.

    Args:
        folder_path: Directory containing MTR files.
        output_dir: Archive/output directory for TIFF files.
        spec_id: Specification ID (None for auto-detect).
        anthropic_api_key: Anthropic API key.
        po_number: Explicit PO override for all files.
        organize_by_po: Create PO subfolders.
        tiff_dpi: DPI for TIFF output.
        tiff_compression: TIFF compression method.
        preprocessing_dpi: DPI for rendering PDF pages for OCR.
        paddle_model_path: Optional PaddleOCR model path.
        on_file_start: Callback(filename, index, total) before each file.
        on_file_complete: Callback(filename, PipelineResult, index, total) after each file.
        cancel_flag: Callable returning True to cancel between files.

    Returns:
        BatchResult with per-file results.
    """
    batch = BatchResult()
    folder = Path(folder_path)

    files = sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in BATCH_EXTENSIONS
    )
    batch.total = len(files)

    for idx, file_path in enumerate(files):
        # Check cancel
        if cancel_flag and cancel_flag():
            logger.info("Batch cancelled at file %d/%d", idx + 1, batch.total)
            break

        filename = file_path.name

        if on_file_start:
            on_file_start(filename, idx, batch.total)

        try:
            result = process_document(
                pdf_path=str(file_path),
                output_dir=output_dir,
                spec_id=spec_id,
                anthropic_api_key=anthropic_api_key,
                paddle_model_path=paddle_model_path,
                preprocessing_dpi=preprocessing_dpi,
                tiff_dpi=tiff_dpi,
                tiff_compression=tiff_compression,
                po_number=po_number,
                organize_by_po=organize_by_po,
            )
            batch.results.append(result)

            if not result.success:
                batch.error_count += 1
            elif result.validation and result.validation.overall_status == 'FAIL':
                batch.fail_count += 1
            else:
                batch.success_count += 1

        except Exception as e:
            logger.exception("Batch error on %s: %s", filename, e)
            err_result = PipelineResult(source_file=str(file_path))
            err_result.errors.append(str(e))
            batch.results.append(err_result)
            batch.error_count += 1
            result = err_result

        if on_file_complete:
            on_file_complete(filename, result, idx, batch.total)

    return batch
