"""
MTR Extractor - Extracts structured data from MTR images/PDFs.

This module provides:
1. PDF to image conversion
2. Prompt template for vision LLM extraction
3. Response parsing utilities
4. Manual entry fallback

Vision extraction is designed to be called by the OpenClaw agent (Cipher),
which has direct access to vision LLM capabilities.
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any


# Extraction prompt for vision LLM
EXTRACTION_PROMPT = """Analyze this Material Test Report (MTR) image and extract all data into structured JSON.

**IMPORTANT**: Extract ONLY what is explicitly shown on the document. Do not guess or infer values.

## Required Fields:
- heat_number: The heat, lot, or batch number (critical identifier)
- material_grade: Material grade (e.g., "4140", "303", "420 SS", "Inconel 625")

## Header Information (if shown):
- uns: UNS number (e.g., "S30300", "G41400") 
- supplier: Mill or supplier name
- customer: Customer/purchaser name
- po_number: Purchase order number
- product_form: Bar, plate, tube, forging, etc.
- size: Dimensions (e.g., "2.250 inch round")
- condition: Heat treatment (Annealed, Q&T, Normalized, etc.)

## Chemistry (% by weight):
Extract all elements shown. Common: C, Mn, P, S, Si, Cr, Ni, Mo, Cu, V, Nb, Ti, Al, N, B
- Convert percentages to decimal (e.g., "0.04%" → 0.04)

## Mechanical Properties:
- yield_strength: 0.2% offset yield strength (note unit: ksi or MPa)
- tensile_strength: Ultimate tensile strength
- elongation: % elongation
- reduction_of_area: % reduction of area
- hardness_hbw: Brinell hardness
- hardness_hrc: Rockwell C hardness

## Special Tests (if present):
- charpy_impact: {avg, temperature, temp_unit, unit} (e.g., avg ft-lbs at °F)
- temper_temperature: Tempering temperature (°F or °C)
- nace_compliant: true if NACE/HIC/SSC compliance stated
- grain_size: ASTM grain size number

## Output Format:
Return ONLY valid JSON (no markdown, no explanation):

{
  "heat_number": "string",
  "material_grade": "string",
  "uns": "string or null",
  "supplier": "string or null", 
  "customer": "string or null",
  "po_number": "string or null",
  "product_form": "string or null",
  "size": "string or null",
  "condition": "string or null",
  "chemistry": {
    "C": 0.00,
    "Mn": 0.00
  },
  "mechanical": {
    "yield_strength": 0.0,
    "yield_strength_unit": "ksi",
    "tensile_strength": 0.0,
    "tensile_strength_unit": "ksi",
    "elongation": 0.0,
    "reduction_of_area": 0.0,
    "hardness_hbw": 0,
    "hardness_hrc": 0
  },
  "charpy_impact": null,
  "temper_temperature": null,
  "nace_compliant": null,
  "grain_size": null
}

Notes:
- Omit fields not shown (or use null)
- For multiple specimens, use averages
- Include _unit suffix for stress values if not ksi
"""


def get_extraction_prompt() -> str:
    """Get the extraction prompt for vision LLM."""
    return EXTRACTION_PROMPT


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
                normalized['mechanical']['yield_strength'] = val.get('value')
            else:
                normalized['mechanical']['yield_strength'] = val
            if unit and unit.lower() != 'ksi':
                normalized['mechanical']['yield_strength_unit'] = unit
        
        # Tensile strength
        if 'tensile_strength' in mech:
            val = mech['tensile_strength']
            unit = mech.get('tensile_strength_unit', 'ksi')
            if isinstance(val, dict):
                normalized['mechanical']['tensile_strength'] = val.get('value')
            else:
                normalized['mechanical']['tensile_strength'] = val
            if unit and unit.lower() != 'ksi':
                normalized['mechanical']['tensile_strength_unit'] = unit
        
        # Other mechanical properties (simple copy)
        for field in ['elongation', 'reduction_of_area', 'hardness_hbw', 
                      'hardness_hrc', 'hardness_hrb']:
            if field in mech and mech[field] is not None:
                normalized['mechanical'][field] = mech[field]
    
    # Special tests
    if 'charpy_impact' in data and data['charpy_impact']:
        normalized['charpy_impact'] = data['charpy_impact']
    
    if 'temper_temperature' in data and data['temper_temperature']:
        normalized['temper_temperature'] = data['temper_temperature']
    
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


def manual_entry() -> Dict[str, Any]:
    """
    Interactive manual entry mode for MTR data.
    Useful for testing or when vision extraction isn't available.
    """
    print("\n=== Manual MTR Entry ===\n")
    
    data = {
        'chemistry': {},
        'mechanical': {}
    }
    
    # Header info
    data['heat_number'] = input("Heat Number: ").strip()
    data['material_grade'] = input("Material Grade (e.g., 4140, 303): ").strip()
    data['uns'] = input("UNS Number (or blank): ").strip() or None
    data['supplier'] = input("Supplier/Mill (or blank): ").strip() or None
    data['condition'] = input("Condition (e.g., Annealed, Q&T): ").strip() or None
    
    # Chemistry
    print("\nChemistry (enter blank element to finish):")
    while True:
        element = input("  Element (e.g., C, Cr, Ni): ").strip().capitalize()
        if not element:
            break
        try:
            value = float(input(f"  {element} value (%): "))
            data['chemistry'][element] = value
        except ValueError:
            print("  Invalid number, skipping")
    
    # Mechanical
    print("\nMechanical Properties (blank to skip):")
    
    for prop, prompt in [
        ('yield_strength', 'Yield Strength (ksi)'),
        ('tensile_strength', 'Tensile Strength (ksi)'),
        ('elongation', 'Elongation (%)'),
        ('reduction_of_area', 'Reduction of Area (%)'),
        ('hardness_hbw', 'Hardness HBW'),
        ('hardness_hrc', 'Hardness HRc'),
    ]:
        try:
            val = input(f"  {prompt}: ").strip()
            if val:
                data['mechanical'][prop] = float(val)
        except ValueError:
            pass
    
    # Special
    temper = input("\nTemper Temperature (°F, or blank): ").strip()
    if temper:
        try:
            data['temper_temperature'] = float(temper)
        except ValueError:
            pass
    
    nace = input("NACE Compliant (y/n/blank): ").strip().lower()
    if nace == 'y':
        data['nace_compliant'] = True
    elif nace == 'n':
        data['nace_compliant'] = False
    
    return data


if __name__ == '__main__':
    # CLI for testing
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        
        if arg == '--prompt':
            # Print extraction prompt
            print(EXTRACTION_PROMPT)
        
        elif arg == '--manual':
            # Manual entry
            data = manual_entry()
            print("\nExtracted data:")
            print(json.dumps(data, indent=2))
        
        elif arg.endswith('.pdf'):
            # Convert PDF to images
            images = pdf_to_images(arg)
            print(f"Converted {len(images)} pages:")
            for img in images:
                print(f"  {img}")
        
        else:
            print(f"Unknown argument: {arg}")
            print("Usage:")
            print("  python extractor.py --prompt     # Show extraction prompt")
            print("  python extractor.py --manual     # Manual entry mode")
            print("  python extractor.py file.pdf     # Convert PDF to images")
    else:
        print("MTR Extractor")
        print("Usage:")
        print("  python extractor.py --prompt     # Show extraction prompt")
        print("  python extractor.py --manual     # Manual entry mode")
        print("  python extractor.py file.pdf     # Convert PDF to images")
