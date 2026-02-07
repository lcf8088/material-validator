"""
Test 13: Claude parser - Structured extraction and response parsing.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from lib.claude_parser import (
    _parse_response,
    _build_spec_context,
    _format_spec_as_text,
    parse_and_validate,
    EXTRACTION_PROMPT,
)


class TestParseResponse:
    """Test JSON parsing from Claude responses."""

    def test_clean_json(self):
        raw = json.dumps({"heat_number": "H1", "chemistry": {"C": 0.42}})
        result = _parse_response(raw)
        assert result["heat_number"] == "H1"
        assert result["_extraction_status"] == "success"

    def test_json_in_markdown_fence(self):
        raw = '```json\n{"heat_number": "H1"}\n```'
        result = _parse_response(raw)
        assert result["heat_number"] == "H1"

    def test_json_with_preamble(self):
        raw = 'Here is the extracted data:\n\n{"heat_number": "H1"}\n\nDone.'
        result = _parse_response(raw)
        assert result["heat_number"] == "H1"

    def test_invalid_json(self):
        result = _parse_response("This is not JSON")
        assert result["_extraction_status"] == "error"

    def test_empty_string(self):
        result = _parse_response("")
        assert result["_extraction_status"] == "error"

    def test_complex_response(self):
        data = {
            "heat_number": "D2213660",
            "material_grade": "4140",
            "chemistry": {"C": 0.42, "Cr": 1.08, "Mo": 0.25},
            "mechanical": {
                "yield_strength": 119.73,
                "tensile_strength": 149.45,
            },
            "compliance_flags": [],
        }
        raw = json.dumps(data)
        result = _parse_response(raw)
        assert result["heat_number"] == "D2213660"
        assert result["chemistry"]["Cr"] == 1.08


class TestBuildSpecContext:
    def test_no_spec_returns_empty(self):
        assert _build_spec_context(None) == ""
        assert _build_spec_context("") == ""

    def test_with_spec_returns_context(self):
        result = _build_spec_context("C: min=0.38, max=0.43", "ES-M0001C")
        assert "ES-M0001C" in result
        assert "SPEC CONTEXT" in result


class TestFormatSpecAsText:
    def test_formats_chemistry(self):
        spec = {
            "chemistry": {"C": {"min": 0.38, "max": 0.43}},
        }
        text = _format_spec_as_text(spec)
        assert "C:" in text
        assert "0.38" in text

    def test_formats_mechanical(self):
        spec = {
            "mechanical": {"yield_strength": {"min": 110, "unit": "ksi"}},
        }
        text = _format_spec_as_text(spec)
        assert "yield_strength" in text
        assert "110" in text

    def test_formats_special(self):
        spec = {
            "special_requirements": [
                {"type": "nace_compliance", "note": "Required"},
            ],
        }
        text = _format_spec_as_text(spec)
        assert "nace_compliance" in text

    def test_empty_spec(self):
        text = _format_spec_as_text({})
        assert text == ""


class TestExtractionPrompt:
    def test_prompt_has_required_fields(self):
        assert "heat_number" in EXTRACTION_PROMPT
        assert "chemistry" in EXTRACTION_PROMPT
        assert "mechanical" in EXTRACTION_PROMPT
        assert "OCR TEXT" in EXTRACTION_PROMPT

    def test_prompt_has_placeholders(self):
        assert "{ocr_text}" in EXTRACTION_PROMPT
        assert "{spec_context}" in EXTRACTION_PROMPT


class TestParseAndValidateMocked:
    """Test the full parse_and_validate with mocked Anthropic client."""

    def test_successful_parse(self):
        mock_anthropic = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps({
            "heat_number": "H1",
            "material_grade": "4140",
            "chemistry": {"C": 0.42},
            "mechanical": {"yield_strength": 120},
        }))]
        mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_message

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            # Re-import to pick up the mock
            import importlib
            import lib.claude_parser as cp
            importlib.reload(cp)
            result = cp.parse_and_validate("Heat: H1\nGrade: 4140", "test-api-key")

        assert result["heat_number"] == "H1"
        assert result["_extraction_status"] == "success"

    def test_with_spec_context(self):
        mock_anthropic = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"heat_number": "H1"}')]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            import importlib
            import lib.claude_parser as cp
            importlib.reload(cp)
            spec = {"chemistry": {"C": {"min": 0.38, "max": 0.43}}}
            result = cp.parse_and_validate("text", "key", spec=spec, spec_id="ES-M0001C")

        assert result["heat_number"] == "H1"

        # Verify spec context was included in the prompt
        call_args = mock_client.messages.create.call_args
        prompt_text = call_args[1]["messages"][0]["content"]
        assert "ES-M0001C" in prompt_text
