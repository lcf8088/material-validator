"""
Shared specification loader - single source of truth for specs.
"""

import yaml
from pathlib import Path
from typing import Dict, Optional, List


class SpecLoader:
    """
    Centralized spec loader with caching.
    Use get_instance() for singleton access across modules.
    """
    
    _instance: Optional['SpecLoader'] = None
    
    def __init__(self, specs_dir: Optional[str] = None):
        if specs_dir is None:
            specs_dir = Path(__file__).parent.parent.parent / 'specs'
        self.specs_dir = Path(specs_dir)
        self._specs: Dict[str, dict] = {}
        self._load_all()
    
    @classmethod
    def get_instance(cls, specs_dir: Optional[str] = None) -> 'SpecLoader':
        """Get singleton instance of SpecLoader."""
        if cls._instance is None:
            cls._instance = cls(specs_dir)
        return cls._instance
    
    @classmethod
    def reset_instance(cls):
        """Reset singleton (useful for testing)."""
        cls._instance = None
    
    def _load_all(self) -> None:
        """Load all YAML spec files from directory."""
        self._specs.clear()
        
        if not self.specs_dir.exists():
            raise FileNotFoundError(f"Specs directory not found: {self.specs_dir}")
        
        for spec_file in self.specs_dir.glob('*.yaml'):
            try:
                with open(spec_file) as f:
                    spec = yaml.safe_load(f)
                    if spec and 'id' in spec:
                        self._specs[spec['id']] = spec
            except Exception as e:
                print(f"Warning: Failed to load {spec_file}: {e}")
    
    def get(self, spec_id: str) -> Optional[dict]:
        """Get a spec by ID."""
        return self._specs.get(spec_id)
    
    def list_ids(self) -> List[str]:
        """List all available spec IDs."""
        return list(self._specs.keys())
    
    def all_specs(self) -> Dict[str, dict]:
        """Get all specs as a dictionary."""
        return self._specs.copy()
    
    def reload(self) -> None:
        """Reload all specs from disk."""
        self._load_all()
    
    def get_by_uns(self, uns: str) -> List[dict]:
        """Find specs matching a UNS number."""
        uns = uns.upper().strip()
        return [
            spec for spec in self._specs.values()
            if spec.get('uns', '').upper().strip() == uns
        ]
    
    def get_by_grade(self, grade: str) -> List[dict]:
        """Find specs that include a specific grade."""
        grade = grade.upper().strip()
        matches = []
        for spec in self._specs.values():
            spec_grades = [g.upper() for g in spec.get('grades', [])]
            if grade in spec_grades:
                matches.append(spec)
            elif any(grade in g or g in grade for g in spec_grades):
                matches.append(spec)
        return matches
