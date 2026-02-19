"""
Assembly MTR validation — COC cover sheet parsing and heat number traceability.

Handles assembly packets: a Certificate of Compliance (COC) listing components
with heat numbers, followed by individual MTR documents for each component.
Validates that all COC-listed heat numbers have matching MTRs in the packet.
"""

import base64
import io
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)

# Haiku model for cheap detection/extraction (~$0.001 per call)
HAIKU_MODEL = 'claude-haiku-4-5-20251001'
SONNET_MODEL = 'claude-sonnet-4-5-20250929'

# Max image bytes before compression (same as claude_parser.py)
MAX_IMAGE_BYTES = 3_500_000


@dataclass
class AssemblyComponent:
    """A single component listed on the COC cover sheet."""
    line_item: str = ''
    qty: str = ''
    part_description: str = ''
    part_number: str = ''
    work_order: str = ''
    heat_number: str = ''
    found_on_pages: List[int] = field(default_factory=list)
    status: str = 'MISSING'  # 'FOUND', 'MISSING', 'MANUAL'
    manual_note: str = ''  # user note when manually verified


@dataclass
class AssemblyResult:
    """Result of assembly MTR validation."""
    is_assembly: bool = False
    po_number: str = ''
    customer_part_number: str = ''
    invoice_number: str = ''
    vendor_name: str = ''
    assembly_description: str = ''
    components: List[AssemblyComponent] = field(default_factory=list)
    mtr_heats: Dict[int, str] = field(default_factory=dict)  # page -> heat
    overall_status: str = 'UNKNOWN'  # 'PASS', 'WARN'
    warnings: List[str] = field(default_factory=list)

    @property
    def found_count(self) -> int:
        return sum(1 for c in self.components if c.status == 'FOUND')

    @property
    def missing_count(self) -> int:
        return sum(1 for c in self.components if c.status == 'MISSING')

    @property
    def manual_count(self) -> int:
        return sum(1 for c in self.components if c.status == 'MANUAL')

    @property
    def unique_heats_expected(self) -> int:
        return len(set(_normalize_heat(c.heat_number) for c in self.components
                       if c.heat_number))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for history/report storage."""
        return {
            'is_assembly': self.is_assembly,
            'po_number': self.po_number,
            'customer_part_number': self.customer_part_number,
            'invoice_number': self.invoice_number,
            'vendor_name': self.vendor_name,
            'assembly_description': self.assembly_description,
            'overall_status': self.overall_status,
            'warnings': self.warnings,
            'components': [
                {
                    'line_item': c.line_item,
                    'qty': c.qty,
                    'part_description': c.part_description,
                    'part_number': c.part_number,
                    'heat_number': c.heat_number,
                    'status': c.status,
                    'found_on_pages': c.found_on_pages,
                    'manual_note': c.manual_note,
                }
                for c in self.components
            ],
            'mtr_heats': {str(k): v for k, v in self.mtr_heats.items()},
        }


def _normalize_heat(heat: str) -> str:
    """Normalize a heat number for comparison.

    Strips whitespace, hyphens, dots, leading zeros. Case-insensitive.
    E.g. 'D-191 4127' -> 'D1914127', 'JT-707' -> 'JT707'
    """
    if not heat:
        return ''
    h = heat.strip().upper()
    # Remove hyphens, dots, spaces
    h = re.sub(r'[\s\-\.]+', '', h)
    # Strip leading zeros from numeric suffix (but keep at least 1 digit)
    match = re.match(r'^([A-Z]*)0*(\d+)$', h)
    if match and match.group(2):
        h = match.group(1) + match.group(2)
    return h


def _encode_single_image(image_path: str) -> Optional[Dict[str, Any]]:
    """Encode a single image as a base64 content block for the Anthropic API."""
    p = Path(image_path)
    if not p.exists():
        return None

    raw_bytes = p.read_bytes()

    if len(raw_bytes) > MAX_IMAGE_BYTES:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        if img.width > 2048:
            ratio = 2048 / img.width
            img = img.resize((2048, int(img.height * ratio)), Image.LANCZOS)
        for quality in (85, 70, 50):
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=quality)
            compressed = buf.getvalue()
            if len(compressed) <= MAX_IMAGE_BYTES:
                raw_bytes = compressed
                break
        media_type = 'image/jpeg'
    else:
        suffix = p.suffix.lower()
        media_type = {
            '.png': 'image/png', '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg', '.webp': 'image/webp',
        }.get(suffix, 'image/png')

    data = base64.standard_b64encode(raw_bytes).decode('ascii')
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data}
    }


def _call_model(api_key: str, model: str, content: list,
                max_tokens: int = 4096) -> str:
    """Make a Claude API call and return the text response."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Step 1: Assembly detection
# ---------------------------------------------------------------------------

def detect_assembly(image_paths: List[str], api_key: str) -> bool:
    """Detect if a document is an assembly packet by analyzing page 1.

    Sends the first page image to Haiku with a simple YES/NO question.
    Cost: ~$0.002, ~2s.
    """
    if not image_paths:
        return False

    t0 = time.time()
    img_block = _encode_single_image(image_paths[0])
    if not img_block:
        return False

    content = [
        img_block,
        {"type": "text", "text": (
            "Is this page a Certificate of Compliance (COC) or assembly cover sheet "
            "that lists MULTIPLE different components/parts, each with their OWN "
            "heat numbers or material cert references?\n\n"
            "This is NOT an assembly if it is:\n"
            "- A single Mill Test Certificate/Report (even with multiple pages)\n"
            "- A packing list or shipping document with only ONE material/heat\n"
            "- A test report showing chemistry, mechanical properties, etc.\n\n"
            "Reply ONLY: YES or NO"
        )},
    ]

    try:
        answer = _call_model(api_key, HAIKU_MODEL, content, max_tokens=10)
        result = answer.strip().upper().startswith('YES')
        logger.info("[TIMING] detect_assembly (Haiku): %.1fs -> %s",
                    time.time() - t0, result)
        return result
    except Exception as e:
        logger.warning("Assembly detection failed (%s), assuming single-part", e)
        return False


# ---------------------------------------------------------------------------
# Step 2: COC cover sheet parsing
# ---------------------------------------------------------------------------

COC_PARSE_PROMPT = """\
This is the cover sheet (Certificate of Compliance / packing list) of an assembly \
material test report packet. Extract the following information as JSON.

Extract these top-level fields:
- "po_number": the Purchase Order number
- "customer_part_number": the customer's part number for the assembly
- "invoice_number": invoice number if present
- "vendor_name": the company/vendor name on the certificate
- "assembly_description": brief description of the assembly (e.g. "1-3/16 SM Pulling Tool Assy")

Extract the component table as "components" — an array of objects, one per row:
- "line_item": line/item number
- "qty": quantity
- "part_description": part name/description
- "part_number": the vendor's part number
- "work_order": work order number if listed
- "heat_number": the heat/lot number for that component

IMPORTANT:
- Extract EVERY row from the component table, even if some fields are blank.
- Heat numbers are critical — read them carefully from the table.
- If multiple heat numbers appear for one component, list them comma-separated.
- Return ONLY valid JSON, no markdown fences or explanation.

Example output format:
{
  "po_number": "001628",
  "customer_part_number": "451-118-00-A2000-R0",
  "invoice_number": "B12815-1",
  "vendor_name": "B&T Oilfield Products",
  "assembly_description": "1-3/16 SM Pulling Tool Assy",
  "components": [
    {"line_item": "1", "qty": "1", "part_description": "SM Pulling Tool Core Nut", "part_number": "SMCN-01188-01", "work_order": "149308", "heat_number": "D1914127"},
    ...
  ]
}"""


def parse_coc_cover_sheet(image_paths: List[str], api_key: str) -> AssemblyResult:
    """Parse the COC cover sheet (page 1) to extract component table.

    Uses Sonnet vision for accurate table extraction.
    Cost: ~$0.01, ~5s.
    """
    result = AssemblyResult(is_assembly=True)

    if not image_paths:
        result.warnings.append("No images provided for COC parsing")
        return result

    t0 = time.time()
    img_block = _encode_single_image(image_paths[0])
    if not img_block:
        result.warnings.append("Could not encode cover sheet image")
        return result

    content = [
        img_block,
        {"type": "text", "text": COC_PARSE_PROMPT},
    ]

    try:
        raw = _call_model(api_key, SONNET_MODEL, content)
        logger.info("[TIMING] parse_coc_cover_sheet (Sonnet): %.1fs", time.time() - t0)

        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith('```'):
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)

        import json
        data = json.loads(raw)

        result.po_number = str(data.get('po_number', '')).strip()
        result.customer_part_number = str(data.get('customer_part_number', '')).strip()
        result.invoice_number = str(data.get('invoice_number', '')).strip()
        result.vendor_name = str(data.get('vendor_name', '')).strip()
        result.assembly_description = str(data.get('assembly_description', '')).strip()

        for comp_data in data.get('components', []):
            comp = AssemblyComponent(
                line_item=str(comp_data.get('line_item', '')).strip(),
                qty=str(comp_data.get('qty', '')).strip(),
                part_description=str(comp_data.get('part_description', '')).strip(),
                part_number=str(comp_data.get('part_number', '')).strip(),
                work_order=str(comp_data.get('work_order', '')).strip(),
                heat_number=str(comp_data.get('heat_number', '')).strip(),
            )
            result.components.append(comp)

        logger.info("COC parsed: PO=%s, Part=%s, %d components",
                    result.po_number, result.customer_part_number, len(result.components))

    except Exception as e:
        logger.error("COC parsing failed: %s", e)
        result.warnings.append(f"COC parsing error: {e}")

    return result


# ---------------------------------------------------------------------------
# Step 3: MTR heat number extraction
# ---------------------------------------------------------------------------

HEAT_EXTRACT_PROMPT = """\
This is a page from a material test report (MTR), certificate of test, \
certificate of analysis, or similar material certification document.

What is the HEAT NUMBER (also called lot number, coil ID, or melt number) \
on this document?

Rules:
- Return ONLY the heat number value, nothing else.
- If multiple heat numbers appear, return the PRIMARY one (usually the largest/most prominent).
- If no heat number is found, return "NONE".
- Do NOT include labels like "Heat:" or "Heat Number:" — just the value itself.
- Common heat number formats: alphanumeric codes like "D1914127", "JT707", "K31C", "505544"."""


def extract_mtr_heats(image_paths: List[str], api_key: str,
                      start_page: int = 1) -> Dict[int, str]:
    """Extract heat numbers from MTR pages (pages after the cover sheet).

    Sends each page to Haiku individually for heat number extraction.
    Groups consecutive pages with the same heat as one MTR document.

    Args:
        image_paths: All page images (index 0 = cover sheet).
        api_key: Anthropic API key.
        start_page: Index to start from (1 = skip cover sheet).

    Returns:
        Dict mapping page number (1-indexed) to heat number.
    """
    mtr_heats: Dict[int, str] = {}

    if len(image_paths) <= start_page:
        return mtr_heats

    t0 = time.time()
    pages_to_scan = image_paths[start_page:]

    for i, img_path in enumerate(pages_to_scan):
        page_num = i + start_page + 1  # 1-indexed, accounting for cover sheet

        img_block = _encode_single_image(img_path)
        if not img_block:
            continue

        content = [
            img_block,
            {"type": "text", "text": HEAT_EXTRACT_PROMPT},
        ]

        try:
            answer = _call_model(api_key, HAIKU_MODEL, content, max_tokens=50)
            heat = answer.strip()
            if heat and heat.upper() != 'NONE':
                # Clean up common artifacts
                heat = re.sub(r'^["\']|["\']$', '', heat)  # strip quotes
                heat = heat.strip()
                mtr_heats[page_num] = heat
                logger.debug("Page %d heat: %s", page_num, heat)
            else:
                logger.debug("Page %d: no heat number found", page_num)
        except Exception as e:
            logger.warning("Heat extraction failed for page %d: %s", page_num, e)

    elapsed = time.time() - t0
    logger.info("[TIMING] extract_mtr_heats (Haiku, %d pages): %.1fs (%.1fs/page)",
                len(pages_to_scan), elapsed,
                elapsed / len(pages_to_scan) if pages_to_scan else 0)
    logger.info("Found heats on %d/%d pages: %s",
                len(mtr_heats), len(pages_to_scan),
                {k: v for k, v in sorted(mtr_heats.items())})

    return mtr_heats


# ---------------------------------------------------------------------------
# Step 4: Cross-reference
# ---------------------------------------------------------------------------

def _fuzzy_heat_match(needle: str, haystack: Dict[str, List[int]]
                      ) -> Optional[Tuple[str, List[int]]]:
    """Try common OCR character substitutions to find a fuzzy match.

    Handles confusions: T<->1, O<->0, I<->1, l<->1, S<->5, B<->8.
    Returns (matched_key, pages) or None.
    """
    # Character substitution pairs (bidirectional)
    SUBS = [('T', '1'), ('O', '0'), ('I', '1'), ('L', '1'), ('S', '5'), ('B', '8')]

    def _variants(s: str) -> set:
        results = {s}
        for old, new in SUBS:
            # Forward substitution
            if old in s:
                results.add(s.replace(old, new))
            if new in s:
                results.add(s.replace(new, old))
            # Also try per-character (for multiple occurrences)
            for i, ch in enumerate(s):
                if ch == old:
                    results.add(s[:i] + new + s[i+1:])
                elif ch == new:
                    results.add(s[:i] + old + s[i+1:])
        return results

    for variant in _variants(needle):
        if variant in haystack:
            return (variant, haystack[variant])
    return None


def cross_reference(assembly: AssemblyResult) -> AssemblyResult:
    """Match COC component heat numbers against extracted MTR heats.

    Handles shared heats (one MTR satisfying multiple components).
    Uses exact match first, then fuzzy OCR character substitution.
    Updates component statuses and overall_status.
    """
    # Build lookup: normalized heat -> list of pages
    heat_to_pages: Dict[str, List[int]] = {}
    for page, heat in assembly.mtr_heats.items():
        norm = _normalize_heat(heat)
        if norm:
            heat_to_pages.setdefault(norm, []).append(page)

    # Match each component
    for comp in assembly.components:
        if not comp.heat_number:
            comp.status = 'MISSING'
            assembly.warnings.append(
                f"Component '{comp.part_description}' has no heat number on COC")
            continue

        # Handle comma-separated heat numbers (multiple heats per component)
        heats = [h.strip() for h in comp.heat_number.split(',') if h.strip()]
        all_found = True
        pages = []

        for heat in heats:
            norm = _normalize_heat(heat)
            if norm in heat_to_pages:
                pages.extend(heat_to_pages[norm])
            else:
                # Try fuzzy match for OCR character confusion (T/1, O/0, etc.)
                fuzzy = _fuzzy_heat_match(norm, heat_to_pages)
                if fuzzy:
                    matched_key, matched_pages = fuzzy
                    pages.extend(matched_pages)
                    logger.info("Fuzzy heat match: COC '%s' (%s) ~ MTR '%s' (pages %s)",
                                heat, norm, matched_key, matched_pages)
                else:
                    all_found = False

        if all_found and pages:
            comp.status = 'FOUND'
            comp.found_on_pages = sorted(set(pages))
        elif comp.status != 'MANUAL':
            comp.status = 'MISSING'

    # Calculate overall status
    missing = [c for c in assembly.components if c.status == 'MISSING']
    if not missing:
        assembly.overall_status = 'PASS'
    else:
        assembly.overall_status = 'WARN'
        for c in missing:
            assembly.warnings.append(
                f"Heat '{c.heat_number}' not found for: {c.part_description} ({c.part_number})")

    found = sum(1 for c in assembly.components if c.status in ('FOUND', 'MANUAL'))
    total = len(assembly.components)
    logger.info("Cross-reference: %d/%d components matched, status=%s",
                found, total, assembly.overall_status)

    return assembly


# ---------------------------------------------------------------------------
# Full assembly pipeline
# ---------------------------------------------------------------------------

def process_assembly(
    image_paths: List[str],
    api_key: str,
    on_progress: Optional[callable] = None,
) -> AssemblyResult:
    """Run the full assembly validation pipeline.

    Steps:
    1. Parse COC cover sheet (Sonnet)
    2. Extract heat numbers from MTR pages (Haiku)
    3. Cross-reference heats

    Args:
        image_paths: All page images (index 0 = cover sheet).
        api_key: Anthropic API key.
        on_progress: Optional callback(step: str, pct: float).

    Returns:
        AssemblyResult with traceability data.
    """
    def _progress(step: str, pct: float):
        logger.info("Assembly [%.0f%%] %s", pct * 100, step)
        if on_progress:
            on_progress(step, pct)

    t0 = time.time()

    # Step 1: Parse COC cover sheet
    _progress("Parsing COC cover sheet...", 0.10)
    result = parse_coc_cover_sheet(image_paths, api_key)

    if not result.components:
        result.warnings.append("No components found on cover sheet")
        result.overall_status = 'WARN'
        return result

    # Step 2: Extract heat numbers from MTR pages
    _progress("Extracting heat numbers from MTR pages...", 0.30)
    result.mtr_heats = extract_mtr_heats(image_paths, api_key, start_page=1)

    # Step 3: Cross-reference
    _progress("Cross-referencing heats...", 0.80)
    result = cross_reference(result)

    elapsed = time.time() - t0
    logger.info("[TIMING] process_assembly TOTAL: %.1fs (%d components, %d MTR pages)",
                elapsed, len(result.components), len(result.mtr_heats))
    _progress("Assembly validation complete.", 1.0)

    return result


def mark_heat_manual(assembly: AssemblyResult, part_number: str,
                     note: str = '') -> AssemblyResult:
    """Mark a component's heat as manually verified (externally provided).

    Used when an MTR is missing from the packet but the user has verified
    the heat number through other means.
    """
    for comp in assembly.components:
        if comp.part_number == part_number and comp.status == 'MISSING':
            comp.status = 'MANUAL'
            comp.manual_note = note or 'Externally verified'
            logger.info("Marked %s (%s) as manually verified: %s",
                        comp.part_number, comp.heat_number, note)
            break

    # Recalculate overall status
    missing = [c for c in assembly.components if c.status == 'MISSING']
    assembly.overall_status = 'PASS' if not missing else 'WARN'

    return assembly
