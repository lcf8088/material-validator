"""
Vision API abstraction layer - supports multiple providers for MTR extraction.
"""

import base64
import json
import httpx
from pathlib import Path
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod

from lib.extractor import get_extraction_prompt, parse_extraction_response, normalize_extracted_data


class VisionProvider(ABC):
    """Abstract base class for vision API providers."""
    
    @abstractmethod
    def extract_mtr(self, image_path: str) -> Dict[str, Any]:
        """Extract MTR data from image. Returns normalized dict or error."""
        pass
    
    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """Test API connection. Returns (success, message)."""
        pass
    
    def _load_image_base64(self, image_path: str) -> tuple[str, str]:
        """Load image and return (base64_data, media_type)."""
        path = Path(image_path)
        
        suffix = path.suffix.lower()
        media_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg', 
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
        }
        media_type = media_types.get(suffix, 'image/jpeg')
        
        with open(path, 'rb') as f:
            data = base64.standard_b64encode(f.read()).decode('utf-8')
        
        return data, media_type


class OpenAIVision(VisionProvider):
    """OpenAI GPT-4 Vision provider."""
    
    def __init__(self, api_key: str, model: str = 'gpt-4o'):
        self.api_key = api_key
        self.model = model
        self.base_url = 'https://api.openai.com/v1'
    
    def extract_mtr(self, image_path: str) -> Dict[str, Any]:
        try:
            image_data, media_type = self._load_image_base64(image_path)
            
            response = httpx.post(
                f'{self.base_url}/chat/completions',
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': self.model,
                    'messages': [
                        {
                            'role': 'user',
                            'content': [
                                {'type': 'text', 'text': get_extraction_prompt()},
                                {
                                    'type': 'image_url',
                                    'image_url': {
                                        'url': f'data:{media_type};base64,{image_data}'
                                    }
                                }
                            ]
                        }
                    ],
                    'max_tokens': 4096,
                },
                timeout=60.0,
            )
            
            response.raise_for_status()
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            parsed = parse_extraction_response(content)
            return normalize_extracted_data(parsed)
            
        except Exception as e:
            return {'_extraction_status': 'error', '_error': str(e)}
    
    def test_connection(self) -> tuple[bool, str]:
        try:
            response = httpx.get(
                f'{self.base_url}/models',
                headers={'Authorization': f'Bearer {self.api_key}'},
                timeout=10.0,
            )
            response.raise_for_status()
            return True, "Connected to OpenAI API"
        except Exception as e:
            return False, f"Connection failed: {e}"


class AnthropicVision(VisionProvider):
    """Anthropic Claude Vision provider."""
    
    def __init__(self, api_key: str, model: str = 'claude-sonnet-4-5'):
        self.api_key = api_key
        self.model = model
        self.base_url = 'https://api.anthropic.com/v1'
    
    def extract_mtr(self, image_path: str) -> Dict[str, Any]:
        try:
            image_data, media_type = self._load_image_base64(image_path)
            
            response = httpx.post(
                f'{self.base_url}/messages',
                headers={
                    'x-api-key': self.api_key,
                    'anthropic-version': '2023-06-01',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': self.model,
                    'max_tokens': 4096,
                    'messages': [
                        {
                            'role': 'user',
                            'content': [
                                {
                                    'type': 'image',
                                    'source': {
                                        'type': 'base64',
                                        'media_type': media_type,
                                        'data': image_data,
                                    }
                                },
                                {
                                    'type': 'text',
                                    'text': get_extraction_prompt()
                                }
                            ]
                        }
                    ]
                },
                timeout=60.0,
            )
            
            response.raise_for_status()
            result = response.json()
            content = result['content'][0]['text']
            
            parsed = parse_extraction_response(content)
            return normalize_extracted_data(parsed)
            
        except Exception as e:
            return {'_extraction_status': 'error', '_error': str(e)}
    
    def test_connection(self) -> tuple[bool, str]:
        try:
            # Anthropic doesn't have a simple test endpoint, try a minimal request
            response = httpx.post(
                f'{self.base_url}/messages',
                headers={
                    'x-api-key': self.api_key,
                    'anthropic-version': '2023-06-01',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': self.model,
                    'max_tokens': 10,
                    'messages': [{'role': 'user', 'content': 'Hi'}]
                },
                timeout=10.0,
            )
            response.raise_for_status()
            return True, "Connected to Anthropic API"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return False, "Invalid API key"
            return False, f"API error: {e.response.status_code}"
        except Exception as e:
            return False, f"Connection failed: {e}"


class GoogleVision(VisionProvider):
    """Google Gemini Vision provider."""
    
    def __init__(self, api_key: str, model: str = 'gemini-2.0-flash'):
        self.api_key = api_key
        self.model = model
    
    def extract_mtr(self, image_path: str) -> Dict[str, Any]:
        try:
            image_data, media_type = self._load_image_base64(image_path)
            
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent'
            
            response = httpx.post(
                url,
                params={'key': self.api_key},
                json={
                    'contents': [
                        {
                            'parts': [
                                {'text': get_extraction_prompt()},
                                {
                                    'inline_data': {
                                        'mime_type': media_type,
                                        'data': image_data
                                    }
                                }
                            ]
                        }
                    ],
                    'generationConfig': {
                        'maxOutputTokens': 4096,
                    }
                },
                timeout=60.0,
            )
            
            response.raise_for_status()
            result = response.json()
            content = result['candidates'][0]['content']['parts'][0]['text']
            
            parsed = parse_extraction_response(content)
            return normalize_extracted_data(parsed)
            
        except Exception as e:
            return {'_extraction_status': 'error', '_error': str(e)}
    
    def test_connection(self) -> tuple[bool, str]:
        try:
            url = f'https://generativelanguage.googleapis.com/v1beta/models'
            response = httpx.get(url, params={'key': self.api_key}, timeout=10.0)
            response.raise_for_status()
            return True, "Connected to Google AI API"
        except Exception as e:
            return False, f"Connection failed: {e}"


class LocalVision(VisionProvider):
    """Local vision provider (Ollama, LMStudio, etc.)."""
    
    def __init__(self, endpoint: str = 'http://localhost:11434', model: str = 'llava'):
        self.endpoint = endpoint.rstrip('/')
        self.model = model
    
    def extract_mtr(self, image_path: str) -> Dict[str, Any]:
        try:
            image_data, _ = self._load_image_base64(image_path)
            
            # Ollama-style API
            response = httpx.post(
                f'{self.endpoint}/api/generate',
                json={
                    'model': self.model,
                    'prompt': get_extraction_prompt(),
                    'images': [image_data],
                    'stream': False,
                },
                timeout=120.0,  # Local models can be slower
            )
            
            response.raise_for_status()
            result = response.json()
            content = result.get('response', '')
            
            parsed = parse_extraction_response(content)
            return normalize_extracted_data(parsed)
            
        except Exception as e:
            return {'_extraction_status': 'error', '_error': str(e)}
    
    def test_connection(self) -> tuple[bool, str]:
        try:
            response = httpx.get(f'{self.endpoint}/api/tags', timeout=5.0)
            response.raise_for_status()
            return True, f"Connected to local server at {self.endpoint}"
        except Exception as e:
            return False, f"Connection failed: {e}"


def create_vision_provider(
    provider: str,
    api_key: str = '',
    model: str = '',
    endpoint: str = ''
) -> VisionProvider:
    """Factory function to create vision provider instance."""
    
    if provider == 'openai':
        return OpenAIVision(api_key, model or 'gpt-4o')
    elif provider == 'anthropic':
        return AnthropicVision(api_key, model or 'claude-sonnet-4-5')
    elif provider == 'google':
        return GoogleVision(api_key, model or 'gemini-2.0-flash')
    elif provider == 'local':
        return LocalVision(endpoint or 'http://localhost:11434', model or 'llava')
    else:
        raise ValueError(f"Unknown provider: {provider}")
