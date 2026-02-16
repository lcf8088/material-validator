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
    _encode_images,
    _resolve_model,
    parse_and_validate,
    EXTRACTION_PROMPT,
    MODEL_IDS,
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

    def test_prompt_has_vision_instructions(self):
        assert "IMAGES" in EXTRACTION_PROMPT
        assert "visual layout" in EXTRACTION_PROMPT


class TestModelResolution:
    def test_sonnet_resolves(self):
        assert _resolve_model("sonnet") == MODEL_IDS["sonnet"]

    def test_opus_resolves(self):
        assert _resolve_model("opus") == MODEL_IDS["opus"]

    def test_unknown_defaults_to_sonnet(self):
        assert _resolve_model("unknown") == MODEL_IDS["sonnet"]


class TestEncodeImages:
    def test_encode_existing_image(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 20)
        blocks = _encode_images([str(img)])
        assert len(blocks) == 1
        assert blocks[0]["type"] == "image"
        assert blocks[0]["source"]["media_type"] == "image/png"
        assert blocks[0]["source"]["type"] == "base64"

    def test_skip_missing_image(self):
        blocks = _encode_images(["/nonexistent/path.png"])
        assert len(blocks) == 0

    def test_max_pages_limit(self, tmp_path):
        paths = []
        for i in range(8):
            img = tmp_path / f"page{i}.png"
            img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 20)
            paths.append(str(img))
        blocks = _encode_images(paths)
        assert len(blocks) == 5  # MAX_IMAGE_PAGES


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
        # Content is now a list of blocks (multimodal), find the text block
        content = call_args[1]["messages"][0]["content"]
        if isinstance(content, list):
            prompt_text = next(b["text"] for b in content if b.get("type") == "text")
        else:
            prompt_text = content
        assert "ES-M0001C" in prompt_text

    def test_with_image_paths(self, tmp_path):
        img = tmp_path / "page1.png"
        img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 20)

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
            result = cp.parse_and_validate(
                "text", "key", image_paths=[str(img)], model="sonnet"
            )

        assert result["heat_number"] == "H1"

        # Verify image was included in request
        call_args = mock_client.messages.create.call_args
        content = call_args[1]["messages"][0]["content"]
        assert isinstance(content, list)
        image_blocks = [b for b in content if b.get("type") == "image"]
        assert len(image_blocks) == 1
        assert image_blocks[0]["source"]["media_type"] == "image/png"

    def test_model_selection(self):
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
            cp.parse_and_validate("text", "key", model="opus")

        call_args = mock_client.messages.create.call_args
        assert call_args[1]["model"] == "claude-opus-4-6"

    def test_fallback_strategy(self):
        mock_anthropic = MagicMock()
        # First call (sonnet) returns error, second call (opus) succeeds
        mock_error = MagicMock()
        mock_error.content = [MagicMock(text="not json at all")]
        mock_success = MagicMock()
        mock_success.content = [MagicMock(text='{"heat_number": "H1"}')]
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [mock_error, mock_success]
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            import importlib
            import lib.claude_parser as cp
            importlib.reload(cp)
            result = cp.parse_and_validate("text", "key", model="sonnet_with_opus_fallback")

        assert result["heat_number"] == "H1"
        assert result.get("_fallback_used") == "opus"
        assert mock_client.messages.create.call_count == 2
