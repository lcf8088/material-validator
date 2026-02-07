# MTR Extraction Workflow

This document describes how to extract and validate Material Test Reports.

## Quick Workflow

### Step 1: Convert PDF to Images (if needed)
```bash
python validate.py --pdf path/to/mtr.pdf
```
Output: PNG images in your system temp directory under `mtr_extraction/`

### Step 2: Extract Data via Vision
Send the image to Cipher with this prompt:
```
Extract the MTR data from this image into JSON format:
{
  "heat_number": "...",
  "material_grade": "...",
  "uns": "...",
  "supplier": "...",
  "chemistry": {"C": 0.00, "Mn": 0.00, ...},
  "mechanical": {"yield_strength": 0.0, "tensile_strength": 0.0, ...},
  "temper_temperature": 0
}
```

### Step 3: Save and Validate
Save the extracted JSON to a file (e.g., `extracted-mtr.json`), then:
```bash
# Validate with auto-detection
python validate.py --json extracted-mtr.json --auto

# Or specify spec
python validate.py --json extracted-mtr.json --spec ES-M0001G
```

## Extraction Prompt

For consistent extraction, use this prompt with the image:

```
Analyze this Material Test Report (MTR) and extract all data into JSON.

Required fields:
- heat_number: The heat/lot number
- material_grade: Material grade (e.g., "4140", "303 SS")
- uns: UNS number if shown
- supplier: Mill or supplier name

Chemistry (% by weight):
- Extract all elements: C, Mn, P, S, Si, Cr, Ni, Mo, etc.
- Convert percentages to decimal (0.04% → 0.04)

Mechanical properties:
- yield_strength (ksi)
- tensile_strength (ksi)  
- elongation (%)
- reduction_of_area (%)
- hardness_hrc or hardness_hbw

Special (if shown):
- temper_temperature (°F)
- nace_compliant (true/false)
- charpy_impact

Return ONLY valid JSON, no markdown or explanation.
```

## CLI Reference

```bash
# List specs
python validate.py --list-specs

# Show spec details
python validate.py --show-spec ES-M0003A

# Validate with auto-detection
python validate.py --json mtr.json --auto

# Validate against specific spec
python validate.py --json mtr.json --spec ES-M0001G

# Convert PDF to images
python validate.py --pdf cert.pdf

# Show extraction prompt
python validate.py --extract-prompt
```

## Available Specifications

| ID | Material | Min YS |
|----|----------|--------|
| ES-M0001C | 4140/4142 Standard | 80 ksi |
| ES-M0001G | 4140/4142 110 MYS | 110 ksi |
| ES-M0003A | 303 Stainless Steel | 30 ksi |
| ES-M0003E | 13Cr / 420 SS | 80-95 ksi |
