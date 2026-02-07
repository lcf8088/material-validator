"""
PaddleOCR-VL wrapper for high-fidelity OCR with table structure recognition.

Uses PaddleOCR (with PP-OCRv4 or VL model) for local GPU-accelerated text
extraction from MTR document images. Supports multi-page documents and
merges cross-page tables.
"""

import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

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
        'use_angle_cls': True,
        'lang': 'en',
        'use_gpu': True,
        'show_log': False,
        'type': 'structure',  # Enable table structure recognition
    }
    if model_path:
        kwargs['rec_model_dir'] = model_path

    logger.info("Loading PaddleOCR model (first call)...")
    _ocr_instance = PaddleOCR(**kwargs)
    logger.info("PaddleOCR model loaded.")

    return _ocr_instance


def extract_text(image_paths: List[str], model_path: Optional[str] = None) -> str:
    """
    Extract text from one or more document images using PaddleOCR.

    Processes each image, detects text regions and table structures,
    and returns combined Markdown-formatted output.

    Args:
        image_paths: List of image file paths (PNG recommended).
        model_path: Optional custom model directory.

    Returns:
        Combined OCR text output with table structure preserved as Markdown.
    """
    ocr = _get_ocr(model_path)
    all_text_blocks = []

    for i, img_path in enumerate(image_paths):
        if not Path(img_path).exists():
            logger.warning("Image not found, skipping: %s", img_path)
            continue

        if len(image_paths) > 1:
            all_text_blocks.append(f"\n--- Page {i + 1} ---\n")

        result = ocr.ocr(img_path, cls=True)

        if result is None:
            logger.warning("OCR returned no results for: %s", img_path)
            continue

        page_lines = _extract_lines_from_result(result)
        all_text_blocks.extend(page_lines)

    return "\n".join(all_text_blocks)


def _extract_lines_from_result(result) -> List[str]:
    """
    Process PaddleOCR result into text lines.

    PaddleOCR returns a list of pages, each page is a list of detected
    text regions: [[box_coords, (text, confidence)], ...]

    We sort by vertical position to reconstruct reading order and group
    nearby text into lines.
    """
    lines = []

    for page in result:
        if page is None:
            continue

        # Extract text with position info
        text_items = []
        for item in page:
            box = item[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            text, confidence = item[1]

            # Use top-left y coordinate for vertical ordering
            y_pos = min(pt[1] for pt in box)
            x_pos = min(pt[0] for pt in box)

            text_items.append({
                'text': text.strip(),
                'y': y_pos,
                'x': x_pos,
                'confidence': confidence,
            })

        # Sort by vertical position, then horizontal
        text_items.sort(key=lambda t: (t['y'], t['x']))

        # Group into lines (items within 10px vertically are same line)
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
