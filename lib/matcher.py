"""
Spec matcher - auto-detect which specification an MTR should be validated against.

Logic:
1. Match by UNS number (most reliable)
2. Match by material grade name
3. If multiple specs match same material, use mechanical properties to differentiate
   (e.g., 4140 standard vs 4140 110MYS - check yield strength range)
"""

from typing import Optional, List, Tuple, Dict, Any

from .spec_loader import SpecLoader
from .validator import PROPERTY_ALIASES


# Type alias for match result
MatchResult = Tuple[str, float, str]  # (spec_id, confidence, reason)

# Scoring constants for spec matching
CONFIDENCE_UNS_MATCH = 0.9
CONFIDENCE_GRADE_EXACT = 0.8
CONFIDENCE_GRADE_PARTIAL = 0.6
SCORE_RANGE_FIT = 0.1
SCORE_MEETS_MIN = 0.05
SCORE_BELOW_MIN = -0.2
SCORE_HIGH_STRENGTH_MATCH = 0.15
SCORE_MED_STRENGTH_MATCH = 0.05


class SpecMatcher:
    """Auto-detects the best specification for an MTR."""
    
    def __init__(self, specs_dir: Optional[str] = None):
        self.loader = SpecLoader.get_instance(specs_dir)
    
    def find_matching_specs(self, mtr_data: Dict[str, Any]) -> List[MatchResult]:
        """
        Find all specs that could potentially match this MTR.
        
        Args:
            mtr_data: Extracted MTR data with 'uns', 'material_grade', 'mechanical', etc.
            
        Returns:
            List of (spec_id, confidence, reason) tuples, sorted by confidence desc.
        """
        matches = []
        
        mtr_uns = (mtr_data.get('uns') or '').upper().strip()
        mtr_grade = (mtr_data.get('material_grade') or '').upper().strip()
        
        for spec_id, spec in self.loader.all_specs().items():
            match = self._check_spec_match(spec_id, spec, mtr_uns, mtr_grade)
            if match:
                matches.append(match)
        
        # Sort by confidence descending
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches
    
    def _check_spec_match(self, spec_id: str, spec: dict, mtr_uns: str, mtr_grade: str) -> Optional[MatchResult]:
        """Check if a single spec matches the MTR identifiers."""
        spec_uns = (spec.get('uns') or '').upper().strip()
        spec_grades = [g.upper() for g in spec.get('grades', [])]
        
        # UNS match (highest confidence)
        if mtr_uns and spec_uns and mtr_uns == spec_uns:
            return (spec_id, CONFIDENCE_UNS_MATCH, f"UNS match: {mtr_uns}")
        
        # Grade match
        if mtr_grade:
            # Exact match
            if mtr_grade in spec_grades:
                return (spec_id, CONFIDENCE_GRADE_EXACT, f"Grade match: {mtr_grade}")
            
            # Partial match (grade contained in spec grades or vice versa)
            for sg in spec_grades:
                if mtr_grade in sg or sg in mtr_grade:
                    return (spec_id, CONFIDENCE_GRADE_PARTIAL, f"Partial grade match: {mtr_grade} ~ {sg}")
        
        return None
    
    def select_best_spec(self, mtr_data: Dict[str, Any]) -> Optional[MatchResult]:
        """
        Select the single best spec for this MTR.
        Uses mechanical properties to differentiate when multiple specs match.
        
        Args:
            mtr_data: Extracted MTR data
            
        Returns:
            (spec_id, confidence, reason) or None if no match.
        """
        matches = self.find_matching_specs(mtr_data)
        
        if not matches:
            return None
        
        if len(matches) == 1:
            return matches[0]
        
        # Multiple matches - need to differentiate by mechanical properties
        mtr_ys = self._get_yield_strength(mtr_data)
        
        if mtr_ys is not None:
            best = self._select_by_yield_strength(matches, mtr_ys)
            if best:
                return best
        
        # No mechanical differentiation possible, return highest confidence match
        return matches[0]
    
    def _get_yield_strength(self, mtr_data: Dict[str, Any]) -> Optional[float]:
        """Extract yield strength from MTR data."""
        mech = mtr_data.get('mechanical', {})
        
        # Try common field names from shared aliases
        for key in PROPERTY_ALIASES.get('yield_strength', ['yield_strength']):
            if key in mech:
                val = mech[key]
                if isinstance(val, dict):
                    return val.get('value')
                return val
        
        return None
    
    def _select_by_yield_strength(self, matches: List[MatchResult], mtr_ys: float) -> Optional[MatchResult]:
        """
        Select best spec when multiple match, using yield strength to differentiate.
        
        For materials like 4140 with multiple specs (standard vs 110MYS),
        prefer the spec whose YS requirement best matches the actual value.
        """
        best_match = None
        best_score = -float('inf')
        
        for spec_id, confidence, reason in matches:
            spec = self.loader.get(spec_id)
            if not spec:
                continue
            
            mech = spec.get('mechanical', {})
            ys_spec = mech.get('yield_strength', {})
            
            ys_min = ys_spec.get('min', 0)
            ys_max = ys_spec.get('max', float('inf'))
            
            # Calculate fit score
            score = confidence
            
            if ys_min <= mtr_ys <= ys_max:
                # Perfect fit within range
                score += SCORE_RANGE_FIT
            elif mtr_ys >= ys_min:
                # Meets minimum, might exceed max (valid for min-only specs)
                score += SCORE_MEETS_MIN
            else:
                # Below minimum - poor fit
                score += SCORE_BELOW_MIN

            # Prefer higher-requirement specs when material meets them
            # This ensures 110 MYS material gets matched to ES-M0001G, not ES-M0001C
            if mtr_ys >= 110 and ys_min >= 110:
                score += SCORE_HIGH_STRENGTH_MATCH
            elif mtr_ys >= 80 and ys_min >= 80 and ys_min < 110:
                score += SCORE_MED_STRENGTH_MATCH
            
            if score > best_score:
                best_score = score
                best_match = (spec_id, score, f"{reason} (YS={mtr_ys:.1f} fits min={ys_min})")
        
        return best_match
    
    def get_spec_summary(self, spec_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of a spec for display."""
        spec = self.loader.get(spec_id)
        if not spec:
            return None
        
        return {
            'id': spec_id,
            'material': spec.get('material', ''),
            'uns': spec.get('uns', ''),
            'grades': spec.get('grades', []),
            'condition': spec.get('condition', ''),
        }
    
    def suggest_specs(self, partial_grade: str) -> List[Dict[str, Any]]:
        """
        Suggest specs that might match a partial grade name.
        Useful for CLI tab completion or fuzzy matching.
        """
        partial = partial_grade.upper().strip()
        suggestions = []
        
        for spec_id, spec in self.loader.all_specs().items():
            material = spec.get('material', '')
            grades = spec.get('grades', [])
            
            # Check if partial matches material name or any grade
            if partial in material.upper():
                suggestions.append(self.get_spec_summary(spec_id))
            elif any(partial in g.upper() for g in grades):
                suggestions.append(self.get_spec_summary(spec_id))
        
        return suggestions
