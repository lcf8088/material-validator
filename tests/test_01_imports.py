"""
Test 01: Import smoke tests.

Verify every module can be imported without errors.
This catches syntax errors, missing dependencies in non-optional code paths,
and circular imports.
"""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


CORE_MODULES = [
    "lib.spec_loader",
    "lib.validator",
    "lib.matcher",
    "lib.sanity",
    "lib.converters",
    "lib.extractor",
    "lib.history",
]

NEW_MODULES = [
    "lib.preprocessor",
    "lib.paddle_ocr",
    "lib.claude_parser",
    "lib.pipeline",
    "lib.watcher",
]

GUI_MODULES = [
    "gui.config",
    "gui.tiff_export",
    # gui.app and gui.settings require tkinter which may not be available in CI
]


class TestCoreImports:
    """All core lib modules should import cleanly."""

    @pytest.mark.parametrize("module", CORE_MODULES)
    def test_core_import(self, module):
        mod = importlib.import_module(module)
        assert mod is not None


class TestNewModuleImports:
    """New pipeline modules should import cleanly (dependencies may be mocked)."""

    @pytest.mark.parametrize("module", NEW_MODULES)
    def test_new_module_import(self, module):
        mod = importlib.import_module(module)
        assert mod is not None


class TestGUIImports:
    """GUI modules should import cleanly."""

    @pytest.mark.parametrize("module", GUI_MODULES)
    def test_gui_import(self, module):
        mod = importlib.import_module(module)
        assert mod is not None


class TestLibInit:
    """lib/__init__.py should export all expected names."""

    def test_lib_exports(self):
        import lib
        expected = [
            "SpecLoader", "SpecValidator", "CertValidation", "ValidationResult",
            "format_validation_report", "SpecMatcher",
            "convert_stress", "normalize_hardness",
            "pdf_to_images", "parse_extraction_response", "normalize_extracted_data",
            "run_all_sanity_checks", "format_sanity_report",
            "ValidationHistory", "process_document", "PipelineResult", "FolderWatcher",
        ]
        for name in expected:
            assert hasattr(lib, name), f"lib missing export: {name}"
