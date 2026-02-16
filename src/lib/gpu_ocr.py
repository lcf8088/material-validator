"""
GPU-accelerated OCR using RapidOCR + ONNX Runtime CUDA.

Uses PP-OCRv4 ONNX models via RapidOCR with onnxruntime-gpu CUDAExecutionProvider.
Falls back to CPU if CUDA is unavailable. Drop-in replacement for paddle_ocr.extract_text().

Benchmark (10-page MTR @ 150 DPI, RTX 5090):
  - GPU: ~10s (1.0s/page)
  - CPU: ~77s (7.7s/page)
  - PaddleOCR CPU: ~172s (17.2s/page)
"""

import glob
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Module-level singleton
_engine = None
_engine_mode = None  # 'gpu' or 'cpu'


def _ensure_cuda_dlls():
    """Add NVIDIA pip package DLL directories to PATH for CUDA runtime resolution."""
    site_packages = os.path.join(sys.prefix, 'Lib', 'site-packages')
    nvidia_dirs = glob.glob(os.path.join(site_packages, 'nvidia', '*', 'bin'))
    existing_path = os.environ.get('PATH', '')
    new_dirs = [d for d in nvidia_dirs if os.path.isdir(d) and d not in existing_path]
    if new_dirs:
        os.environ['PATH'] = ';'.join(new_dirs) + ';' + existing_path


def _get_engine(use_gpu: bool = True):
    """Lazy-load RapidOCR engine. Keeps model in memory after first call."""
    global _engine, _engine_mode

    if _engine is not None:
        return _engine, _engine_mode

    if use_gpu:
        _ensure_cuda_dlls()

    from rapidocr_onnxruntime import RapidOCR

    if use_gpu:
        try:
            import onnxruntime as ort
            providers = ort.get_available_providers()
            if 'CUDAExecutionProvider' not in providers:
                logger.warning("CUDAExecutionProvider not available, falling back to CPU")
                use_gpu = False
        except ImportError:
            use_gpu = False

    if use_gpu:
        logger.info("Loading RapidOCR with CUDA GPU...")
        try:
            _engine = RapidOCR(det_use_cuda=True, rec_use_cuda=True, cls_use_cuda=True)
            _engine_mode = 'gpu'
            # Warm up GPU (first inference triggers model upload to GPU memory)
            import numpy as np
            dummy = np.zeros((48, 320, 3), dtype=np.uint8)
            _engine(dummy)
            logger.info("RapidOCR GPU engine loaded and warmed up.")
            return _engine, _engine_mode
        except Exception as e:
            logger.warning("GPU init failed (%s), falling back to CPU", e)
            _engine = None

    logger.info("Loading RapidOCR with CPU...")
    _engine = RapidOCR()
    _engine_mode = 'cpu'
    logger.info("RapidOCR CPU engine loaded.")
    return _engine, _engine_mode


def gpu_available() -> bool:
    """Check if GPU OCR is available without loading the engine."""
    try:
        _ensure_cuda_dlls()
        import onnxruntime as ort
        return 'CUDAExecutionProvider' in ort.get_available_providers()
    except ImportError:
        return False


def extract_text(image_paths: List[str], model_path: Optional[str] = None) -> str:
    """
    Extract text from document images using RapidOCR (GPU or CPU).

    Drop-in replacement for paddle_ocr.extract_text() — same interface and output format.

    Args:
        image_paths: List of image file paths (PNG recommended).
        model_path: Unused, kept for API compatibility with paddle_ocr.

    Returns:
        Combined OCR text output with reading order preserved.
    """
    engine, mode = _get_engine()
    all_text_blocks = []

    for i, img_path in enumerate(image_paths):
        if not Path(img_path).exists():
            logger.warning("Image not found, skipping: %s", img_path)
            continue

        if len(image_paths) > 1:
            all_text_blocks.append(f"\n--- Page {i + 1} ---\n")

        result, _ = engine(img_path)

        if result is None:
            logger.warning("OCR returned no results for: %s", img_path)
            continue

        # RapidOCR returns: [[box, text, confidence], ...]
        # box is [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
        page_lines = _group_into_lines(result)
        all_text_blocks.extend(page_lines)

    return "\n".join(all_text_blocks)


def _group_into_lines(results) -> List[str]:
    """Group RapidOCR results into reading-order lines (same logic as paddle_ocr)."""
    if not results:
        return []

    text_items = []
    for box, text, _conf in results:
        y_pos = min(pt[1] for pt in box)
        x_pos = min(pt[0] for pt in box)
        text_items.append({
            'text': str(text).strip(),
            'y': float(y_pos),
            'x': float(x_pos),
        })

    text_items.sort(key=lambda t: (t['y'], t['x']))

    if not text_items:
        return []

    lines = []
    current_row = [text_items[0]]
    current_y = text_items[0]['y']

    for item in text_items[1:]:
        if abs(item['y'] - current_y) > 15.0:
            current_row.sort(key=lambda t: t['x'])
            lines.append("  ".join(t['text'] for t in current_row))
            current_row = [item]
            current_y = item['y']
        else:
            current_row.append(item)

    current_row.sort(key=lambda t: t['x'])
    lines.append("  ".join(t['text'] for t in current_row))

    return lines


def release_model():
    """Release the OCR engine from memory."""
    global _engine, _engine_mode
    _engine = None
    _engine_mode = None
    logger.info("RapidOCR engine released.")
