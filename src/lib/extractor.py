"""
MTR Extractor - Utility functions for MTR data processing.

This module provides:
1. PDF to image conversion
2. Response parsing utilities
3. Data normalization

OCR extraction is handled by lib/paddle_ocr.py.
Structured parsing is handled by lib/claude_parser.py.
"""

import json
import logging
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

from lib.converters import convert_stress

logger = logging.getLogger(__name__)


def pdf_to_images(pdf_path: str, dpi: int = 150) -> list:
    """
    Convert PDF pages to images.
    
    Args:
        pdf_path: Path to the PDF file
        dpi: Resolution for rendering (default 150)
        
    Returns:
        List of image file paths (PNG)
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        raise ImportError("pymupdf required: pip install pymupdf")
    
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    doc = fitz.open(pdf_path)
    image_paths = []
    
    # Scale factor for DPI (72 is default PDF DPI)
    scale = dpi / 72.0
    mat = fitz.Matrix(scale, scale)
    
    output_dir = Path(tempfile.gettempdir()) / 'mtr_extraction'
    output_dir.mkdir(exist_ok=True)
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=mat)
        
        output_path = output_dir / f"{pdf_path.stem}_page{page_num + 1}.png"
        pix.save(str(output_path))
        image_paths.append(str(output_path))
    
    doc.close()
    return image_paths


def parse_extraction_response(response_text: str) -> Dict[str, Any]:
    """
    Parse vision LLM response to extract JSON data.
    Handles markdown code blocks and common formatting issues.
    
    Args:
        response_text: Raw response from vision LLM
        
    Returns:
        Parsed MTR data dictionary
    """
    text = response_text.strip()
    
    # Try to find JSON in code block
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
    
    # Try to find JSON object directly
    if not text.startswith('{'):
        # Look for first { and last }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            text = text[start:end + 1]
    
    # Parse JSON
    try:
        data = json.loads(text)
        data['_extraction_status'] = 'success'
        return data
    except json.JSONDecodeError as e:
        return {
            '_extraction_status': 'error',
            '_error': f"Failed to parse JSON: {e}",
            '_raw_response': response_text[:1000]
        }


def normalize_extracted_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize extracted data to standard format expected by validator.
    
    Handles variations in field names, units, etc.
    """
    normalized = {}
    
    # Copy header fields
    for field in ['heat_number', 'material_grade', 'uns', 'supplier',
                  'customer', 'po_number', 'product_form', 'size', 'condition']:
        if field in data and data[field]:
            normalized[field] = data[field]

    # Validate PO number format: must start with "PO" (case-insensitive)
    po = normalized.get('po_number')
    if po and not str(po).upper().startswith('PO'):
        logger.warning("Ignoring extracted PO '%s' — does not start with 'PO'", po)
        del normalized['po_number']
    
    # Normalize chemistry
    if 'chemistry' in data and data['chemistry']:
        normalized['chemistry'] = {}
        for elem, val in data['chemistry'].items():
            # Normalize element names (title case, strip) - e.g. "cr" → "Cr"
            elem_norm = elem.strip().capitalize()
            if isinstance(val, (int, float)):
                normalized['chemistry'][elem_norm] = float(val)
    
    # Normalize mechanical properties
    if 'mechanical' in data and data['mechanical']:
        mech = data['mechanical']
        normalized['mechanical'] = {}
        
        # Yield strength
        if 'yield_strength' in mech:
            val = mech['yield_strength']
            unit = mech.get('yield_strength_unit', 'ksi')
            if isinstance(val, dict):
                val = val.get('value')
            if val is not None and unit and unit.lower() != 'ksi':
                try:
                    val = round(convert_stress(float(val), unit, 'ksi'), 1)
                    logger.info("Converted yield_strength from %s to ksi: %.1f", unit, val)
                    unit = 'ksi'
                except (ValueError, TypeError):
                    pass
            normalized['mechanical']['yield_strength'] = val

        # Tensile strength
        if 'tensile_strength' in mech:
            val = mech['tensile_strength']
            unit = mech.get('tensile_strength_unit', 'ksi')
            if isinstance(val, dict):
                val = val.get('value')
            if val is not None and unit and unit.lower() != 'ksi':
                try:
                    val = round(convert_stress(float(val), unit, 'ksi'), 1)
                    logger.info("Converted tensile_strength from %s to ksi: %.1f", unit, val)
                    unit = 'ksi'
                except (ValueError, TypeError):
                    pass
            normalized['mechanical']['tensile_strength'] = val
        
        # Other mechanical properties (simple copy)
        for field in ['elongation', 'reduction_of_area', 'hardness_hbw', 
                      'hardness_hrc', 'hardness_hrb']:
            if field in mech and mech[field] is not None:
                normalized['mechanical'][field] = mech[field]
    
    # Special tests
    if 'charpy_impact' in data and data['charpy_impact']:
        normalized['charpy_impact'] = data['charpy_impact']
    
    if 'temper_temperature' in data and data['temper_temperature']:
        raw_temper = str(data['temper_temperature']).strip()
        # Strip unit suffixes (e.g. "1140F", "1140 °F", "620C")
        temper_match = re.match(r'^([0-9.]+)', raw_temper)
        if temper_match:
            normalized['temper_temperature'] = float(temper_match.group(1))
        else:
            normalized['temper_temperature'] = raw_temper
    
    if 'nace_compliant' in data and data['nace_compliant'] is not None:
        normalized['nace_compliant'] = data['nace_compliant']
    
    if 'grain_size' in data and data['grain_size']:
        normalized['grain_size'] = data['grain_size']
    
    return normalized


def save_extracted_data(data: Dict[str, Any], output_path: str) -> str:
    """
    Save extracted MTR data to JSON file.
    
    Args:
        data: Extracted MTR data
        output_path: Path for output JSON file
        
    Returns:
        Path to saved file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    return str(output_path)


if __name__ == '__main__':
    # CLI for testing
    if len(sys.argv) > 1 and sys.argv[1].endswith('.pdf'):
        images = pdf_to_images(sys.argv[1])
        print(f"Converted {len(images)} pages:")
        for img in images:
            print(f"  {img}")
    else:
        print("Usage: python extractor.py file.pdf  # Convert PDF to images")
