"""
Test 09: Config - Configuration management and migration.
"""

import json
import pytest
from gui.config import Config, DEFAULT_CONFIG


class TestConfigDefaults:
    def test_default_config_has_required_keys(self):
        required = [
            "archive_folder", "anthropic_api_key", "watch_folder",
            "paddle_model_path", "preprocessing_dpi", "auto_detect_spec",
            "tiff_dpi", "tiff_compression", "theme",
        ]
        for key in required:
            assert key in DEFAULT_CONFIG, f"Missing default key: {key}"

    def test_no_legacy_keys_in_defaults(self):
        """Defaults should not contain old vision_provider keys."""
        legacy = ["vision_provider", "vision_api_key", "vision_model", "vision_endpoint"]
        for key in legacy:
            assert key not in DEFAULT_CONFIG, f"Legacy key still in defaults: {key}"


class TestConfigLoadSave:
    def test_load_new_config(self, sample_config):
        cfg = Config(sample_config)
        assert cfg.anthropic_api_key == "sk-ant-test-key-1234"
        assert cfg.get("preprocessing_dpi") == 300

    def test_load_nonexistent_uses_defaults(self, tmp_path):
        cfg = Config(str(tmp_path / "nonexistent.json"))
        assert cfg.anthropic_api_key == ""
        assert cfg.get("tiff_dpi") == 300

    def test_save_and_reload(self, tmp_path):
        path = str(tmp_path / "test_config.json")
        cfg = Config(path)
        cfg.set("anthropic_api_key", "test-key-999")

        cfg2 = Config(path)
        assert cfg2.anthropic_api_key == "test-key-999"

    def test_update_multiple(self, tmp_path):
        path = str(tmp_path / "test_config.json")
        cfg = Config(path)
        cfg.update({"tiff_dpi": 200, "theme": "light"})
        assert cfg.get("tiff_dpi") == 200
        assert cfg.get("theme") == "light"


class TestLegacyConfigMigration:
    def test_legacy_keys_stripped_on_load(self, legacy_config):
        """Loading a config with old vision_provider keys should strip them."""
        cfg = Config(legacy_config)
        assert cfg.get("vision_provider") is None
        assert cfg.get("vision_api_key") is None
        assert cfg.get("vision_model") is None

    def test_legacy_config_gets_new_defaults(self, legacy_config):
        """Legacy config should get new default keys filled in."""
        cfg = Config(legacy_config)
        assert cfg.get("anthropic_api_key") is not None  # Should exist (empty default)
        assert cfg.get("watch_folder") is not None
        assert cfg.get("preprocessing_dpi") == 300

    def test_legacy_preserved_values_kept(self, legacy_config):
        """Non-legacy values should be preserved during migration."""
        cfg = Config(legacy_config)
        assert cfg.get("tiff_dpi") == 150  # From legacy config
        assert cfg.get("theme") == "dark"


class TestIsConfigured:
    def test_fully_configured(self, sample_config):
        cfg = Config(sample_config)
        assert cfg.is_configured()

    def test_no_archive_folder(self, tmp_path):
        path = str(tmp_path / "cfg.json")
        cfg = Config(path)
        cfg.update({"anthropic_api_key": "key", "archive_folder": ""})
        assert not cfg.is_configured()

    def test_no_api_key(self, tmp_path):
        path = str(tmp_path / "cfg.json")
        cfg = Config(path)
        cfg.update({"anthropic_api_key": "", "archive_folder": "/some/path"})
        assert not cfg.is_configured()


class TestConfigProperties:
    def test_archive_folder_property(self, sample_config):
        cfg = Config(sample_config)
        original = cfg.archive_folder
        cfg.archive_folder = "/new/path"
        assert cfg.archive_folder == "/new/path"

    def test_anthropic_api_key_property(self, sample_config):
        cfg = Config(sample_config)
        cfg.anthropic_api_key = "new-key"
        assert cfg.anthropic_api_key == "new-key"

    def test_watch_folder_property(self, sample_config):
        cfg = Config(sample_config)
        cfg.watch_folder = "/watch/here"
        assert cfg.watch_folder == "/watch/here"
