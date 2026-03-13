"""
Main OCR pipeline orchestrator.

Ties together: preprocessor -> PaddleOCR -> Claude parser -> validation -> TIFF -> staging.
Single entry point for processing MTR documents end-to-end.
"""

import logging
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .assembly import AssemblyResult, detect_assembly, process_assembly
from .extractor import pdf_to_images, normalize_extracted_data
from .preprocessor import extract_native_text, is_digital_native, preprocess_images, fix_rotated_pages
from .paddle_ocr import extract_text as paddle_extract_text

# GPU OCR availability (checked once at import time)
_gpu_ocr_available = False
try:
    from .gpu_ocr import extract_text as gpu_extract_text, gpu_available, _ensure_cuda_dlls
    _ensure_cuda_dlls()  # Must happen before any onnxruntime import
    _gpu_ocr_available = gpu_available()
except ImportError:
    pass


# Default OCR function (patchable by tests via mock)
ocr_extract_text = paddle_extract_text


def _get_ocr_func(use_gpu: bool = True):
    """Return the appropriate OCR extract function.

    If tests have patched pipeline.ocr_extract_text, use that.
    Otherwise select GPU or CPU based on availability.
    """
    import sys
    module = sys.modules[__name__]
    current = getattr(module, 'ocr_extract_text', paddle_extract_text)
    # If tests have replaced ocr_extract_text with a mock, honor it
    if current is not paddle_extract_text and (not _gpu_ocr_available or current is not gpu_extract_text):
        return current, "mock"
    if use_gpu and _gpu_ocr_available:
        return gpu_extract_text, "gpu"
    return paddle_extract_text, "cpu"
from .claude_parser import parse_and_validate, extract_tables_with_opus, crop_table_regions
from .matcher import SpecMatcher
from .validator import SpecValidator, CertValidation
from .sanity import run_all_sanity_checks
from .spec_loader import SpecLoader

logger = logging.getLogger(__name__)

# Regex to detect compact integer notation legend in OCR text
_COMPACT_NOTATION_RE = re.compile(
    r'\*\d\s*:\s*X\s*\d+|OTHER\s*:\s*X\s*\d+', re.IGNORECASE)


def _fix_compact_notation_chemistry(
    chemistry: Dict[str, Any],
    spec: Optional[Dict[str, Any]],
    ocr_text: str,
) -> Dict[str, Any]:
    """Correct chemistry values when compact integer notation multiplier was misapplied.

    Detects compact notation certs (footnotes like *2:X10, OTHER:X100) and for
    each out-of-spec element, tries dividing/multiplying by 10 to see if the
    result falls in spec.  This catches the common case where Claude applies
    the wrong column multiplier (e.g. X10 instead of X100).
    """
    if not spec or not chemistry:
        return chemistry
    # Only run on compact notation certs
    if not _COMPACT_NOTATION_RE.search(ocr_text):
        return chemistry

    chem_spec = spec.get('chemistry') or {}
    fixed = dict(chemistry)

    for elem, value in chemistry.items():
        if elem.endswith('_unit') or value is None:
            continue
        limits = chem_spec.get(elem) or {}
        spec_max = limits.get('max')
        spec_min = limits.get('min')
        if spec_max is None and spec_min is None:
            continue

        try:
            val = float(value)
        except (ValueError, TypeError):
            continue

        # Check if current value is out of spec
        in_spec = True
        if spec_max is not None and val > float(spec_max):
            in_spec = False
        if spec_min is not None and val < float(spec_min):
            in_spec = False

        if in_spec:
            continue

        # Try shifting multiplier by factors of 10 (divide or multiply)
        for factor in [10, 0.1, 100, 0.01]:
            candidate = val / factor if factor > 1 else val * (1 / factor)
            candidate_ok = True
            if spec_max is not None and candidate > float(spec_max):
                candidate_ok = False
            if spec_min is not None and candidate < float(spec_min):
                candidate_ok = False
            if candidate_ok and candidate > 0:
                logger.warning(
                    "Compact notation fix: %s=%.4g out of spec (min=%s max=%s), "
                    "corrected to %.4g (factor=1/%g)",
                    elem, val, spec_min, spec_max, candidate, factor)
                fixed[elem] = candidate
                break

    return fixed


def _spec_aware_merge(
    sonnet_data: Dict[str, Any],
    opus_data: Dict[str, Any],
    spec: Optional[Dict[str, Any]],
    section: str,
) -> Dict[str, Any]:
    """Merge Opus extraction into Sonnet with spec-aware validation.

    For each field, Opus values override Sonnet UNLESS:
    - Opus value is null → keep Sonnet value
    - Spec is available AND Opus value is wildly out of range
      (>5x spec max or <spec_min/5) AND Sonnet value is more
      reasonable → keep Sonnet value

    This catches cases where Opus misreads dense tables (e.g. column
    shifts in compact integer notation Japanese certs) while still
    preferring Opus for normal extractions.
    """
    merged = dict(sonnet_data)
    spec_limits = (spec or {}).get(section) or {}

    for key, opus_val in opus_data.items():
        if opus_val is None:
            continue

        sonnet_val = sonnet_data.get(key)
        limits = spec_limits.get(key) or {}

        # Skip unit fields — they are set alongside their numeric field
        if key.endswith('_unit'):
            merged[key] = opus_val
            continue

        # Try numeric comparison when spec limits exist
        try:
            opus_num = float(opus_val)
        except (ValueError, TypeError):
            merged[key] = opus_val
            continue

        spec_max = limits.get('max')
        spec_min = limits.get('min')
        wildly_off = False

        if spec_max is not None:
            try:
                if opus_num > float(spec_max) * 5:
                    wildly_off = True
            except (ValueError, TypeError):
                pass

        if spec_min is not None and not wildly_off:
            try:
                smin = float(spec_min)
                if smin > 0 and opus_num < smin / 5:
                    wildly_off = True
            except (ValueError, TypeError):
                pass

        if wildly_off and sonnet_val is not None:
            try:
                sonnet_num = float(sonnet_val)
                # Check if Sonnet is more reasonable (within 5x of spec range)
                sonnet_ok = True
                if spec_max is not None:
                    try:
                        if sonnet_num > float(spec_max) * 5:
                            sonnet_ok = False
                    except (ValueError, TypeError):
                        pass
                if spec_min is not None:
                    try:
                        smin = float(spec_min)
                        if smin > 0 and sonnet_num < smin / 5:
                            sonnet_ok = False
                    except (ValueError, TypeError):
                        pass
                if sonnet_ok:
                    logger.warning(
                        "Opus %s.%s=%.4g wildly off spec (min=%s max=%s), "
                        "keeping Sonnet value %.4g",
                        section, key, opus_num, spec_min, spec_max, sonnet_num)
                    # Revert unit field to Sonnet's unit as well
                    unit_key = key + '_unit'
                    if unit_key in merged and unit_key in sonnet_data:
                        merged[unit_key] = sonnet_data[unit_key]
                    continue  # keep Sonnet value in merged
            except (ValueError, TypeError):
                pass

        logger.info("Merge %s.%s: Sonnet=%s -> Opus=%s", section, key, sonnet_val, opus_val)

        # If Opus is out of spec and Sonnet is in spec, prefer Sonnet
        # (catches column shifts, wrong multipliers in compact notation)
        if sonnet_val is not None and (spec_max is not None or spec_min is not None):
            try:
                sonnet_num = float(sonnet_val)
                opus_in_spec = True
                sonnet_in_spec = True
                if spec_max is not None:
                    smax = float(spec_max)
                    if opus_num > smax:
                        opus_in_spec = False
                    if sonnet_num > smax:
                        sonnet_in_spec = False
                if spec_min is not None:
                    smin = float(spec_min)
                    if opus_num < smin:
                        opus_in_spec = False
                    if sonnet_num < smin:
                        sonnet_in_spec = False
                if not opus_in_spec and sonnet_in_spec:
                    logger.warning(
                        "Opus %s.%s=%.4g out of spec (min=%s max=%s), "
                        "Sonnet value %.4g is in spec — keeping Sonnet",
                        section, key, opus_num, spec_min, spec_max, sonnet_num)
                    # Revert unit field to Sonnet's unit as well
                    unit_key = key + '_unit'
                    if unit_key in merged and unit_key in sonnet_data:
                        merged[unit_key] = sonnet_data[unit_key]
                    continue  # keep Sonnet value in merged
            except (ValueError, TypeError):
                pass

        merged[key] = opus_val

    # --- Steel sanity: YS must be < TS ---
    # If Opus swapped columns (reads TS as YS), prefer Sonnet's values
    if section == 'mechanical':
        try:
            ys = float(merged.get('yield_strength') or 0)
            ts = float(merged.get('tensile_strength') or 0)
            if ys > 0 and ts > 0 and ys >= ts:
                logger.warning(
                    "Opus YS(%.1f) >= TS(%.1f) — column shift detected, "
                    "reverting mechanical to Sonnet values", ys, ts)
                # Revert YS and TS (and their units) to Sonnet values if available
                for fld in ('yield_strength', 'tensile_strength'):
                    sv = sonnet_data.get(fld)
                    if sv is not None:
                        merged[fld] = sv
                        logger.info("Reverted %s to Sonnet value: %s", fld, sv)
                        unit_key = fld + '_unit'
                        if unit_key in sonnet_data:
                            merged[unit_key] = sonnet_data[unit_key]
        except (ValueError, TypeError):
            pass

    return merged


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
    assembly_result: Optional[AssemblyResult] = None
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
    t0 = time.time()
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
        logger.info("[TIMING] Haiku MTR check: %.1fs -> %s", time.time() - t0, answer)
        return answer.startswith("YES")
    except Exception as e:
        logger.warning("Haiku MTR check failed (%s, %.1fs), assuming text is OK", e, time.time() - t0)
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
    use_gpu: bool = True,
) -> tuple:
    """Phase A: Staged text extraction from a document.

    Tries stages in order: direct text -> OCR@150 -> OCR@300.
    Returns (ocr_text, image_paths, is_pdf, stage_used).
    """
    t_start = time.time()
    filename = Path(pdf_path).name
    pdf_path_obj = Path(pdf_path)
    is_pdf = pdf_path_obj.suffix.lower() == '.pdf'

    def _elapsed():
        return time.time() - t_start

    # DPI for OCR stages — 150 is 44% fewer pixels than 200, sufficient for printed MTRs
    ocr_dpi = 150

    # --- Stage 1: Direct text extraction (digital-native PDFs) ---
    direct_text = ""
    page_texts = []
    if is_pdf:
        t1 = time.time()
        direct_text, page_texts = extract_native_text(pdf_path, return_page_texts=True)
        logger.info("[TIMING] %s | extract_native_text: %.1fs (%d chars)",
                    filename, time.time() - t1, len(direct_text))

        t1 = time.time()
        quality_ok = _text_quality_ok(direct_text, api_key, page_texts=page_texts)
        logger.info("[TIMING] %s | Stage 1 quality check (Haiku): %.1fs -> %s",
                    filename, time.time() - t1, "PASS" if quality_ok else "FAIL")

        if quality_ok:
            t1 = time.time()
            image_paths = pdf_to_images(pdf_path, dpi=ocr_dpi)
            logger.info("[TIMING] %s | pdf_to_images@%d: %.1fs (%d pages)",
                        filename, ocr_dpi, time.time() - t1, len(image_paths))
            t1 = time.time()
            image_paths = fix_rotated_pages(image_paths)
            logger.info("[TIMING] %s | fix_rotated_pages: %.1fs", filename, time.time() - t1)
            logger.info("[TIMING] %s | pre_extract TOTAL: %.1fs (stage=direct)",
                        filename, _elapsed())
            return direct_text, image_paths, is_pdf, "direct"

        logger.info("Stage 1 FAILED: direct text (%d chars), escalating to OCR@%d",
                     len(direct_text), ocr_dpi)

    # Determine if PDF is scanned (very little embedded text)
    scanned = len(direct_text.strip()) < 50

    # --- Stage 2: PaddleOCR at ocr_dpi ---
    t1 = time.time()
    if is_pdf:
        image_paths = pdf_to_images(pdf_path, dpi=ocr_dpi)
    else:
        image_paths = [pdf_path]
    logger.info("[TIMING] %s | pdf_to_images@%d: %.1fs (%d pages)",
                filename, ocr_dpi, time.time() - t1, len(image_paths))

    t1 = time.time()
    image_paths = fix_rotated_pages(image_paths)
    logger.info("[TIMING] %s | fix_rotated_pages: %.1fs", filename, time.time() - t1)

    if scanned:
        t1 = time.time()
        ocr_images = preprocess_images(image_paths)
        logger.info("[TIMING] %s | preprocess_images: %.1fs", filename, time.time() - t1)
    else:
        ocr_images = image_paths

    ocr_func, ocr_backend = _get_ocr_func(use_gpu)
    t1 = time.time()
    ocr_text = ocr_func(ocr_images, model_path=paddle_model_path)
    logger.info("[TIMING] %s | OCR(%s)@%d: %.1fs (%d chars)",
                filename, ocr_backend, ocr_dpi, time.time() - t1, len(ocr_text))

    t1 = time.time()
    quality_ok = _text_quality_ok(ocr_text, api_key)
    logger.info("[TIMING] %s | Stage 2 quality check (Haiku): %.1fs -> %s",
                filename, time.time() - t1, "PASS" if quality_ok else "FAIL")

    if quality_ok:
        logger.info("[TIMING] %s | pre_extract TOTAL: %.1fs (stage=ocr_%d_%s)",
                    filename, _elapsed(), ocr_dpi, ocr_backend)
        return ocr_text, image_paths, is_pdf, f"ocr_{ocr_dpi}"

    logger.info("Stage 2 FAILED: OCR@%d (%d chars), escalating to OCR@300", ocr_dpi, len(ocr_text))

    # --- Stage 3: PaddleOCR at 300 DPI (accept unconditionally) ---
    if is_pdf:
        t1 = time.time()
        image_paths = pdf_to_images(pdf_path, dpi=preprocessing_dpi)
        logger.info("[TIMING] %s | pdf_to_images@300: %.1fs (%d pages)",
                    filename, time.time() - t1, len(image_paths))
        t1 = time.time()
        image_paths = fix_rotated_pages(image_paths)
        logger.info("[TIMING] %s | fix_rotated_pages: %.1fs", filename, time.time() - t1)
        if scanned:
            t1 = time.time()
            ocr_images = preprocess_images(image_paths)
            logger.info("[TIMING] %s | preprocess_images@300: %.1fs", filename, time.time() - t1)
        else:
            ocr_images = image_paths
    else:
        ocr_images = image_paths

    t1 = time.time()
    ocr_text = ocr_func(ocr_images, model_path=paddle_model_path)
    logger.info("[TIMING] %s | OCR(%s)@300: %.1fs (%d chars)",
                filename, ocr_backend, time.time() - t1, len(ocr_text))

    logger.info("[TIMING] %s | pre_extract TOTAL: %.1fs (stage=ocr_300_%s)",
                filename, _elapsed(), ocr_backend)
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
    use_gpu_ocr: bool = True,
    force_assembly: Optional[bool] = None,
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
    t_pipeline_start = time.time()
    filename = Path(pdf_path).name

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
                use_gpu=use_gpu_ocr,
            )
            logger.info("Staged extraction complete (%s, %d chars)", stage_used, len(ocr_text))
            _progress("Text extraction complete.", 0.30)

        if not image_paths:
            result.errors.append("No pages/images extracted from document.")
            return result

        if not ocr_text.strip():
            result.errors.append("OCR extracted no text from document.")
            return result

        # --- Render high-quality images at 300 DPI ---
        # Raw grayscale (no posterize) for Claude — maximum detail for table reading.
        # Posterized grayscale for TIFF — compact archive output.
        enhanced_image_paths = None  # posterized, for TIFF
        claude_hq_paths = None       # raw grayscale, for Claude
        if is_pdf:
            try:
                _progress("Rendering enhanced images...", 0.33)
                from gui.tiff_export import render_enhanced_pages
                t_enhance = time.time()
                claude_hq_paths = render_enhanced_pages(pdf_path, dpi=tiff_dpi, posterize=False)
                enhanced_image_paths = render_enhanced_pages(pdf_path, dpi=tiff_dpi, posterize=True)
                logger.info("[TIMING] %s | render_enhanced_pages@%d: %.1fs (%d pages)",
                            filename, tiff_dpi, time.time() - t_enhance, len(enhanced_image_paths))
            except Exception as e:
                logger.warning("Enhanced image rendering failed, using raw images: %s", e)

        # Raw 300 DPI for Claude (max detail), fall back to OCR images
        claude_image_paths = claude_hq_paths or image_paths

        # --- Assembly detection and processing ---
        is_assembly = False

        # Filename-based assembly detection: "assy" in filename forces assembly mode
        if force_assembly is None and re.search(r'(?i)\bassy\b', Path(pdf_path).stem):
            is_assembly = True
            logger.info("Assembly detected via filename keyword 'assy': %s", filename)

        if force_assembly is True:
            is_assembly = True
        elif force_assembly is False:
            is_assembly = False
        elif not is_assembly and len(image_paths) >= 3:
            # Auto-detect: only check multi-page docs (assemblies have COC + MTRs)
            _progress("Checking for assembly packet...", 0.32)
            try:
                is_assembly = detect_assembly(image_paths, anthropic_api_key)
            except Exception as e:
                logger.warning("Assembly detection failed: %s", e)

        if is_assembly:
            _progress("Processing assembly packet...", 0.35)
            try:
                assembly_result = process_assembly(
                    image_paths=image_paths,
                    api_key=anthropic_api_key,
                    on_progress=on_progress,
                )
                result.assembly_result = assembly_result
                result.success = True

                # Store key fields for TIFF naming / display
                result.extracted_data = {
                    'po_number': assembly_result.po_number,
                    'customer_part_number': assembly_result.customer_part_number,
                    'heat_number': 'ASSEMBLY',
                    'material_grade': assembly_result.assembly_description,
                    '_assembly': True,
                }
                result.warnings.extend(assembly_result.warnings)

                # TIFF to staging
                if output_dir and is_pdf:
                    _progress("Assembling TIFF (staging)...", 0.90)
                    staging_dir = Path(tempfile.gettempdir()) / 'material-validator-staging'
                    staging_dir.mkdir(parents=True, exist_ok=True)
                    po = assembly_result.po_number or 'UNKNOWN-PO'
                    staging_name = f"staging_ASSY_{po}_{int(time.time())}.tiff"
                    staging_path = str(staging_dir / staging_name)
                    t_tiff = time.time()
                    if enhanced_image_paths:
                        from gui.tiff_export import enhanced_images_to_tiff
                        success_tiff, msg = enhanced_images_to_tiff(enhanced_image_paths, staging_path, dpi=tiff_dpi)
                    else:
                        from gui.tiff_export import pdf_to_tiff
                        success_tiff, msg = pdf_to_tiff(pdf_path, staging_path, tiff_dpi, tiff_compression)
                    logger.info("[TIMING] %s | TIFF conversion: %.1fs", filename, time.time() - t_tiff)
                    if success_tiff:
                        result.output_tiff_path = staging_path
                    else:
                        result.warnings.append(f"TIFF conversion failed: {msg}")

                total_pipeline = time.time() - t_pipeline_start
                _progress("Assembly validation complete.", 1.0)
                logger.info("[TIMING] %s | process_document (assembly) TOTAL: %.1fs",
                            filename, total_pipeline)
                return result

            except Exception as e:
                logger.exception("Assembly pipeline error: %s", e)
                result.errors.append(f"Assembly processing failed: {e}")
                return result

        # Detect Vendor Spec mode (extract only, no validation)
        vendor_spec_mode = (spec_id == "Vendor Spec")

        # Step 5: Claude structured parsing
        _progress("Parsing with Claude...", 0.45)
        spec_loader = SpecLoader.get_instance()
        spec_data = None
        if spec_id and not vendor_spec_mode:
            spec_data = spec_loader.get(spec_id)

        t_claude = time.time()
        raw_data = parse_and_validate(
            ocr_text=ocr_text,
            api_key=anthropic_api_key,
            spec=spec_data,
            spec_id=spec_id if not vendor_spec_mode else None,
            image_paths=claude_image_paths,
            model=extraction_model,
        )
        logger.info("[TIMING] %s | Claude parse (%s, %d images): %.1fs",
                    filename, extraction_model, len(image_paths), time.time() - t_claude)

        if raw_data.get('_extraction_status') == 'error':
            result.errors.append(f"Claude parsing failed: {raw_data.get('_error', 'Unknown')}")
            result.extracted_data = raw_data
            return result

        result.extracted_data = raw_data
        result.compliance_flags = raw_data.pop('compliance_flags', [])

        # Step 5a: Early spec detection for merge validation
        # If no spec_id was provided, try auto-detecting now so the Opus
        # merge can use spec limits to catch wrong-multiplier errors.
        if not spec_id and not vendor_spec_mode:
            try:
                _normalized_early = normalize_extracted_data(dict(raw_data))
                matcher = SpecMatcher()
                early_match = matcher.select_best_spec(_normalized_early)
                if early_match:
                    spec_id, _conf, _reason = early_match
                    spec_data = spec_loader.get(spec_id)
                    logger.info("Early spec detection for merge: %s (%.0f%%)", spec_id, _conf * 100)
            except Exception as e:
                logger.debug("Early spec detection failed: %s", e)

        # Step 5b: Opus precision pass for chemistry & mechanical tables
        # Sonnet misreads dense multi-row tables (Min/Max/Cer). Opus is
        # much more accurate, so we do a focused call for just the tables
        # and merge the results into Sonnet's extraction.
        if extraction_model != 'opus' and not vendor_spec_mode and image_paths:
            _progress("Reading tables with Opus...", 0.50)
            opus_tables = None
            try:
                # Crop table regions identified by Sonnet to minimize Opus tokens
                table_regions = raw_data.get('table_regions')
                if table_regions:
                    opus_images = crop_table_regions(claude_image_paths, table_regions)
                    logger.info("Cropped %d table region(s) for Opus", len(opus_images))
                else:
                    opus_images = claude_image_paths[:1]  # fallback: page 1 only
                    logger.info("No table_regions from Sonnet, sending page 1 to Opus")
                t_opus = time.time()
                opus_tables = extract_tables_with_opus(opus_images, anthropic_api_key)
                logger.info("[TIMING] %s | Opus table extraction: %.1fs", filename, time.time() - t_opus)
            except Exception as e:
                logger.warning("Opus table extraction failed: %s", e)
            if opus_tables:
                if opus_tables.get('heat_number'):
                    raw_data['heat_number'] = opus_tables['heat_number']
                    logger.info("Merged Opus heat_number: %s", opus_tables['heat_number'])
                if opus_tables.get('chemistry'):
                    # Spec-aware chemistry merge: field-level with validation
                    sonnet_chem = raw_data.get('chemistry') or {}
                    opus_chem = opus_tables['chemistry']
                    merged_chem = _spec_aware_merge(
                        sonnet_chem, opus_chem, spec_data, 'chemistry')
                    raw_data['chemistry'] = merged_chem
                    logger.info("Merged Opus chemistry: %d elements", len(merged_chem))
                if opus_tables.get('chemistry_qualifiers'):
                    raw_data['chemistry_qualifiers'] = opus_tables['chemistry_qualifiers']
                if opus_tables.get('mechanical'):
                    # Spec-aware mechanical merge: field-level with validation
                    sonnet_mech = raw_data.get('mechanical') or {}
                    opus_mech = opus_tables['mechanical']
                    merged_mech = _spec_aware_merge(
                        sonnet_mech, opus_mech, spec_data, 'mechanical')
                    raw_data['mechanical'] = merged_mech
                    logger.info("Merged Opus mechanical: %d properties", len(merged_mech))

        # Step 5c: Compact notation correction
        # Both models can misapply multipliers in compact integer notation certs.
        # Use spec limits to detect and correct wrong-multiplier chemistry values.
        if raw_data.get('chemistry') and spec_data and ocr_text:
            raw_data['chemistry'] = _fix_compact_notation_chemistry(
                raw_data['chemistry'], spec_data, ocr_text)

        # Step 6: Normalize extracted data
        _progress("Normalizing data...", 0.55)
        normalized = normalize_extracted_data(raw_data)

        result.normalized_data = normalized

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

        # Step 10: Assemble TIFF from enhanced images (or fall back to pdf_to_tiff)
        if output_dir and is_pdf:
            _progress("Assembling TIFF (staging)...", 0.85)

            staging_dir = Path(tempfile.gettempdir()) / 'material-validator-staging'
            staging_dir.mkdir(parents=True, exist_ok=True)

            heat_number = normalized.get('heat_number') or normalized.get('batch_number') or 'UNKNOWN'
            staging_name = f"staging_{heat_number}_{int(time.time())}.tiff"
            staging_path = str(staging_dir / staging_name)

            t_tiff = time.time()
            if enhanced_image_paths:
                from gui.tiff_export import enhanced_images_to_tiff
                success, msg = enhanced_images_to_tiff(enhanced_image_paths, staging_path, dpi=tiff_dpi)
            else:
                from gui.tiff_export import pdf_to_tiff
                success, msg = pdf_to_tiff(pdf_path, staging_path, tiff_dpi, tiff_compression)
            logger.info("[TIMING] %s | TIFF assembly: %.1fs", filename, time.time() - t_tiff)
            if success:
                result.output_tiff_path = staging_path
                logger.info("Staging TIFF saved: %s", staging_path)
            else:
                result.warnings.append(f"TIFF conversion failed: {msg}")

        result.success = True
        total_pipeline = time.time() - t_pipeline_start
        _progress("Complete.", 1.0)
        logger.info("[TIMING] %s | process_document TOTAL: %.1fs", filename, total_pipeline)

    except Exception as e:
        logger.exception("Pipeline error: %s", e)
        result.errors.append(str(e))

    return result


