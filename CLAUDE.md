# Material Validator - Project Reference

> **IMPORTANT**: Keep this file updated as the project evolves. When you add modules, specs, tests, change the pipeline, or fix significant bugs, update the relevant section here. Treat this like a living changelog + architecture doc.

## What This Project Does

**Material Cert Validator** is a desktop app + CLI for **D&D Drilling International Corp** that validates Material Test Reports (MTRs) against internal engineering specifications. It checks chemical composition, mechanical properties, and special requirements for industrial materials (steel alloys, stainless steel, nickel alloys, polymers, etc.).

## Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | 3.12.9 (Windows) |
| OCR (GPU) | RapidOCR + ONNX Runtime CUDA | 1.4.4 / 1.24.1 |
| OCR (CPU fallback) | PaddleOCR (PP-OCRv5) + PaddlePaddle | 3.4.0 / 3.3.0 |
| AI Parsing | Anthropic Claude API | 0.79.0 |
| GUI | customtkinter + tkinterdnd2 | 5.2.2 |
| PDF | PyMuPDF (fitz) | |
| Image | OpenCV, Pillow | |
| Specs | YAML files | |
| File Monitor | watchdog | |
| Build | PyInstaller | |

## Pipeline (end-to-end flow)

```
User drops PDF/image (GUI or watch folder)
    |
    v
pipeline.process_document()
    |-> preprocessor.is_digital_native()       # check if PDF has text layer
    |-> extractor.pdf_to_images()              # PDF -> images at configurable DPI
    |-> page_relevance.score_pages()           # filter irrelevant pages
    |-> preprocessor.preprocess_images()       # deskew, CLAHE, threshold (if scanned)
    |-> gpu_ocr / paddle_ocr.extract_text()    # OCR text extraction
    |-> claude_parser.parse_and_validate()     # Claude API -> structured JSON
    |-> extractor.normalize_extracted_data()   # float coercion, unit conversion, element normalization
    |-> matcher.select_best_spec()             # auto-detect spec by UNS/grade/YS (if not manual)
    |-> validator.validate()                   # compare each property against spec min/max
    |-> sanity.run_all_sanity_checks()         # flag impossible values, borderline warnings
    |-> image_export.pdf_to_jpgs()             # per-page grayscale JPGs (_page_NN suffix)
    |-> history.record()                       # JSONL audit trail
    |
    v
PipelineResult -> GUI display / CLI output
```

## Project Structure

```
material-validator/
├── CLAUDE.md               # THIS FILE - project context for Claude Code
├── validate.py             # CLI entry point
├── run_gui.py              # GUI launcher (dependency check + start)
├── run.bat                 # Windows batch launcher (sets env vars)
├── requirements.txt        # Python dependencies
├── build_exe.spec          # PyInstaller build config
├── config.json             # User config (git-ignored, has API key)
│
├── src/
│   ├── gui/                # Desktop application layer
│   │   ├── app.py              # Main GUI - sidebar nav, D&D theme, drag-drop, cards
│   │   ├── config.py           # Config persistence (JSON read/write)
│   │   ├── settings.py         # Embedded settings panel (Pipeline/Archive/General tabs)
│   │   ├── theme.py            # D&D branded dark theme constants
│   │   ├── image_export.py     # Per-page JPG export & archive naming
│   │   ├── override_dialog.py  # Manual override dialog for spec/validation
│   │   └── logo.jpg            # D&D company logo
│   │
│   └── lib/                # Core processing & validation engines
│       ├── __init__.py         # Public API exports
│       ├── pipeline.py         # End-to-end orchestrator
│       ├── validator.py        # Core validation engine (compare MTR vs spec)
│       ├── sanity.py           # Data quality checks (flag suspicious values)
│       ├── matcher.py          # Auto-detect best spec from MTR data
│       ├── extractor.py        # PDF->images, data normalization
│       ├── claude_parser.py    # Claude API structured extraction
│       ├── paddle_ocr.py       # PaddleOCR CPU wrapper
│       ├── gpu_ocr.py          # RapidOCR + ONNX Runtime CUDA (17x faster)
│       ├── page_relevance.py   # Smart page filtering/scoring
│       ├── preprocessor.py     # Image preprocessing for scanned docs
│       ├── spec_loader.py      # YAML spec loader (singleton)
│       ├── converters.py       # Unit conversions (ksi<->MPa, HRc<->HBW)
│       ├── assembly.py         # Assembly/COC document handling
│       ├── report.py           # Report generation
│       ├── history.py          # Validation audit trail (JSONL + index)
│       └── watcher.py          # Folder monitoring (auto-process new files)
│
├── specs/                  # 59 material specification YAML files
│   ├── ES-M0001*.yaml         # 4140/4142 alloy steel variants
│   ├── ES-M0003*.yaml         # Stainless steel / 13Cr / Super 13Cr variants
│   ├── ES-M0004*.yaml         # Nickel alloys (Inconel, Monel, etc.)
│   ├── ES-M1001*.yaml         # Additional alloy specs
│   ├── ES-M1101*.yaml         # Additional alloy specs
│   ├── ES-M1301*.yaml         # Additional alloy specs
│   ├── ES-M2001*.yaml         # Polymer/elastomer specs
│   ├── ES-M2201*.yaml         # PEEK specs
│   └── ES-M2401*.yaml         # Additional material specs
│
├── tests/                  # 19 test files
│   ├── conftest.py             # Fixtures: specs_dir, mtr_4140, mtr_303, tmp_dir
│   ├── mtrs/                   # Test MTR JSON data files
│   ├── test_01_imports.py      # Module imports
│   ├── test_02_spec_loader.py  # YAML loading, singleton
│   ├── test_03_validator.py    # Core validation (range checks, real MTRs)
│   ├── test_04_matcher.py      # Spec auto-detection (UNS/grade/YS)
│   ├── test_05_sanity.py       # Data quality checks
│   ├── test_06_converters.py   # Unit conversions
│   ├── test_07_extractor.py    # PDF + normalization
│   ├── test_08_history.py      # Audit trail
│   ├── test_09_config.py       # Config persistence
│   ├── test_10_image_export.py # Archive filename generation
│   ├── test_11_preprocessor.py # Image preprocessing
│   ├── test_12_paddle_ocr.py   # OCR wrapper
│   ├── test_13_claude_parser.py# Claude API parsing
│   ├── test_14_pipeline.py     # Full pipeline (mocked)
│   ├── test_15_watcher.py      # File monitoring
│   ├── test_16_cli.py          # CLI commands
│   ├── test_17_integration.py  # End-to-end workflows
│   ├── test_18_page_relevance.py # Page scoring
│   └── test_plan_runner.py     # Plan test runner
│
└── history/                # Runtime validation logs (git-ignored)
```

## Key Module Details

### validator.py - Validation Engine
- `SpecValidator.validate(mtr_data, spec_id) -> CertValidation`
- Validates chemistry (element %), mechanical (YS/TS/elong/RA/hardness), special (NACE/temper/charpy)
- Auto-converts units (ksi<->MPa) and hardness scales (HRc<->HBW)
- Status per property: PASS, FAIL, MISSING, INCOMPLETE, SKIP
- Overall: PASS (all pass), FAIL (any fail), INCOMPLETE (any missing)
- PROPERTY_ALIASES maps canonical names to 5+ alternate field names each

### matcher.py - Spec Auto-Detection
- `SpecMatcher.select_best_spec(mtr_data) -> MatchResult`
- Hierarchy: UNS (0.9) > exact grade (0.8) > partial grade (0.6) > keyword (lower)
- Yield strength differentiates similar specs (e.g., 4140 standard vs 110 MYS)

### sanity.py - Data Quality
- Chemistry: negative values, out-of-range, Cr/Ni swap detection
- Mechanical: TS < YS impossible, material-aware TS/YS ratio check
- Borderline: values within 5% of spec limits
- Returns: `{errors: [], warnings: [], borderline: []}`

### gpu_ocr.py - GPU OCR (primary)
- RapidOCR 1.4.4 + onnxruntime-gpu 1.24.1 + PP-OCRv4 ONNX models
- RTX 5090 Laptop: 10s GPU vs 77s CPU (RapidOCR) vs 172s (PaddleOCR CPU) = **17x speedup**
- CUDA DLL trick: must add nvidia pip package bin dirs to PATH before onnxruntime import
- Config: `use_gpu_ocr: true` (default on, falls back to PaddleOCR CPU)

### claude_parser.py - Claude API
- Sends OCR text + optional page images to Claude for structured JSON extraction
- System prompt enforces string->number coercion, null for missing, PO format validation
- Supports Opus precision pass for chemistry/mechanical tables

### pipeline.py - Orchestrator
- `process_document()` runs the full pipeline shown above
- Progress callbacks for GUI (`on_progress(step, pct)`)
- Thread lock prevents concurrent extractions
- Assembly/COC detection and handling

## Design Patterns

1. **Singleton**: SpecLoader.get_instance() for shared spec access
2. **Dataclasses**: ValidationResult, CertValidation, PipelineResult, BatchResult
3. **Append-only Log**: JSONL + JSON index for audit compliance
4. **Lazy Loading**: OCR models cached in module global on first use
5. **Property Aliases**: Flexible field matching (yield_strength has 5+ names)
6. **Pivot Conversion**: All stress conversions route through ksi
7. **Hardness Interpolation**: HRc<->HBW via ASTM E140 lookup + linear interp
8. **Progress Callbacks**: Pipeline/batch use `on_progress(step, pct)` callbacks
9. **Stability Detection**: Watcher polls file size to detect copy completion
10. **Thread Safety**: Pipeline lock; UI updates via `root.after()`

## Running

```bash
# GUI
python run_gui.py

# CLI
python validate.py --list-specs
python validate.py --json tests/mtrs/heat-D2213660-4140.json --auto
python validate.py --pipeline cert.pdf --auto

# Tests
pytest tests/ -v

# Build .exe
pyinstaller build_exe.spec
```

## Known Constraints

- **PaddlePaddle 3.3.0**: `enable_mkldnn=True` crashes with ArrayAttribute error -> use `enable_mkldnn=False`
- **PaddleOCR 3.4.0**: Breaking API changes from 2.x (see memory for details)
- **GPU OCR**: RTX 5090 too new for paddlepaddle-gpu -> use RapidOCR+ONNX instead
- **paddle2onnx 2.1.0**: DLL incompatible with paddlepaddle 3.3.0 on Windows -> use RapidOCR's bundled PP-OCRv4 ONNX models
- **String coercion**: OCR/Claude returns strings for numeric values -> must `float()` coerce at all comparison points
- **config.json**: Contains API key -> git-ignored, never commit

## Recent Changes (latest first)

- Archive output switched from multi-page TIFF to per-page JPG (`_page_NN` suffix); `tiff_export.py` → `image_export.py`; config keys `tiff_dpi`/`tiff_compression` → `image_dpi`/`image_quality` (legacy keys auto-migrate)
- Re-Extract button to re-run full pipeline on current file
- Yield strength double-conversion fix + material-aware YS/TS sanity check
- Split ES-M0003G into 5 supplier-specific Super 13Cr specs
- Staging TIFF fix for heat numbers containing slashes
- Assembly trigger keyword change (DOCS -> assy)
- Assembly COC detection: combined page classify + heat extract
- Archive PDF 2x size bloat fix with dual-strategy compression
- Standardized output naming YYYY.MM.PO#.LN#.ID, PDF export, keyword spec matching
- Yield strength corruption fix (mislabeled MPa unit)
- Rotated PDF fix, Sonnet 4.6 upgrade, compact notation correction
- German/Japanese MTR extraction support
- Opus precision pass for chemistry/mechanical tables
- GPU OCR via RapidOCR + ONNX Runtime CUDA
