"""
Test 16: CLI - validate.py command-line interface.
"""

import subprocess
import sys
import pytest
from pathlib import Path

CLI = str(Path(__file__).parent.parent / "validate.py")


def run_cli(*args, timeout=15):
    """Run validate.py with arguments and return result."""
    result = subprocess.run(
        [sys.executable, CLI] + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(Path(__file__).parent.parent),
    )
    return result


class TestCLIInfo:
    def test_list_specs(self):
        r = run_cli("--list-specs")
        assert r.returncode == 0
        assert "ES-M0001C" in r.stdout
        assert "ES-M0001G" in r.stdout
        assert "ES-M0003A" in r.stdout

    def test_show_spec(self):
        r = run_cli("--show-spec", "ES-M0001C")
        assert r.returncode == 0
        assert "ES-M0001C" in r.stdout
        assert "CHEMISTRY" in r.stdout

    def test_show_nonexistent_spec(self):
        r = run_cli("--show-spec", "FAKE")
        assert "not found" in r.stdout.lower() or "error" in r.stdout.lower()

    def test_help(self):
        r = run_cli("--help")
        assert r.returncode == 0
        assert "validate" in r.stdout.lower() or "usage" in r.stdout.lower()


class TestCLIValidation:
    def test_validate_json_with_spec(self):
        json_path = str(Path(__file__).parent / "mtrs" / "heat-D2213660-4140.json")
        r = run_cli("--json", json_path, "--spec", "ES-M0001G")
        assert r.returncode in (0, 1, 2)  # PASS, INCOMPLETE, or FAIL
        assert "VALIDATION REPORT" in r.stdout or "heat" in r.stdout.lower()

    def test_validate_json_auto_detect(self):
        json_path = str(Path(__file__).parent / "mtrs" / "heat-D2213660-4140.json")
        r = run_cli("--json", json_path, "--auto")
        assert r.returncode in (0, 1, 2)
        assert "Auto-detected" in r.stdout or "VALIDATION" in r.stdout

    def test_validate_json_output_json(self):
        json_path = str(Path(__file__).parent / "mtrs" / "heat-D2213660-4140.json")
        r = run_cli("--json", json_path, "--spec", "ES-M0001C", "--output-json")
        assert r.returncode in (0, 1, 2)
        import json
        data = json.loads(r.stdout)
        assert "overall_status" in data

    def test_validate_303(self):
        json_path = str(Path(__file__).parent / "mtrs" / "heat-Y75T-303ss.json")
        r = run_cli("--json", json_path, "--spec", "ES-M0003A")
        assert r.returncode in (0, 1, 2)

    def test_validate_no_spec_no_auto(self):
        json_path = str(Path(__file__).parent / "mtrs" / "heat-D2213660-4140.json")
        r = run_cli("--json", json_path)
        assert r.returncode != 0
        assert "No specification" in r.stdout or "error" in r.stdout.lower()

    def test_nonexistent_json(self):
        r = run_cli("--json", "/nonexistent.json", "--spec", "ES-M0001C")
        assert r.returncode != 0

    def test_no_args_shows_help(self):
        r = run_cli()
        assert r.returncode != 0
        assert "usage" in r.stdout.lower() or "validate" in r.stdout.lower()


class TestCLIPdfConversion:
    def test_pdf_conversion_nonexistent(self):
        r = run_cli("--pdf", "/nonexistent.pdf")
        assert r.returncode != 0

    def test_pdf_conversion_real(self, tmp_path):
        """Create a minimal PDF and convert it."""
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Test")
        pdf_path = str(tmp_path / "test.pdf")
        doc.save(pdf_path)
        doc.close()

        r = run_cli("--pdf", pdf_path)
        assert r.returncode == 0
        assert "Converted" in r.stdout


class TestCLINoColor:
    def test_no_color_flag(self):
        json_path = str(Path(__file__).parent / "mtrs" / "heat-D2213660-4140.json")
        r = run_cli("--json", json_path, "--spec", "ES-M0001C", "--no-color")
        assert "\033[" not in r.stdout  # No ANSI escape codes
