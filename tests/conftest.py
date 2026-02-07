"""Shared fixtures for the test suite."""

import json
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def specs_dir():
    return str(PROJECT_ROOT / "specs")


@pytest.fixture
def mtr_4140():
    """Load the 4140 test MTR JSON."""
    with open(PROJECT_ROOT / "tests" / "mtrs" / "heat-D2213660-4140.json") as f:
        return json.load(f)


@pytest.fixture
def mtr_303():
    """Load the 303 SS test MTR JSON."""
    with open(PROJECT_ROOT / "tests" / "mtrs" / "heat-Y75T-303ss.json") as f:
        return json.load(f)


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for test outputs."""
    return tmp_path


@pytest.fixture
def sample_config(tmp_path):
    """Create a temporary config.json for testing."""
    config_data = {
        "archive_folder": str(tmp_path / "archive"),
        "anthropic_api_key": "sk-ant-test-key-1234",
        "watch_folder": str(tmp_path / "watch"),
        "paddle_model_path": "",
        "preprocessing_dpi": 300,
        "auto_detect_spec": True,
        "tiff_dpi": 300,
        "tiff_compression": "lzw",
        "theme": "dark",
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    return str(config_path)


@pytest.fixture
def legacy_config(tmp_path):
    """Create a config.json with legacy vision_provider keys."""
    config_data = {
        "archive_folder": str(tmp_path / "archive"),
        "vision_provider": "google",
        "vision_api_key": "old-key-12345",
        "vision_model": "gemini-2.0-flash",
        "tiff_dpi": 150,
        "tiff_compression": "lzw",
        "theme": "dark",
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    return str(config_path)
