"""
Image preprocessing for scanned MTR documents.

Detects digital-native vs scanned PDFs and applies preprocessing
pipeline (de-skew, contrast enhancement, binarization) to improve
OCR accuracy on scanned documents.
"""

import base64
import logging
import tempfile
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


def extract_native_text(pdf_path: str, return_page_texts: bool = False):
    """Extract embedded text from a PDF using PyMuPDF.

    Returns page-separated text using the same '--- Page N ---' markers
    that PaddleOCR produces, so downstream page relevance scoring works
    identically regardless of extraction method.

    If return_page_texts=True, returns (combined_text, [per_page_texts]).
    """
    import fitz

    doc = fitz.open(pdf_path)
    parts = []
    page_texts = []
    for i, page in enumerate(doc, 1):
        text = page.get_text().strip()
        page_texts.append(text)
        if len(doc) > 1:
            parts.append(f"\n--- Page {i} ---\n")
        parts.append(text)
    doc.close()
    combined = "\n".join(parts)
    if return_page_texts:
        return combined, page_texts
    return combined


def is_digital_native(pdf_path: str) -> bool:
    """
    Detect whether a PDF is digital-native (has a text layer) or scanned.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        True if the PDF has extractable text (digital-native), False if scanned.
    """
    return len(extract_native_text(pdf_path)) > 50


def fix_rotated_pages(image_paths: List[str]) -> List[str]:
    """
    Check each page image for 90-degree rotation and fix if needed.

    Runs on all pages (digital-native or scanned) because multi-document
    PDFs may contain individual rotated pages even in otherwise
    digital-native bundles.

    Args:
        image_paths: List of page image file paths

    Returns:
        List of image paths (rotated pages saved to new files)
    """
    import cv2

    result_paths = []
    for img_path in image_paths:
        img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            result_paths.append(img_path)
            continue

        rotated = _fix_page_rotation(img)
        if rotated.shape != img.shape:
            # Page was rotated (dimensions changed) — save to a new file
            out_path = str(Path(img_path).with_name(Path(img_path).stem + '_rotfix.png'))
            cv2.imwrite(out_path, rotated)
            result_paths.append(out_path)
        else:
            result_paths.append(img_path)

    return result_paths


def fix_upside_down_pages(
    image_paths: List[str],
    api_key: str,
) -> Tuple[List[str], List[int]]:
    """Detect and fix 180-degree (upside-down) page rotation using Haiku vision.

    Sends each page image to Haiku and asks if the text is upside down.
    Rotates any upside-down pages 180 degrees in place.

    Args:
        image_paths: List of page image file paths
        api_key: Anthropic API key for Haiku calls

    Returns:
        (updated_image_paths, rotated_indices) where rotated_indices is a
        list of 0-based indices that were flipped 180 degrees.
    """
    import anthropic
    import cv2

    if not image_paths or not api_key:
        return image_paths, []

    client = anthropic.Anthropic(api_key=api_key)
    rotated_indices = []
    result_paths = list(image_paths)

    for i, img_path in enumerate(image_paths):
        try:
            with open(img_path, "rb") as f:
                img_bytes = f.read()
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

            suffix = Path(img_path).suffix.lower()
            media_type = "image/png" if suffix == ".png" else "image/jpeg"

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": img_b64,
                        }},
                        {"type": "text", "text":
                            "Is the text on this page upside down (rotated 180 degrees)? "
                            "Answer YES or NO only."},
                    ],
                }],
            )
            answer = response.content[0].text.strip().upper()
            logger.info("Page %d upside-down check: %s", i + 1, answer)

            if answer.startswith("YES"):
                img = cv2.imread(img_path)
                if img is not None:
                    flipped = cv2.rotate(img, cv2.ROTATE_180)
                    out_path = str(Path(img_path).with_name(
                        Path(img_path).stem + '_flip180.png'))
                    cv2.imwrite(out_path, flipped)
                    result_paths[i] = out_path
                    rotated_indices.append(i)
                    logger.info("Page %d rotated 180 degrees", i + 1)

        except Exception as e:
            logger.warning("Upside-down check failed for page %d: %s", i + 1, e)

    return result_paths, rotated_indices


def rotate_pages_180(image_paths: List[str], indices: List[int]) -> List[str]:
    """Rotate specific pages 180 degrees.

    Applies the same 180-degree rotation detected by fix_upside_down_pages
    to a different set of images (e.g. enhanced TIFF images, Claude HQ images).

    Args:
        image_paths: List of page image file paths
        indices: 0-based page indices to rotate

    Returns:
        Updated list of image paths with rotated pages saved to new files.
    """
    import cv2

    if not indices:
        return image_paths

    result_paths = list(image_paths)
    for i in indices:
        if i >= len(image_paths):
            continue
        img_path = image_paths[i]
        try:
            img = cv2.imread(img_path)
            if img is not None:
                flipped = cv2.rotate(img, cv2.ROTATE_180)
                out_path = str(Path(img_path).with_name(
                    Path(img_path).stem + '_flip180.png'))
                cv2.imwrite(out_path, flipped)
                result_paths[i] = out_path
        except Exception as e:
            logger.warning("Failed to rotate page %d: %s", i + 1, e)

    return result_paths


def preprocess_images(image_paths: List[str], output_dir: str = "") -> List[str]:
    """
    Preprocess scanned document images to improve OCR quality.

    Pipeline:
    1. Convert to grayscale
    2. De-skew (correct rotation)
    3. Contrast enhancement (CLAHE)
    4. Adaptive threshold binarization

    Args:
        image_paths: List of image file paths to preprocess
        output_dir: Directory for output images (default: temp dir)

    Returns:
        List of preprocessed image file paths
    """
    import cv2
    import numpy as np

    if not output_dir:
        output_dir = str(Path(tempfile.gettempdir()) / 'mtr_preprocessed')
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    processed_paths = []

    for img_path in image_paths:
        img = cv2.imread(img_path)
        if img is None:
            # Can't read image, skip preprocessing and pass through
            processed_paths.append(img_path)
            continue

        # 1. Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 1b. Detect and correct 90-degree rotation
        gray = _fix_page_rotation(gray)

        # 2. De-skew
        gray = _deskew(gray)

        # 3. CLAHE contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

        # 4. Adaptive threshold binarization
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 10
        )

        # Save preprocessed image
        stem = Path(img_path).stem
        out_path = str(Path(output_dir) / f"{stem}_preprocessed.png")
        cv2.imwrite(out_path, binary)
        processed_paths.append(out_path)

    return processed_paths


def _fix_page_rotation(image):
    """
    Detect and correct 90-degree page rotation.

    Uses Hough line detection to determine if the dominant text/line direction
    is vertical (indicating the page content is rotated 90 degrees).
    If so, rotates the image to make text horizontal.
    """
    import cv2
    import numpy as np

    edges = cv2.Canny(image, 50, 200, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                            minLineLength=image.shape[1] // 10,
                            maxLineGap=10)

    if lines is None or len(lines) < 5:
        return image

    horizontal_count = 0
    vertical_count = 0
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if angle < 20:
            horizontal_count += 1
        elif angle > 70:
            vertical_count += 1

    # If vertical lines dominate by at least 3:1, page is likely rotated 90 degrees
    if vertical_count > horizontal_count * 3 and vertical_count > 10:
        # Rotate 90 degrees clockwise (most common rotation direction for MTR docs)
        rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        return rotated

    return image


def _deskew(image):
    """
    Correct skew in a grayscale image using Hough line detection.
    """
    import cv2
    import numpy as np

    # Edge detection
    edges = cv2.Canny(image, 50, 200, apertureSize=3)

    # Detect lines
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                            minLineLength=image.shape[1] // 4,
                            maxLineGap=10)

    if lines is None or len(lines) == 0:
        return image

    # Calculate median angle from detected lines
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # Only consider near-horizontal lines (within 15 degrees)
        if abs(angle) < 15:
            angles.append(angle)

    if not angles:
        return image

    median_angle = np.median(angles)

    # Only correct if skew is meaningful (> 0.3 degrees)
    if abs(median_angle) < 0.3:
        return image

    # Rotate to correct skew
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated = cv2.warpAffine(image, rotation_matrix, (w, h),
                             flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REPLICATE)

    return rotated
