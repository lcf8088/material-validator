"""
Claude Opus 4.6 structured parser for MTR data extraction.

Takes raw OCR text output from PaddleOCR and sends it to Claude
with a structured extraction prompt and optional spec context.
Returns parsed JSON matching the existing MTR data format.
"""

import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Structured extraction prompt for Claude
EXTRACTION_PROMPT = """\
You are an expert at reading Material Test Reports (MTRs) / Mill Certifications.

Below is raw OCR text extracted from an MTR document. Parse it into structured JSON.

**RULES**:
- Extract ONLY what is explicitly stated in the text. Do not guess or infer values.
- Chemistry values are percentages by weight (e.g., 0.04 means 0.04%).
- Stress values: note whether they are in ksi, MPa, or psi. Report the unit exactly as shown on the document.
- If a field is not present in the OCR text, use null.
- For po_number: the customer PO always starts with "PO" (e.g., PO001533). Ignore supplier order numbers, internal references, or any number that does not start with "PO".
- For multiple specimens/tests, use averages for mechanical properties.
- Element symbols should be standard (C, Mn, P, S, Si, Cr, Ni, Mo, Cu, V, Nb, Ti, Al, N, B, W, Co).

**OCR TEXT**:
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
  "temper_temperature": null,
  "nace_compliant": null,
  "grain_size": null
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


def parse_and_validate(
    ocr_text: str,
    api_key: str,
    spec: Optional[Dict[str, Any]] = None,
    spec_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send OCR text to Claude for structured extraction and optional spec validation.

    Args:
        ocr_text: Raw text from PaddleOCR extraction.
        api_key: Anthropic API key.
        spec: Optional spec dict for cross-referencing.
        spec_id: Optional spec identifier string.

    Returns:
        Parsed MTR data dict compatible with normalize_extracted_data().
    """
    import anthropic

    spec_context = ""
    if spec:
        spec_text = _format_spec_as_text(spec)
        spec_context = _build_spec_context(spec_text, spec_id)

    prompt = EXTRACTION_PROMPT.format(
        ocr_text=ocr_text,
        spec_context=spec_context,
    )

    client = anthropic.Anthropic(api_key=api_key)

    logger.info("Sending OCR text to Claude for structured parsing...")
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[
            {"role": "user", "content": prompt}
        ],
    )

    response_text = message.content[0].text
    logger.info("Claude response received (%d chars).", len(response_text))

    # Parse the JSON response
    return _parse_response(response_text)


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
            model="claude-opus-4-6",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}],
        )
        return True, "Connected to Anthropic API (Claude Opus 4.6)"
    except anthropic.AuthenticationError:
        return False, "Invalid API key"
    except Exception as e:
        return False, f"Connection failed: {e}"
