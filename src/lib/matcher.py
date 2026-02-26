"""
Spec matcher - auto-detect which specification an MTR should be validated against.

Logic:
1. Gate by material type (metal vs polymer) — exclude impossible specs early
2. Primary: Score by chemistry fingerprint (most reliable — actual measured values)
3. Primary: Score by mechanical property fit (yield, tensile, hardness)
4. Boost: UNS number match adds confidence
5. Boost: Material grade name match adds confidence
6. Combine scores and apply minimum confidence threshold
"""

from typing import Optional, List, Tuple, Dict, Any

from .spec_loader import SpecLoader
from .validator import PROPERTY_ALIASES


# Type alias for match result
MatchResult = Tuple[str, float, str]  # (spec_id, confidence, reason)

# ---- Scoring weights ----
# Chemistry is the primary signal — it's the alloy fingerprint
WEIGHT_CHEMISTRY = 0.50
# Mechanical properties differentiate variants (e.g., 4140 80MYS vs 110MYS)
WEIGHT_MECHANICAL = 0.25
# UNS/grade are identity boosters — reliable when present, often missing/wrong
WEIGHT_IDENTITY = 0.25

# Identity sub-scores (within the identity weight)
SCORE_UNS_MATCH = 1.0
SCORE_GRADE_EXACT = 0.9
SCORE_GRADE_PARTIAL = 0.5
SCORE_GRADE_ALIAS = 0.9

# Confidence threshold — below this, return "no match"
CONFIDENCE_THRESHOLD = 0.40

# DDIC spec family number → material category mapping
# Derived from "DDIC Material Spec Reference.xlsx"
_NON_METAL_FAMILIES = {
    '0011',  # Plastics (Nylon)
    '1001',  # Elastomer - FKM / Viton
    '1101',  # Elastomer - FEPM / AFLAS
    '1301',  # Elastomer - HNBR / HSN
    '2001',  # Polymer - PTFE
    '2002',  # Polymer - PTFE filled
    '2201',  # Polymer - PEEK
    '2401',  # Polymer - iglide
}

# Metallic elements whose presence indicates a metal MTR
_METALLIC_ELEMENTS = {'Fe', 'Cr', 'Ni', 'Mo', 'Mn', 'Cu', 'Ti', 'Al', 'Co', 'W', 'Nb', 'V', 'Ta'}

# Key alloying elements that define steel families (weighted heavier)
_KEY_ELEMENTS = {'C', 'Cr', 'Ni', 'Mo', 'Mn', 'V', 'W', 'Cu', 'Nb', 'Ti', 'Co', 'Al'}

# Supplier / trade name aliases → standard grade names
_GRADE_ALIASES = {
    'CORRODUR 4021': ['420 MODIFIED', '420 MOD', '420'],
    'CORRODUR 4034': ['420'],
    'CORRODUR 4116': ['420 MODIFIED'],
    '1.4021': ['420'],
    '1.4028': ['420 MODIFIED'],
    'X20CR13': ['420', '13CR'],
    'X46CR13': ['420 MODIFIED'],
}


# Material keyword synonyms → canonical form (for polymer/elastomer matching)
_MATERIAL_SYNONYMS = {
    'TEFLON': 'PTFE',
    'POLYTETRAFLUOROETHYLENE': 'PTFE',
    'MOS2': 'MOLY',
    'MOLYBDENUM': 'MOLY',
    'MOLYBDENUM DISULFIDE': 'MOLY',
    'MOLY DISULFIDE': 'MOLY',
    'GLASS FIBER': 'GLASS',
    'GLASS FIBRE': 'GLASS',
    'FIBERGLASS': 'GLASS',
    'CARBON FIBER': 'CARBON',
    'CARBON FIBRE': 'CARBON',
    'VITON': 'FKM',
    'FLUOROELASTOMER': 'FKM',
    'AFLAS': 'FEPM',
    'PEEK': 'PEEK',
    'POLYETHERETHERKETONE': 'PEEK',
    'NYLON': 'NYLON',
    'POLYAMIDE': 'NYLON',
    'BUNA': 'NBR',
    'NITRILE': 'NBR',
    'HNBR': 'HNBR',
    'HSN': 'HNBR',
}

# Noise words to strip when extracting material keywords
_NOISE_WORDS = {'FILLED', 'COMPOUND', 'VIRGIN', 'MODIFIED', 'GRADE', 'TYPE',
                'TECH', 'FINE', 'WITH', 'AND', 'THE', 'OF', 'FOR', 'PLUS'}


def _extract_material_keywords(text: str) -> set:
    """Extract canonical material keywords from a text string.

    Tokenizes the text, applies synonym mapping, and returns a set
    of canonical material terms (e.g., 'PTFE', 'GLASS', 'MOLY').
    """
    import re
    text = text.upper()
    # Try multi-word synonyms first (longest match)
    for phrase, canonical in sorted(_MATERIAL_SYNONYMS.items(),
                                     key=lambda x: -len(x[0])):
        if phrase in text:
            text = text.replace(phrase, canonical)

    tokens = set(re.split(r'[^A-Z0-9]+', text)) - _NOISE_WORDS - {''}
    # Map remaining single-word synonyms, skip pure numbers and short tokens
    result = set()
    for t in tokens:
        if re.match(r'^\d+$', t):
            continue  # skip pure numbers (percentages, quantities)
        if len(t) < 3:
            continue  # skip very short tokens
        result.add(_MATERIAL_SYNONYMS.get(t, t))
    return result


def _extract_family_number(spec_id: str) -> str:
    """Extract the 4-digit family number from a DDIC spec ID."""
    import re
    m = re.search(r'M(\d{4})', spec_id)
    return m.group(1) if m else ''


class SpecMatcher:
    """Auto-detects the best specification for an MTR using chemistry-first matching."""

    def __init__(self, specs_dir: Optional[str] = None):
        self.loader = SpecLoader.get_instance(specs_dir)

    def find_matching_specs(self, mtr_data: Dict[str, Any]) -> List[MatchResult]:
        """
        Find all specs that could potentially match this MTR.

        Scores each spec using a weighted combination of:
        - Chemistry fingerprint (50%) — primary signal
        - Mechanical property fit (25%) — differentiates variants
        - UNS/grade identity (25%) — booster when present

        Returns:
            List of (spec_id, confidence, reason) tuples, sorted by confidence desc.
        """
        matches = []

        mtr_uns = (mtr_data.get('uns') or '').upper().strip()
        mtr_grade = (mtr_data.get('material_grade') or '').upper().strip()
        mtr_chem = mtr_data.get('chemistry', {})
        mtr_mech = mtr_data.get('mechanical', {})
        mtr_is_metallic = self._is_metallic(mtr_data)

        for spec_id, spec in self.loader.all_specs().items():
            # Material-type gating
            spec_is_non_metal = self._is_non_metal_spec(spec_id, spec)
            if mtr_is_metallic and spec_is_non_metal:
                continue
            if not mtr_is_metallic and not spec_is_non_metal and mtr_chem:
                continue

            # Score each dimension
            chem_score, chem_detail = self._score_chemistry(spec, mtr_chem)
            mech_score, mech_detail = self._score_mechanical(spec, mtr_mech)
            mtr_product_form = (mtr_data.get('product_form') or '').upper().strip()
            id_score, id_detail = self._score_identity(spec, mtr_uns, mtr_grade, mtr_product_form)

            # Weighted combination
            # If chemistry data is missing, shift weight to identity
            if not mtr_chem or chem_score < 0:
                total = id_score * (WEIGHT_IDENTITY + WEIGHT_CHEMISTRY) + mech_score * WEIGHT_MECHANICAL
            # If mechanical data is missing, shift weight to chemistry
            elif not mtr_mech or mech_score < 0:
                total = chem_score * (WEIGHT_CHEMISTRY + WEIGHT_MECHANICAL) + id_score * WEIGHT_IDENTITY
            else:
                total = (chem_score * WEIGHT_CHEMISTRY +
                         mech_score * WEIGHT_MECHANICAL +
                         id_score * WEIGHT_IDENTITY)

            if total >= CONFIDENCE_THRESHOLD:
                # Build reason string from contributing factors
                reasons = []
                if chem_detail:
                    reasons.append(chem_detail)
                if mech_detail:
                    reasons.append(mech_detail)
                if id_detail:
                    reasons.append(id_detail)
                reason = '; '.join(reasons) if reasons else f"score={total:.2f}"
                matches.append((spec_id, total, reason))

        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    # ------------------------------------------------------------------ Chemistry scoring
    def _score_chemistry(self, spec: dict, mtr_chem: Dict[str, Any]) -> Tuple[float, str]:
        """Score how well MTR chemistry fits a spec's chemistry ranges.

        Returns (score 0.0-1.0, detail string). Score -1 if no comparison possible.
        Key alloying elements are weighted 2x.
        """
        spec_chem = spec.get('chemistry', {})
        if not spec_chem or not mtr_chem:
            return (-1.0, '')

        total_weight = 0.0
        matched_weight = 0.0
        matched_elems = []
        mismatched_elems = []

        for elem, spec_range in spec_chem.items():
            if not isinstance(spec_range, dict):
                continue
            elem_upper = elem.upper()

            # Find MTR value (case-insensitive)
            mtr_val = None
            for mk, mv in mtr_chem.items():
                if mk.upper() == elem_upper:
                    try:
                        mtr_val = float(mv)
                    except (ValueError, TypeError):
                        pass
                    break

            if mtr_val is None:
                continue

            weight = 2.0 if elem_upper in _KEY_ELEMENTS else 1.0
            total_weight += weight

            spec_min = spec_range.get('min', 0)
            spec_max = spec_range.get('max', float('inf'))

            # 20% tolerance for OCR errors
            range_span = (spec_max - spec_min) if spec_max != float('inf') else spec_min
            tolerance = max(range_span * 0.2, 0.005)

            if (spec_min - tolerance) <= mtr_val <= (spec_max + tolerance):
                matched_weight += weight
                matched_elems.append(elem_upper)
            else:
                mismatched_elems.append(elem_upper)

        if total_weight == 0:
            return (-1.0, '')

        score = matched_weight / total_weight
        detail = f"Chem {score:.0%} ({', '.join(sorted(matched_elems))})"
        if mismatched_elems:
            detail += f" miss: {', '.join(sorted(mismatched_elems))}"
        return (score, detail)

    # ------------------------------------------------------------------ Mechanical scoring
    def _score_mechanical(self, spec: dict, mtr_mech: Dict[str, Any]) -> Tuple[float, str]:
        """Score how well MTR mechanical properties fit a spec's ranges.

        Returns (score 0.0-1.0, detail string). Score -1 if no comparison possible.
        Checks yield, tensile, elongation, reduction_of_area, hardness.
        """
        spec_mech = spec.get('mechanical', {})
        if not spec_mech or not mtr_mech:
            return (-1.0, '')

        checked = 0
        passed = 0
        details = []

        # Property checks with aliases
        for prop_name in ('yield_strength', 'tensile_strength', 'elongation',
                          'reduction_of_area', 'hardness_hbw', 'hardness_hrc'):
            spec_range = spec_mech.get(prop_name, {})
            if not isinstance(spec_range, dict):
                continue
            spec_min = spec_range.get('min')
            spec_max = spec_range.get('max')
            if spec_min is None and spec_max is None:
                continue

            # Find MTR value using aliases
            mtr_val = None
            aliases = PROPERTY_ALIASES.get(prop_name, [prop_name])
            for alias in aliases:
                if alias in mtr_mech:
                    v = mtr_mech[alias]
                    if isinstance(v, dict):
                        v = v.get('value')
                    try:
                        mtr_val = float(v)
                    except (ValueError, TypeError):
                        pass
                    if mtr_val is not None:
                        break

            if mtr_val is None:
                continue

            checked += 1
            in_range = True
            if spec_min is not None and mtr_val < float(spec_min):
                in_range = False
            if spec_max is not None and mtr_val > float(spec_max):
                in_range = False

            if in_range:
                passed += 1
                details.append(f"{prop_name}:OK")
            else:
                details.append(f"{prop_name}:MISS")

        if checked == 0:
            return (-1.0, '')

        score = passed / checked
        detail = f"Mech {score:.0%} ({passed}/{checked})"
        return (score, detail)

    # ------------------------------------------------------------------ Identity scoring
    def _score_identity(self, spec: dict, mtr_uns: str,
                        mtr_grade: str, mtr_product_form: str = '') -> Tuple[float, str]:
        """Score UNS and grade name match. Returns (score 0.0-1.0, detail string)."""
        spec_uns = (spec.get('uns') or '').upper().strip()
        spec_grades = [g.upper() for g in spec.get('grades', [])]

        # UNS match (best identity signal)
        if mtr_uns and spec_uns and mtr_uns == spec_uns:
            return (SCORE_UNS_MATCH, f"UNS: {mtr_uns}")

        if not mtr_grade and not mtr_product_form:
            return (0.0, '')

        # Exact grade match
        if mtr_grade and mtr_grade in spec_grades:
            return (SCORE_GRADE_EXACT, f"Grade: {mtr_grade}")

        # Normalized match
        mtr_norm = self._normalize_grade(mtr_grade) if mtr_grade else ''
        for sg in spec_grades:
            if mtr_norm and self._normalize_grade(sg) == mtr_norm:
                return (SCORE_GRADE_EXACT, f"Grade: {mtr_grade}~{sg}")

        # Trade name alias match
        if mtr_grade:
            alias_grades = _GRADE_ALIASES.get(mtr_grade, [])
            if not alias_grades:
                alias_grades = _GRADE_ALIASES.get(mtr_norm, [])
            for alias in alias_grades:
                alias_upper = alias.upper()
                if alias_upper in spec_grades:
                    return (SCORE_GRADE_ALIAS, f"Alias: {mtr_grade}->{alias}")
                for sg in spec_grades:
                    if self._normalize_grade(sg) == self._normalize_grade(alias_upper):
                        return (SCORE_GRADE_ALIAS, f"Alias: {mtr_grade}->{alias}~{sg}")

        # Partial match on grade
        if mtr_grade:
            for sg in spec_grades:
                if mtr_grade in sg or sg in mtr_grade:
                    return (SCORE_GRADE_PARTIAL, f"Partial: {mtr_grade}~{sg}")
                sg_norm = self._normalize_grade(sg)
                if mtr_norm in sg_norm or sg_norm in mtr_norm:
                    return (SCORE_GRADE_PARTIAL, f"Partial: {mtr_grade}~{sg}")

        # Keyword-based product form match — handles reordered terms and synonyms
        # e.g., "Teflon Glass Moly" matches spec grade "PTFE 15% Glass 5% Moly"
        if mtr_product_form:
            # Combine grade + product form for maximum signal
            mtr_text = f"{mtr_grade} {mtr_product_form}"
            mtr_keywords = _extract_material_keywords(mtr_text)
            for sg in spec_grades:
                sg_keywords = _extract_material_keywords(sg)
                # Require at least 2 keyword overlap and all spec keywords present
                if len(sg_keywords) >= 2 and sg_keywords.issubset(mtr_keywords):
                    matched = ', '.join(sorted(sg_keywords))
                    return (SCORE_GRADE_PARTIAL, f"Keywords({matched})~{sg}")

        return (0.0, '')

    # ------------------------------------------------------------------ Helpers
    @staticmethod
    def _normalize_grade(grade: str) -> str:
        """Normalize a grade name for comparison."""
        import re
        return re.sub(r'[\s\-]+', ' ', grade).strip()

    @staticmethod
    def _is_metallic(mtr_data: Dict[str, Any]) -> bool:
        """Check if MTR chemistry indicates a metallic material."""
        chem = mtr_data.get('chemistry', {})
        if not chem:
            return False
        for elem, val in chem.items():
            if elem in _METALLIC_ELEMENTS and val is not None:
                try:
                    if float(val) > 0.01:
                        return True
                except (ValueError, TypeError):
                    pass
        return False

    @staticmethod
    def _is_non_metal_spec(spec_id: str, spec: dict) -> bool:
        """Check if a spec is for non-metals (polymers, elastomers, plastics)."""
        mat_type = str(spec.get('material_type', '')).lower()
        if mat_type in ('polymer', 'plastic', 'elastomer', 'peek', 'rubber', 'ptfe', 'nylon'):
            return True
        if mat_type in ('metal', 'steel', 'alloy'):
            return False
        family = _extract_family_number(spec_id)
        if family and family in _NON_METAL_FAMILIES:
            return True
        return False

    def select_best_spec(self, mtr_data: Dict[str, Any]) -> Optional[MatchResult]:
        """
        Select the single best spec for this MTR.

        Returns:
            (spec_id, confidence, reason) or None if no confident match.
        """
        matches = self.find_matching_specs(mtr_data)

        if not matches:
            return None

        # Best match is already first (sorted by confidence)
        spec_id, confidence, reason = matches[0]
        if confidence < CONFIDENCE_THRESHOLD:
            return None
        return matches[0]

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
        """Suggest specs that might match a partial grade name."""
        partial = partial_grade.upper().strip()
        suggestions = []
        for spec_id, spec in self.loader.all_specs().items():
            material = spec.get('material', '')
            grades = spec.get('grades', [])
            if partial in material.upper():
                suggestions.append(self.get_spec_summary(spec_id))
            elif any(partial in g.upper() for g in grades):
                suggestions.append(self.get_spec_summary(spec_id))
        return suggestions
