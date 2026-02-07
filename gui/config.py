"""
Configuration management for Material Validator GUI.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any

DEFAULT_CONFIG = {
    'archive_folder': '',
    'vision_provider': 'openai',  # openai, anthropic, google, local
    'vision_api_key': '',
    'vision_model': '',
    'auto_detect_spec': True,
    'default_spec': '',
    'tiff_dpi': 300,
    'tiff_compression': 'lzw',
    'window_width': 1000,
    'window_height': 700,
    'theme': 'dark',
    'last_input_folder': '',
    'specs_folder': '',
}

VISION_PROVIDERS = {
    'openai': {
        'name': 'OpenAI GPT-4 Vision',
        'models': ['gpt-4o', 'gpt-4-turbo'],
        'requires_key': True,
    },
    'anthropic': {
        'name': 'Anthropic Claude Vision', 
        'models': ['claude-sonnet-4-5', 'claude-sonnet-4-20250514'],
        'requires_key': True,
    },
    'google': {
        'name': 'Google Gemini Vision',
        'models': ['gemini-2.0-flash', 'gemini-1.5-pro'],
        'requires_key': True,
    },
    'local': {
        'name': 'Local (Ollama/LMStudio)',
        'models': ['llava', 'bakllava', 'llava-phi3'],
        'requires_key': False,
        'requires_endpoint': True,
    },
}


class Config:
    """Manages application configuration with persistence."""
    
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            # Default to project root (next to validate.py)
            config_path = Path(__file__).parent.parent / 'config.json'

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
    def vision_provider(self) -> str:
        return self._config.get('vision_provider', 'openai')
    
    @vision_provider.setter
    def vision_provider(self, value: str):
        self.set('vision_provider', value)
    
    @property
    def vision_api_key(self) -> str:
        return self._config.get('vision_api_key', '')
    
    @vision_api_key.setter
    def vision_api_key(self, value: str):
        self.set('vision_api_key', value)
    
    def is_configured(self) -> bool:
        """Check if minimum required settings are configured."""
        if not self.archive_folder:
            return False
        
        provider = VISION_PROVIDERS.get(self.vision_provider, {})
        if provider.get('requires_key') and not self.vision_api_key:
            return False
        
        return True
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Get info about current vision provider."""
        return VISION_PROVIDERS.get(self.vision_provider, {})
