"""
Image preprocessing for scanned MTR documents.

Detects digital-native vs scanned PDFs and applies preprocessing
pipeline (de-skew, contrast enhancement, binarization) to improve
OCR accuracy on scanned documents.
"""

import tempfile
from pathlib import Path
from typing import List


def is_digital_native(pdf_path: str) -> bool:
    """
    Detect whether a PDF is digital-native (has a text layer) or scanned.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        True if the PDF has extractable text (digital-native), False if scanned.
    """
    import fitz

    doc = fitz.open(pdf_path)
    total_chars = 0
    for page in doc:
        total_chars += len(page.get_text().strip())
    doc.close()

    # If we extracted a reasonable amount of text, it's digital-native
    return total_chars > 50


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
