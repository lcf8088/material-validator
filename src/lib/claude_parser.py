"""
Claude structured parser for MTR data extraction.

Takes raw OCR text output from PaddleOCR and page images, sends them to Claude
in a multimodal request for structured extraction with optional spec context.
Returns parsed JSON matching the existing MTR data format.
"""

import base64
import io
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from PIL import Image

from .page_relevance import select_relevant_pages

import re

logger = logging.getLogger(__name__)


def _strip_chemistry_table_from_ocr(ocr_text: str) -> str:
    """Strip garbled chemistry table data from OCR text.

    PaddleOCR frequently garbles tabular chemistry data — headers merge,
    values split across lines, column alignment is destroyed. This misleads
    Claude into column-shift errors even when images are provided.

    Replaces the chemistry table section with a marker telling Claude to
    read chemistry exclusively from the document images.
    """
    lines = ocr_text.split('\n')
    result = []
    in_chem_section = False
    stripped_count = 0

    # Patterns that signal the start of a chemistry table
    chem_start_re = re.compile(
        r'CHEM|COMPOSITION\s*\(%?\)|CHEMICAL|ANALYSE|ANALYS',
        re.IGNORECASE,
    )
    # Patterns that signal the end of a chemistry section
    chem_end_re = re.compile(
        r'TENSILE|MECHANICAL|HARDNESS|IMPACT|CHARPY|HEAT\s+TREAT|'
        r'GRAIN\s+SIZE|NOTES|REMARKS|---\s*Page',
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.strip()
        if not in_chem_section:
            if chem_start_re.search(stripped):
                in_chem_section = True
                result.append("[CHEMISTRY TABLE PRESENT — read all chemistry values from the document images, not from OCR text]")
                stripped_count += 1
                continue
            result.append(line)
        else:
            if chem_end_re.search(stripped) or (stripped.startswith('---') and 'Page' in stripped):
                in_chem_section = False
                result.append(line)
            else:
                stripped_count += 1
                # Skip this garbled chemistry line

    if stripped_count > 0:
        logger.info("Stripped %d garbled chemistry lines from OCR text", stripped_count)

    return '\n'.join(result)


# Model ID mapping
MODEL_IDS = {
    'sonnet': 'claude-sonnet-4-6',
    'opus': 'claude-opus-4-6',
}

# Max pages to send as images (typical MTR is 1-4 pages)
MAX_IMAGE_PAGES = 5

# Max raw image bytes before compression (3.5MB raw → ~4.7MB base64, under 5MB API limit)
MAX_IMAGE_BYTES = 3_500_000

# Structured extraction prompt for Claude
EXTRACTION_PROMPT = """\
You are an expert at reading Material Test Reports (MTRs) / Mill Certifications.

You are viewing the actual document images alongside OCR text extracted from them.
Use the IMAGES as the PRIMARY source — for layout, table structure, column-to-header mapping, AND reading values from tables.
Use the OCR TEXT as a secondary reference for text values outside of tables (heat numbers, supplier names, etc.).
IMPORTANT: OCR frequently garbles tabular data — headers merge together, values split across lines, and column alignment is lost. For chemistry and mechanical tables, ALWAYS trust what you see in the images over the OCR text. Read table values directly from the images, matching each value to its column header by visual position.

Parse the document into structured JSON.

**RULES**:
- Extract ONLY what is explicitly stated in the document. Do not guess or infer values.
- Chemistry values are percentages by weight (e.g., 0.04 means 0.04%).
- Stress values: note whether they are in ksi, MPa, or psi. Report the unit exactly as shown on the document.
- If a field is not present in the document, use null.
- For po_number: the customer PO always starts with "PO" (e.g., PO001533). Ignore supplier order numbers, internal references, or any number that does not start with "PO".

**MECHANICAL AVERAGING**:
- For multiple specimens tested under the SAME condition, report the average for mechanical properties.
- If the document has separate columns for different conditions (e.g., "Before Heat Treat" / "After Heat Treat", "As Shipped" / "Capabilities"), always use the FINAL condition values (After Heat Treat, As Shipped, Final). Never average across different conditions.
- Reduction of Area must come from the tensile test results, not from wrap test, bend test, or other test sections.

**CHEMISTRY EXTRACTION**:
- **CRITICAL — WHICH ROW TO EXTRACT**: Chemistry tables often have MULTIPLE rows: "Min." (minimum spec limit), "Max." (maximum spec limit), and "Cer." / "Cert." / "Actual" / "Heat Analysis" / "Ladle" / "Product" (the ACTUAL measured values for this specific heat). You MUST extract ONLY the ACTUAL/CERTIFICATE row. NEVER extract the Min or Max rows — those are specification limits, not measured values. The certificate row is usually the last data row, often marked with check marks (✓) or ticks. If the table has rows labeled "Min.", "Max.", "Cer." — extract the "Cer." row. If rows are labeled "R" (requirement), "L" (ladle), "P" (product) — extract "P" or "L", not "R". If both Ladle and Product rows exist, prefer Product.
- Element symbols should be standard (C, Mn, P, S, Si, Cr, Ni, Mo, Cu, V, Nb, Ti, Al, N, B, W, Co, Sn, Ta, Fe, Pb, Zn, Se, Ca, Ce, La, Mg, Zr).
- Cb (Columbium) is the old name for Niobium. Always output as Nb, never Cb. If the document shows "Cb" followed by a numeric value, map that value to the Nb key in the output.
- S (Sulfur) and Sn (Tin) are different elements. S is typically < 0.05% in steels. Sn is typically < 0.03%. Do not confuse them.
- If an element cell is blank, empty, or not listed on the cert, output null for that element. Do NOT use an adjacent cell's value. Only include elements that are explicitly labeled and have a value printed on the document.
- Use the document images to identify table structure: match chemistry headers to their corresponding values by visual column alignment. This is more reliable than the raw OCR text for column-to-element mapping.
- **COLUMN ALIGNMENT IS CRITICAL**: Count the number of column headers and verify the same number of data values per row. Footnote markers like *1, *2, *3, *4 next to column headers are NOT extra columns — they are superscript annotations. Row labels like R (requirement), L (ladle), P (product) at the start of a row are NOT chemistry values. Do not skip or shift columns. If the header row is [C, Si, Mn, P, S, Cr, Ni, Mo, Ti, V, N] then the first numeric value in a data row corresponds to C, the second to Si, etc. Verify your extraction: if C > 0.50% or Mn < 0.10% for a stainless steel, you likely have a column shift error.
- For values with less-than qualifiers (e.g., "<0.002", "<0.01"), report the number without the "<" in the chemistry dict, and add the qualifier to the "chemistry_qualifiers" dict (e.g., {{"Ta": "<"}}).
- **COMPACT INTEGER NOTATION**: Some MTRs display chemistry as integers with footnote multipliers instead of decimal percentages. Look for footnotes near the bottom of the chemistry table such as "*2:X10", "*3:X1000", "*4:X10000", "OTHER:X100". These tell you how to convert each column's integer to a percentage:
  - OTHER or X100 or unmarked: divide by 100 (e.g., C=1 → 0.01%, Si=22 → 0.22%, Mn=40 → 0.40%).
  - *2 or X10: divide by 10 (e.g., Cr=120 → 12.0%, Ni=56 → 5.6%, Mo=19 → 1.9%).
  - *3 or X1000: divide by 1000 (e.g., P=13 → 0.013%, S=0 → 0.000%).
  - *4 or X10000: divide by 10000 (e.g., N=77 → 0.0077%).
  When you see integer-only chemistry values (no decimal points) with footnote markers on column headers, you MUST apply the correct scale factor and output the final decimal percentage. Verify your conversion makes physical sense (e.g., C is typically 0.01-0.50%, Cr in stainless steels is 11-18%, Ni is typically 0-10%).

**TEMPERATURE EXTRACTION**:
- For temper_temperature, report the numeric value AND the unit separately. Use "C" for Celsius, "F" for Fahrenheit.
- Heat treatment may be described as a multi-step sequence (e.g., "970°C 1HR + 225°C 2HR + 715°C 2HR"). Extract the TEMPERING step specifically. Look for keywords: temper, tempering, anlassen (German), revenu (French). The tempering step is typically the last or second-to-last step, performed at a lower temperature than the austenitizing/hardening step.
- For charpy_temperature, report the numeric value AND the unit separately. Charpy impact test temperatures are frequently NEGATIVE (e.g., -40°C, -20°F, -46°C). Always preserve the negative sign. Common Charpy test temperatures are: -196°C, -101°C, -75°C, -50°C, -46°C, -40°C, -29°C, -20°C, -10°C, 0°C. OCR may misread a minus sign as a digit or drop it entirely. If the document says something like "10°C" but the context suggests a sub-zero test (e.g., impact testing, low-temperature toughness), double-check for a missing minus sign. Report the exact value and unit as printed on the document.

**TABLE LOCATIONS**:
- For "table_regions", report which page (1-indexed) contains the chemistry table, mechanical properties table (tensile test), and hardness table, and their approximate vertical position as a percentage of the page height (0=top, 100=bottom).
- If hardness results are on a DIFFERENT page from the tensile test, report the hardness location separately. If they are on the same page as the mechanical/tensile section, you may omit the hardness key.
- For example, if the chemistry table starts 25% from the top and ends 50% from the top on page 1: {{"page": 1, "top_pct": 25, "bottom_pct": 50}}.

**MULTI-DOCUMENT PDFs**:
- This PDF may contain multiple documents from different companies (packing slips, distributor certs, mill certs). Always prefer the ORIGINAL MILL TEST REPORT as the authoritative source for chemistry and mechanical properties. If different pages show conflicting chemistry, use the mill's values, not the distributor's.

**OCR TEXT** (use for precise character values):
{ocr_text}

{spec_context}

**OUTPUT** (return ONLY valid JSON, no markdown fences, no explanation):
{{
  "heat_number": "string",
  "material_grade": "string",
  "uns": "string or null",
  "supplier": "string or null",
  "customer": "string or null",
  "po_number": "string or null",
  "product_form": "string or null",
  "size": "string or null",
  "condition": "string or null",
  "chemistry": {{
    "C": 0.00,
    "Mn": 0.00
  }},
  "chemistry_qualifiers": {{}},
  "mechanical": {{
    "yield_strength": 0.0,
    "yield_strength_unit": "ksi",
    "tensile_strength": 0.0,
    "tensile_strength_unit": "ksi",
    "elongation": 0.0,
    "reduction_of_area": 0.0,
    "hardness_hbw": null,
    "hardness_hrc": null
  }},
  "charpy_impact": null,
  "charpy_temperature": null,
  "charpy_temperature_unit": null,
  "temper_temperature": null,
  "temper_temperature_unit": null,
  "nace_compliant": null,
  "grain_size": null,
  "table_regions": {{
    "chemistry": {{"page": 1, "top_pct": 0, "bottom_pct": 100}},
    "mechanical": {{"page": 1, "top_pct": 0, "bottom_pct": 100}},
    "hardness": null
  }}
}}
"""

COMPLIANCE_CHECK_ADDENDUM = """\
**SPEC CONTEXT** (use this to flag any out-of-spec values):
The material should comply with specification: {spec_id}
Requirements:
{spec_requirements}

After extracting the data, also include a "compliance_flags" array listing
any values that appear to be outside the spec limits. Format:
"compliance_flags": [
  {{"field": "Cr", "value": 0.75, "spec_min": 0.80, "spec_max": 1.10, "status": "BELOW_MIN"}}
]
If all values appear within spec, use an empty array: "compliance_flags": []
"""


def _build_spec_context(spec_yaml: Optional[str], spec_id: Optional[str] = None) -> str:
    """Build spec context section for the prompt."""
    if not spec_yaml:
        return ""

    return COMPLIANCE_CHECK_ADDENDUM.format(
        spec_id=spec_id or "unknown",
        spec_requirements=spec_yaml
    )


def _format_spec_as_text(spec: Dict[str, Any]) -> str:
    """Format a spec dict as readable text for the prompt."""
    lines = []

    if spec.get('chemistry'):
        lines.append("Chemistry limits:")
        for elem, limits in spec['chemistry'].items():
            min_val = limits.get('min', '-')
            max_val = limits.get('max', '-')
            lines.append(f"  {elem}: min={min_val}, max={max_val}")

    if spec.get('mechanical'):
        lines.append("Mechanical limits:")
        for prop, limits in spec['mechanical'].items():
            min_val = limits.get('min', '-')
            max_val = limits.get('max', '-')
            unit = limits.get('unit', '')
            lines.append(f"  {prop}: min={min_val}, max={max_val} {unit}")

    if spec.get('special_requirements'):
        lines.append("Special requirements:")
        for req in spec['special_requirements']:
            lines.append(f"  - {req.get('type', '')}: {req.get('note', '')}")

    return "\n".join(lines)


def _compress_image(raw_bytes: bytes, filename: str) -> tuple[bytes, str]:
    """Compress an oversized image to fit under MAX_IMAGE_BYTES.

    Strategy: resize if wider than 2048px, then convert to JPEG with
    decreasing quality until it fits.

    Returns:
        (image_bytes, media_type) tuple.
    """
    img = Image.open(io.BytesIO(raw_bytes))
    if img.mode in ('RGBA', 'P', 'LA'):
        img = img.convert('RGB')

    # Resize if wider than 2048px
    if img.width > 2048:
        ratio = 2048 / img.width
        new_size = (2048, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
        logger.info("Resized %s: %dx%d → %dx%d",
                     filename, img.width, img.height, *new_size)

    for quality in (85, 70, 50):
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality)
        compressed = buf.getvalue()
        if len(compressed) <= MAX_IMAGE_BYTES:
            logger.info("Compressed %s: %s → %s (JPEG q=%d)",
                         filename,
                         _fmt_size(len(raw_bytes)),
                         _fmt_size(len(compressed)),
                         quality)
            return compressed, 'image/jpeg'

    # Last resort: already at q=50, return it anyway (best effort)
    logger.warning("Image %s still %s after max compression",
                    filename, _fmt_size(len(compressed)))
    return compressed, 'image/jpeg'


def _fmt_size(n: int) -> str:
    """Format byte count as human-readable string."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}MB"
    return f"{n / 1_000:.0f}KB"


def _encode_images(image_paths: List[str]) -> List[Dict[str, Any]]:
    """Encode page images as base64 content blocks for the Anthropic API.

    Images exceeding MAX_IMAGE_BYTES are compressed to JPEG to stay under
    the 5MB per-image API limit.

    Args:
        image_paths: List of image file paths (PNG).

    Returns:
        List of image content blocks ready for the messages API.
    """
    blocks = []
    for path in image_paths[:MAX_IMAGE_PAGES]:
        p = Path(path)
        if not p.exists():
            logger.warning("Image not found, skipping: %s", path)
            continue

        raw_bytes = p.read_bytes()
        original_size = len(raw_bytes)

        if original_size > MAX_IMAGE_BYTES:
            image_bytes, media_type = _compress_image(raw_bytes, p.name)
        else:
            image_bytes = raw_bytes
            suffix = p.suffix.lower()
            media_type = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.webp': 'image/webp',
                '.gif': 'image/gif',
            }.get(suffix, 'image/png')

        data = base64.standard_b64encode(image_bytes).decode('ascii')
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": data,
            }
        })
    return blocks


OPUS_TABLE_PROMPT = """\
Read the heat number, chemistry table, and mechanical properties from this Mill Test Certificate.

**HEAT NUMBER**:
- Find the heat number (also called "Heat No.", "Heat #", "Schmelze", "Charge"). It uniquely identifies the melt/batch.

**CHEMISTRY TABLE**:
- Tables often have rows: Min. (spec minimum), Max. (spec maximum), Cer./Cert./Actual/Heat/Ladle/Product (measured values).
- Extract ONLY the ACTUAL/CERTIFICATE row — NEVER the Min or Max rows.
- If rows are labeled Min., Max., Cer. — extract the Cer. row.
- If rows are labeled R, L, P — extract P (product) or L (ladle), not R.
- Element symbols: C, Mn, P, S, Si, Cr, Ni, Mo, Cu, V, Nb, Ti, Al, N, B, W, Co, Sn, Ta, Fe.
- Cb = Nb (columbium = niobium). S ≠ Sn.
- Values with "<" qualifiers: report number without "<" in chemistry, add qualifier to chemistry_qualifiers.
- **COLUMN ALIGNMENT IS CRITICAL**: Count the number of column headers and verify the same number of data values per row. Footnote markers like *1, *2, *3, *4 next to column headers are NOT extra columns — they are superscript annotations. Row labels like R, L, P at the start of a row are NOT chemistry values.
- **COMPACT INTEGER NOTATION**: Some MTRs (especially Japanese mills like Nippon Steel, JFE, Sumitomo) display chemistry as integers with footnote multipliers instead of decimal percentages. Look for footnotes near the bottom of the chemistry table such as "*2:X10", "*3:X1000", "*4:X10000", "OTHER:X100". These tell you how to convert each column's integer to a percentage:
  - OTHER or X100 or unmarked columns: divide by 100 (e.g., C=19 → 0.19%, Si=25 → 0.25%, Mn=52 → 0.52%).
  - *2 or X10: divide by 10 (e.g., Cr=129 → 12.9%, Ni=56 → 5.6%).
  - *3 or X1000: divide by 1000 (e.g., P=13 → 0.013%, S=1 → 0.001%).
  - *4 or X10000: divide by 10000 (e.g., N=77 → 0.0077%).
  Each column header may have a different footnote marker (*2, *3, etc.) — apply the CORRECT multiplier for EACH column individually. Verify your conversion makes physical sense (e.g., C is typically 0.01-0.50%, Cr in 13CR steels is 12-14%, Ni is typically 0-10%).

**MECHANICAL PROPERTIES**:
- For multiple specimens under the SAME condition, report averages.
- If separate conditions exist (Before/After Heat Treat), use FINAL condition values only.
- Stress values: note whether they are in ksi, MPa, or psi. Report the unit exactly as shown.
- **COLUMN ALIGNMENT**: Tensile test tables have columns like YS (yield), TS (tensile), EL (elongation), RA (reduction of area). Read each column header carefully and match values by visual position. YS is ALWAYS less than TS for steel — if your extracted yield > tensile, you have a column shift error.
- **FOOTNOTE DISAMBIGUATION**: On some certs (e.g., Nippon Steel), the SAME footnote marker (like *3) has DIFFERENT meanings in different table sections. In chemistry, *3 may mean "multiply by X1000". In tensile test, *3 may mean "unit is ksi". Do NOT apply chemistry multipliers to mechanical property values — mechanical values are already in their stated units (ksi, MPa, %, etc.).

Return ONLY valid JSON:
{
  "heat_number": "string",
  "chemistry": {"C": 0.00, "Mn": 0.00},
  "chemistry_qualifiers": {},
  "mechanical": {
    "yield_strength": 0.0,
    "yield_strength_unit": "ksi",
    "tensile_strength": 0.0,
    "tensile_strength_unit": "ksi",
    "elongation": 0.0,
    "reduction_of_area": 0.0,
    "hardness_hbw": null,
    "hardness_hrc": null
  }
}
"""


def crop_table_regions(
    image_paths: List[str],
    table_regions: Dict[str, Any],
) -> List[str]:
    """Crop chemistry and mechanical table regions from page images.

    Uses the table_regions dict from Sonnet extraction to cut out only
    the relevant portions of each page, dramatically reducing the image
    area (and tokens) sent to Opus.

    Args:
        image_paths: Full page image paths.
        table_regions: {"chemistry": {"page": 1, "top_pct": 25, "bottom_pct": 50}, ...}

    Returns:
        List of cropped image paths (saved as PNGs in temp dir).
    """
    import tempfile
    from PIL import Image as PILImage

    if not table_regions or not image_paths:
        return image_paths[:1]  # fallback: just page 1

    output_dir = Path(tempfile.gettempdir()) / 'mtr_table_crops'
    output_dir.mkdir(exist_ok=True)

    crops = []
    # Collect unique page regions and merge overlapping ones
    page_regions: Dict[int, list] = {}
    for table_name in ('chemistry', 'mechanical', 'hardness'):
        region = table_regions.get(table_name)
        if not region or not isinstance(region, dict):
            continue
        page_idx = int(region.get('page', 1)) - 1  # 0-indexed
        top_pct = max(0, float(region.get('top_pct', 0)) - 15)  # 15% padding
        bottom_pct = min(100, float(region.get('bottom_pct', 100)) + 15)
        if page_idx not in page_regions:
            page_regions[page_idx] = []
        page_regions[page_idx].append((top_pct, bottom_pct))

    if not page_regions:
        return image_paths[:1]

    for page_idx, regions in sorted(page_regions.items()):
        if page_idx >= len(image_paths):
            continue

        img = PILImage.open(image_paths[page_idx])
        w, h = img.size

        # Merge overlapping regions on the same page
        regions.sort()
        merged = [regions[0]]
        for top, bottom in regions[1:]:
            if top <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], bottom))
            else:
                merged.append((top, bottom))

        for i, (top_pct, bottom_pct) in enumerate(merged):
            # If merged region covers >60% of the page, send the full page
            # instead of cropping — avoids cutting off adjacent table sections
            if bottom_pct - top_pct > 60:
                crops.append(image_paths[page_idx])
                logger.info("Table regions span %d%% of p%d — sending full page",
                             int(bottom_pct - top_pct), page_idx + 1)
                continue

            y_top = int(h * top_pct / 100)
            y_bottom = int(h * bottom_pct / 100)
            cropped = img.crop((0, y_top, w, y_bottom))

            crop_path = output_dir / f"table_crop_p{page_idx+1}_{i}.png"
            cropped.save(str(crop_path))
            crops.append(str(crop_path))
            logger.info("Cropped table region p%d: %d%%-%d%% (%dx%d -> %dx%d)",
                         page_idx + 1, top_pct, bottom_pct, w, h, w, y_bottom - y_top)

    return crops if crops else image_paths[:1]


def extract_tables_with_opus(
    image_paths: List[str],
    api_key: str,
) -> Optional[Dict[str, Any]]:
    """Focused Opus call to extract ONLY chemistry and mechanical tables.

    Uses a minimal prompt — no OCR text, no spec context — to keep token
    count (and cost) low.  Opus is much more accurate than Sonnet at reading
    dense multi-row chemistry tables.

    Returns dict with 'chemistry', 'chemistry_qualifiers', 'mechanical' keys,
    or None on failure.
    """
    import time as _time
    import anthropic

    if not image_paths:
        return None

    t0 = _time.time()

    # Encode images (reuse existing helper)
    image_blocks = _encode_images(image_paths[:MAX_IMAGE_PAGES])
    if not image_blocks:
        return None

    content: list = list(image_blocks)
    content.append({"type": "text", "text": OPUS_TABLE_PROMPT})

    client = anthropic.Anthropic(api_key=api_key)
    model_id = MODEL_IDS['opus']

    logger.info("[TIMING] Opus table extraction — %d images...", len(image_blocks))
    message = client.messages.create(
        model=model_id,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )
    api_elapsed = _time.time() - t0

    usage = getattr(message, 'usage', None)
    if usage:
        logger.info("[TIMING] Opus table call: %.1fs | %d in + %d out tokens",
                     api_elapsed,
                     getattr(usage, 'input_tokens', 0),
                     getattr(usage, 'output_tokens', 0))
    else:
        logger.info("[TIMING] Opus table call: %.1fs", api_elapsed)

    result = _parse_response(message.content[0].text)
    if result.get('_extraction_status') != 'success':
        logger.warning("Opus table extraction failed to parse")
        return None

    return result


def _resolve_model(model: str) -> str:
    """Resolve a short model name to a full Anthropic model ID."""
    return MODEL_IDS.get(model, MODEL_IDS['sonnet'])


def parse_and_validate(
    ocr_text: str,
    api_key: str,
    spec: Optional[Dict[str, Any]] = None,
    spec_id: Optional[str] = None,
    image_paths: Optional[List[str]] = None,
    model: str = "sonnet",
) -> Dict[str, Any]:
    """
    Send OCR text and page images to Claude for structured extraction.

    Args:
        ocr_text: Raw text from PaddleOCR extraction.
        api_key: Anthropic API key.
        spec: Optional spec dict for cross-referencing.
        spec_id: Optional spec identifier string.
        image_paths: Optional list of page image paths for vision.
        model: Model to use — 'sonnet', 'opus', or 'sonnet_with_opus_fallback'.

    Returns:
        Parsed MTR data dict compatible with normalize_extracted_data().
    """
    import anthropic

    # Handle fallback strategy
    if model == 'sonnet_with_opus_fallback':
        result = _call_claude(ocr_text, api_key, spec, spec_id, image_paths, 'sonnet')
        if result.get('_extraction_status') == 'error':
            logger.warning("Sonnet extraction failed, falling back to Opus...")
            result = _call_claude(ocr_text, api_key, spec, spec_id, image_paths, 'opus')
            if result.get('_extraction_status') == 'success':
                result['_fallback_used'] = 'opus'
        return result

    return _call_claude(ocr_text, api_key, spec, spec_id, image_paths, model)


def _call_claude(
    ocr_text: str,
    api_key: str,
    spec: Optional[Dict[str, Any]],
    spec_id: Optional[str],
    image_paths: Optional[List[str]],
    model: str,
) -> Dict[str, Any]:
    """Execute a single Claude API call with optional vision."""
    import time as _time
    import anthropic

    t_func_start = _time.time()

    spec_context = ""
    if spec:
        spec_text = _format_spec_as_text(spec)
        spec_context = _build_spec_context(spec_text, spec_id)

    # Strip garbled chemistry table data when images are available
    # (Claude will read chemistry from images instead)
    t0 = _time.time()
    clean_ocr = _strip_chemistry_table_from_ocr(ocr_text) if image_paths else ocr_text
    logger.info("[TIMING] _strip_chemistry_table: %.2fs", _time.time() - t0)

    prompt_text = EXTRACTION_PROMPT.format(
        ocr_text=clean_ocr,
        spec_context=spec_context,
    )
    logger.info("[TIMING] Prompt size: %d chars (OCR: %d, spec_context: %d)",
                len(prompt_text), len(clean_ocr), len(spec_context))

    # Build multimodal content: images first, then text prompt
    content: list = []

    if image_paths:
        t0 = _time.time()
        relevant_indices = select_relevant_pages(
            ocr_text=ocr_text,
            total_pages=len(image_paths),
            max_pages=MAX_IMAGE_PAGES,
        )
        logger.info("[TIMING] select_relevant_pages: %.2fs -> pages %s of %d",
                     _time.time() - t0, [i + 1 for i in relevant_indices], len(image_paths))

        selected_paths = [image_paths[i] for i in relevant_indices]
        t0 = _time.time()
        image_blocks = _encode_images(selected_paths)
        total_img_bytes = sum(len(b.get('source', {}).get('data', '')) for b in image_blocks) if image_blocks else 0
        logger.info("[TIMING] _encode_images (%d pages): %.2fs (~%.1f MB base64)",
                     len(selected_paths), _time.time() - t0, total_img_bytes / 1_000_000)
        if image_blocks:
            content.extend(image_blocks)

    content.append({"type": "text", "text": prompt_text})

    model_id = _resolve_model(model)
    client = anthropic.Anthropic(api_key=api_key)

    logger.info("[TIMING] Sending to Claude (%s) — %d content blocks, %d images...",
                model_id, len(content), len(content) - 1)
    t0 = _time.time()
    message = client.messages.create(
        model=model_id,
        max_tokens=4096,
        messages=[
            {"role": "user", "content": content}
        ],
    )
    api_elapsed = _time.time() - t0

    response_text = message.content[0].text

    # Log token usage for cost tracking
    usage = getattr(message, 'usage', None)
    if usage:
        in_tok = getattr(usage, 'input_tokens', 0)
        out_tok = getattr(usage, 'output_tokens', 0)
        logger.info("[TIMING] Claude API call (%s): %.1fs | %d in + %d out = %d tokens | response: %d chars",
                     model_id, api_elapsed, in_tok, out_tok, in_tok + out_tok, len(response_text))
    else:
        logger.info("[TIMING] Claude API call (%s): %.1fs | response: %d chars",
                     model_id, api_elapsed, len(response_text))

    t0 = _time.time()
    result = _parse_response(response_text)
    logger.info("[TIMING] _parse_response: %.2fs", _time.time() - t0)

    if usage:
        result['_token_usage'] = {
            'input_tokens': getattr(usage, 'input_tokens', 0),
            'output_tokens': getattr(usage, 'output_tokens', 0),
        }

    logger.info("[TIMING] _call_claude TOTAL: %.1fs", _time.time() - t_func_start)
    return result


def _parse_response(response_text: str) -> Dict[str, Any]:
    """
    Parse Claude's response text into a JSON dict.
    Handles markdown code blocks and common formatting issues.
    """
    text = response_text.strip()

    # Strip markdown code fences if present
    if '```json' in text:
        try:
            start = text.index('```json') + 7
            end = text.index('```', start)
            text = text[start:end].strip()
        except ValueError:
            pass
    elif '```' in text:
        try:
            start = text.index('```') + 3
            end = text.index('```', start)
            text = text[start:end].strip()
        except ValueError:
            pass

    # Find JSON object boundaries
    if not text.startswith('{'):
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            text = text[start:end + 1]

    try:
        data = json.loads(text)
        data['_extraction_status'] = 'success'
        return data
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Claude response as JSON: %s", e)
        return {
            '_extraction_status': 'error',
            '_error': f"Failed to parse JSON: {e}",
            '_raw_response': response_text[:1000],
        }


def test_connection(api_key: str) -> tuple[bool, str]:
    """
    Test the Anthropic API connection with a minimal request.

    Returns:
        (success, message) tuple.
    """
    import anthropic

    try:
        client = anthropic.Anthropic(api_key=api_key)
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}],
        )
        return True, "Connected to Anthropic API (Claude Sonnet 4.6)"
    except anthropic.AuthenticationError:
        return False, "Invalid API key"
    except Exception as e:
        return False, f"Connection failed: {e}"
