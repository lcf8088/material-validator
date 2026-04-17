"""
Configuration management for Material Validator GUI.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any

DEFAULT_CONFIG = {
    'archive_folder': '',
    'anthropic_api_key': '',
    'watch_folder': '',
    'paddle_model_path': '',
    'preprocessing_dpi': 300,
    'auto_detect_spec': True,
    'default_spec': '',
    'image_dpi': 300,
    'window_width': 1000,
    'window_height': 700,
    'theme': 'dark',
    'last_input_folder': '',
    'specs_folder': '',
    'auto_archive': True,
    'organize_by_po': False,
    'watch_auto_process': True,
    'extraction_model': 'sonnet',
    'use_gpu_ocr': True,
}


class Config:
    """Manages application configuration with persistence."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            # Default to project root (next to validate.py)
            config_path = Path(__file__).parent.parent.parent / 'config.json'

        self.config_path = Path(config_path)
        self._config = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load config from file or create default."""
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    loaded = json.load(f)
                # Merge with defaults (in case new fields added)
                config = DEFAULT_CONFIG.copy()
                config.update(loaded)
                # Remove legacy keys that no longer apply
                for legacy_key in ('vision_provider', 'vision_api_key', 'vision_model',
                                   'vision_endpoint'):
                    config.pop(legacy_key, None)
                # Migrate legacy keys
                old_dpi = config.pop('tiff_dpi', None)
                if old_dpi and 'image_dpi' not in loaded:
                    config['image_dpi'] = old_dpi
                config.pop('tiff_compression', None)
                config.pop('image_quality', None)
                # Migrate: output_folder was merged into archive_folder
                old_output = config.pop('output_folder', '')
                if old_output and not config.get('archive_folder'):
                    config['archive_folder'] = old_output
                return config
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    def save(self):
        """Save config to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(self._config, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        """Set config value and save."""
        self._config[key] = value
        self.save()

    def update(self, values: Dict[str, Any]):
        """Update multiple values and save."""
        self._config.update(values)
        self.save()

    @property
    def archive_folder(self) -> str:
        return self._config.get('archive_folder', '')

    @archive_folder.setter
    def archive_folder(self, value: str):
        self.set('archive_folder', value)

    @property
    def anthropic_api_key(self) -> str:
        return self._config.get('anthropic_api_key', '')

    @anthropic_api_key.setter
    def anthropic_api_key(self, value: str):
        self.set('anthropic_api_key', value)

    @property
    def watch_folder(self) -> str:
        return self._config.get('watch_folder', '')

    @watch_folder.setter
    def watch_folder(self, value: str):
        self.set('watch_folder', value)

    @property
    def effective_output_folder(self) -> str:
        """Output/archive folder for approved JPG pages."""
        return self._config.get('archive_folder', '')

    @property
    def extraction_model(self) -> str:
        return self._config.get('extraction_model', 'sonnet')

    @extraction_model.setter
    def extraction_model(self, value: str):
        self.set('extraction_model', value)

    def is_configured(self) -> bool:
        """Check if minimum required settings are configured."""
        if not self.archive_folder:
            return False
        if not self.anthropic_api_key:
            return False
        return True
