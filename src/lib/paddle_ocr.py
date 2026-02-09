"""
PaddleOCR wrapper for text extraction from MTR document images.

Uses PaddleOCR (PP-OCRv5) for CPU-based text extraction.
Supports multi-page documents and merges cross-page tables.
"""

import logging
import os
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Suppress PaddleOCR model source connectivity check
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# Module-level model instance for lazy singleton
_ocr_instance = None


def _get_ocr(model_path: Optional[str] = None):
    """
    Lazy-load PaddleOCR model. Keeps model in memory after first call.

    Args:
        model_path: Optional custom model directory path.
    """
    global _ocr_instance

    if _ocr_instance is not None:
        return _ocr_instance

    from paddleocr import PaddleOCR

    kwargs = {
        'device': 'cpu',
        'enable_mkldnn': False,
        'cpu_threads': os.cpu_count() or 10,
        # Use mobile models (much faster, sufficient for printed MTRs)
        'text_detection_model_name': 'PP-OCRv5_mobile_det',
        'text_recognition_model_name': 'latin_PP-OCRv5_mobile_rec',
        # Skip redundant steps — our preprocessor already deskews/orients
        'use_doc_orientation_classify': False,
        'use_doc_unwarping': False,
        'use_textline_orientation': False,
    }
    if model_path:
        kwargs['text_recognition_model_dir'] = model_path

    logger.info("Loading PaddleOCR model (first call)...")
    _ocr_instance = PaddleOCR(**kwargs)
    logger.info("PaddleOCR model loaded.")

    return _ocr_instance


def extract_text(image_paths: List[str], model_path: Optional[str] = None) -> str:
    """
    Extract text from one or more document images using PaddleOCR.

    Processes each image, detects text regions, and returns combined output.

    Args:
        image_paths: List of image file paths (PNG recommended).
        model_path: Optional custom model directory.

    Returns:
        Combined OCR text output with reading order preserved.
    """
    ocr = _get_ocr(model_path)
    all_text_blocks = []

    for i, img_path in enumerate(image_paths):
        if not Path(img_path).exists():
            logger.warning("Image not found, skipping: %s", img_path)
            continue

        if len(image_paths) > 1:
            all_text_blocks.append(f"\n--- Page {i + 1} ---\n")

        results = ocr.predict(img_path)

        if results is None:
            logger.warning("OCR returned no results for: %s", img_path)
            continue

        page_lines = _extract_lines_from_result(results)
        all_text_blocks.extend(page_lines)

    return "\n".join(all_text_blocks)


def _extract_lines_from_result(results) -> List[str]:
    """
    Process PaddleOCR 3.x predict() results into text lines.

    PaddleOCR 3.x returns a list of result objects with:
      - result['rec_texts']: list of recognized text strings
      - result['rec_scores']: list of confidence scores
      - result['dt_polys']: list of bounding polygons

    We sort by vertical position to reconstruct reading order and group
    nearby text into lines.
    """
    lines = []

    for result in results:
        if result is None:
            continue

        # Extract fields from PaddleOCR 3.x result object
        try:
            texts = result.get('rec_texts', []) if isinstance(result, dict) else getattr(result, 'rec_texts', [])
            scores = result.get('rec_scores', []) if isinstance(result, dict) else getattr(result, 'rec_scores', [])
            polys = result.get('dt_polys', []) if isinstance(result, dict) else getattr(result, 'dt_polys', [])
        except (AttributeError, TypeError):
            logger.warning("Unexpected OCR result format: %s", type(result))
            continue

        if not texts:
            continue

        # Build text items with position info
        text_items = []
        for text, poly in zip(texts, polys):
            # poly is [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            y_pos = min(pt[1] for pt in poly)
            x_pos = min(pt[0] for pt in poly)

            text_items.append({
                'text': str(text).strip(),
                'y': float(y_pos),
                'x': float(x_pos),
            })

        # Sort by vertical position, then horizontal
        text_items.sort(key=lambda t: (t['y'], t['x']))

        # Group into lines (items within 15px vertically are same line)
        current_line_items = []
        current_y = -100

        for item in text_items:
            if abs(item['y'] - current_y) > 15:
                # New line
                if current_line_items:
                    current_line_items.sort(key=lambda t: t['x'])
                    line_text = "  ".join(t['text'] for t in current_line_items)
                    lines.append(line_text)
                current_line_items = [item]
                current_y = item['y']
            else:
                current_line_items.append(item)

        # Don't forget last line
        if current_line_items:
            current_line_items.sort(key=lambda t: t['x'])
            line_text = "  ".join(t['text'] for t in current_line_items)
            lines.append(line_text)

    return lines


def release_model():
    """Release the OCR model from memory."""
    global _ocr_instance
    _ocr_instance = None
    logger.info("PaddleOCR model released.")
