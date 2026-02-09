# Material Cert Validator

Validates Material Test Reports (MTRs) against internal engineering specifications.

## Desktop Application (Windows)

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Run the GUI
python run_gui.py
```

### Building Standalone .exe

```bash
pip install pyinstaller
pyinstaller build_exe.spec
# Output: dist/MaterialCertValidator.exe
```

### Features
- Drag & drop PDF/image files
- Multiple vision API options (OpenAI, Anthropic, Google, local)
- Auto-detect specification based on material grade
- TIFF export with naming convention: `HEAT_NUMBER-PO_NUMBER.tiff`
- Validation history and audit trail
- Sanity checks for extraction errors

---

## CLI Quick Start

```bash
# List available specs
python3 validate.py --list-specs

# Show spec details
python3 validate.py --show-spec ES-M0003A

# Validate MTR from JSON
python3 validate.py --json tests/mtrs/heat-Y75T-303ss.json --spec ES-M0003A

# Auto-detect spec and validate
python3 validate.py --json tests/mtrs/heat-D2213660-4140.json --auto

# Manual entry mode
python3 validate.py --manual --spec ES-M0001G
```

## Project Structure

```
material-validator/
├── validate.py          # CLI entry point
├── run_gui.py           # GUI launcher
├── run.bat              # Windows launcher
├── build_exe.spec       # PyInstaller build config
├── requirements.txt     # Dependencies
├── README.md
├── docs/                # Documentation
│   ├── SETUP.md         # First-time setup guide
│   ├── ROADMAP.md       # Feature roadmap
│   └── extract-mtr.md   # Extraction prompt reference
├── src/                 # Source code
│   ├── lib/             # Core library
│   │   ├── validator.py     # Core validation engine
│   │   ├── spec_loader.py   # Specification loader (singleton)
│   │   ├── matcher.py       # Spec auto-detection
│   │   ├── extractor.py     # MTR data extraction (vision LLM)
│   │   ├── pipeline.py      # End-to-end OCR pipeline
│   │   ├── paddle_ocr.py    # PaddleOCR wrapper
│   │   ├── claude_parser.py # Claude vision parsing
│   │   ├── converters.py    # Unit/scale conversions
│   │   ├── sanity.py        # Data quality checks
│   │   ├── history.py       # Validation audit trail
│   │   └── watcher.py       # Folder watch auto-process
│   └── gui/             # Desktop GUI
│       ├── app.py           # Main application (customtkinter)
│       ├── config.py        # Configuration management
│       ├── settings.py      # Settings panel
│       ├── theme.py         # D&D brand theme
│       └── tiff_export.py   # TIFF archive export
├── specs/               # Engineering specifications (YAML)
├── tests/               # Test suite
│   └── mtrs/            # Test MTR data files
└── history/             # Validation records (git-ignored)
```

## Specifications

| Spec ID     | Material                    | Key Requirements |
|-------------|----------------------------|------------------|
| ES-M0001C   | 4140/4142 Standard         | YS ≥ 80 ksi, NACE |
| ES-M0001G   | 4140/4142 110 MYS          | YS ≥ 110 ksi, Temper ≥ 1025°F |
| ES-M0003A   | 303 Stainless Steel        | YS ≥ 30 ksi, RA ≥ 40% |
| ES-M0003E   | 13Cr / 420 SS              | YS 80-95 ksi, Charpy ≥ 15 ft-lbs |

## Validation Status Codes

- **PASS** - All requirements met
- **FAIL** - One or more requirements not met
- **INCOMPLETE** - Missing required data
- **MISSING** - Specific property not found in MTR

## Auto-Detection Logic

When using `--auto`, the matcher:
1. Matches by UNS number (highest confidence)
2. Matches by material grade name
3. Uses yield strength to differentiate when multiple specs match same material
   - Example: 4140 @ 85 ksi → ES-M0001C, 4140 @ 115 ksi → ES-M0001G

## Adding New Specs

Create a YAML file in `specs/` following this structure:

```yaml
id: ES-M0004A
revision: 0
date: 2024-01-15
material: Inconel 625
grades:
  - "625"
  - "Inconel 625"
  - "N06625"
uns: N06625
condition: Annealed

chemistry:
  Ni: { min: 58.0 }
  Cr: { min: 20.0, max: 23.0 }
  Mo: { min: 8.0, max: 10.0 }
  # ... more elements

mechanical:
  yield_strength: { min: 60, unit: ksi }
  tensile_strength: { min: 120, unit: ksi }
  elongation: { min: 30, unit: '%' }

special_requirements:
  - type: grain_size
    max: 5
    note: "ASTM E112"
```

## First-Time Setup

See [SETUP.md](docs/SETUP.md) for configuration walkthrough.

## Adding Specifications

See [SPEC-AUTHORING.md](docs/SPEC-AUTHORING.md) for the full guide on converting DDIC material specification PDFs into YAML spec files, including templates, worked examples, and batch processing workflow.

## Future Enhancements

- [x] Batch processing mode
- [x] Auto-archive TIFF after validation
- [x] Watch folder auto-processing
- [ ] Multi-heat cert support
- [ ] Spec revision tracking and comparison
- [ ] Digital signature for validation integrity
- [ ] Cert expiration alerts
