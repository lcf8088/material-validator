"""
Page relevance scoring for MTR vision pipeline.

Scores each page's OCR text for MTR-relevant keywords to select
only the most useful pages for image-based Claude extraction.
All OCR text is still sent as cheap text tokens — this only filters
which pages get expensive image slots.
"""

import re
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-compiled patterns
# ---------------------------------------------------------------------------

# Chemistry elements commonly found in MTR chemistry tables.
# Each must match as a whole word to avoid false positives ("C" in "Condition").
_ELEMENTS = [
    "C", "Mn", "P", "S", "Si", "Cr", "Ni", "Mo", "Cu", "V", "Nb", "Cb",
    "Ti", "Al", "N", "B", "W", "Co", "Sn", "Ta", "Pb", "Zr", "Ca", "Ce",
    "Fe", "As", "Sb", "Se", "Bi", "Te", "O", "H",
]
_ELEMENT_PATTERNS = [re.compile(rf"\b{e}\b") for e in _ELEMENTS]

# Minimum distinct elements before awarding full chemistry weight
_ELEMENT_THRESHOLD = 3

# Mechanical property keywords — high specificity (English + German + French)
_MECHANICAL_KW = [
    "yield", "tensile", "elongation", "hardness", "charpy", "impact",
    "reduction of area", "proof stress", "breaking load", "brinell",
    "rockwell", "hrc", "hrb", "ksi", "mpa",
    # German
    "zugversuch", "streckgrenze", "zugfestigkeit", "dehnung",
    "brucheinschn", "härte", "kerbschlag", "schlagbiege",
    # French
    "traction", "dureté", "résilience", "allongement",
    # Common multilingual table headers
    "rp0.2", "rp0,2", "rm [",
]

# Header / identity keywords (English + German + French)
_HEADER_KW = [
    "heat number", "heat no", "grade", "astm", "specification", "material",
    "certificate", "mill test", "test report", "chemical composition",
    "mechanical properties", "chemical analysis", "heat treat",
    "normalizing", "quench", "temper", "anneal", "austenitizing",
    # German
    "schmelzen-nr", "schmelze", "werkstoff", "prüfzeugnis", "zeugnis",
    "chemische zusammensetzung", "abnahmeprüfzeugnis",
    # French
    "certificat", "composition chimique", "no.de coulée",
]

# Filler / boilerplate keywords — strong negative signal
_FILLER_KW = [
    "terms and conditions", "warranty", "disclaimer", "limitation of liability",
    "governing law", "arbitration", "indemnification", "force majeure",
    "confidential", "proprietary", "quality policy", "iso 9001",
    "accreditation", "this document may not be reproduced",
]

# Page-break marker format emitted by paddle_ocr.py line 81
_PAGE_MARKER_RE = re.compile(r"\n--- Page (\d+) ---\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def split_ocr_by_page(ocr_text: str) -> Dict[int, str]:
    """Split OCR text on ``--- Page N ---`` markers.

    Returns ``{1: "page 1 text", 2: "page 2 text", ...}``.
    Single-page docs (no markers) return ``{1: ocr_text}``.
    """
    if not ocr_text:
        return {1: ""}

    parts = _PAGE_MARKER_RE.split(ocr_text)

    # No markers found → single page
    if len(parts) == 1:
        return {1: ocr_text}

    pages: Dict[int, str] = {}
    # parts alternates: [pre-marker-text, page_num, page_text, page_num, ...]
    # First element is text before the first marker (usually empty or whitespace)
    for i in range(1, len(parts), 2):
        page_num = int(parts[i])
        page_text = parts[i + 1] if i + 1 < len(parts) else ""
        pages[page_num] = page_text

    return pages


def score_page(page_text: str, page_num: int, total_pages: int) -> float:
    """Score a single page for MTR relevance.

    Higher scores → more likely to contain useful cert data.
    """
    text_lower = page_text.lower()
    score = 0.0

    # --- Chemistry elements ---
    distinct_elements = sum(1 for pat in _ELEMENT_PATTERNS if pat.search(page_text))
    if distinct_elements >= _ELEMENT_THRESHOLD:
        score += distinct_elements * 3.0
    else:
        score += distinct_elements * 0.5

    # --- Mechanical keywords ---
    for kw in _MECHANICAL_KW:
        if kw in text_lower:
            score += 4.0

    # --- Header keywords ---
    for kw in _HEADER_KW:
        if kw in text_lower:
            score += 2.0

    # --- Filler penalty ---
    for kw in _FILLER_KW:
        if kw in text_lower:
            score -= 5.0

    # --- Numeric density ---
    if page_text:
        digit_count = sum(1 for ch in page_text if ch.isdigit())
        digit_ratio = digit_count / len(page_text)
        score += min(5.0, digit_ratio * 50)

    # --- Page position tiebreaker (favor early pages) ---
    if total_pages > 1:
        score += 2.0 * (1 - (page_num - 1) / (total_pages - 1))
    else:
        score += 2.0

    return score


def select_relevant_pages(
    ocr_text: str,
    total_pages: int,
    max_pages: int = 5,
    min_pages: int = 1,
    score_threshold: float = 5.0,
) -> List[int]:
    """Select the most MTR-relevant page indices for image encoding.

    Returns **0-based indices** sorted in document order, suitable for
    indexing into an ``image_paths[]`` list.
    """
    # Short-circuit: single page
    if total_pages <= 1:
        return [0]

    pages = split_ocr_by_page(ocr_text)

    # Score every page
    scored: List[tuple] = []
    for page_num, text in pages.items():
        idx = page_num - 1  # 0-based
        if idx < 0 or idx >= total_pages:
            continue
        s = score_page(text, page_num, total_pages)
        scored.append((idx, s))
        logger.debug("Page %d score: %.1f", page_num, s)

    if not scored:
        return [0]

    # Sort by score descending, take top max_pages above threshold
    scored.sort(key=lambda x: x[1], reverse=True)
    selected = [idx for idx, s in scored[:max_pages] if s >= score_threshold]

    # Fallback: ensure at least min_pages
    if len(selected) < min_pages:
        selected = [idx for idx, _ in scored[:min_pages]]

    # Return in document order
    selected.sort()
    return selected
