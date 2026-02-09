"""
Core validation engine - compares MTR data against spec requirements.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from .spec_loader import SpecLoader
from .converters import convert_stress, normalize_hardness


@dataclass
class ValidationResult:
    """Result for a single property validation."""
    property_name: str
    spec_min: Optional[float] = None
    spec_max: Optional[float] = None
    actual_value: Optional[float] = None
    unit: str = ""
    status: str = "UNKNOWN"  # PASS, FAIL, MISSING, SKIP
    note: str = ""
    
    def is_pass(self) -> bool:
        return self.status == "PASS"
    
    def is_fail(self) -> bool:
        return self.status == "FAIL"


@dataclass
class CertValidation:
    """Complete validation result for an MTR against a spec."""
    spec_id: str
    heat_number: str
    material_grade: str
    overall_status: str = "UNKNOWN"  # PASS, FAIL, INCOMPLETE, ERROR
    chemistry_results: List[ValidationResult] = field(default_factory=list)
    mechanical_results: List[ValidationResult] = field(default_factory=list)
    special_results: List[ValidationResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'spec_id': self.spec_id,
            'heat_number': self.heat_number,
            'material_grade': self.material_grade,
            'overall_status': self.overall_status,
            'chemistry': [vars(r) for r in self.chemistry_results],
            'mechanical': [vars(r) for r in self.mechanical_results],
            'special': [vars(r) for r in self.special_results],
            'errors': self.errors,
            'warnings': self.warnings,
        }
    
    @property
    def all_results(self) -> List['ValidationResult']:
        return self.chemistry_results + self.mechanical_results + self.special_results

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.all_results if r.status == "PASS")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.all_results if r.status == "FAIL")

    @property
    def missing_count(self) -> int:
        return sum(1 for r in self.all_results if r.status == "MISSING")


# Property name aliases for flexible matching
PROPERTY_ALIASES = {
    'yield_strength': ['yield_strength', 'ys', 'yield', '0.2% offset yield', '0.2%_yield'],
    'tensile_strength': ['tensile_strength', 'ts', 'tensile', 'uts', 'ultimate_tensile'],
    'elongation': ['elongation', 'elong', 'el', 'elongation_2in', 'elongation_4d', 'el_2in'],
    'reduction_of_area': ['reduction_of_area', 'ra', 'reduction', 'roa', 'red_of_area'],
    'hardness_hrc': ['hardness_hrc', 'hrc', 'hardness_rc', 'rockwell_c'],
    'hardness_hbw': ['hardness_hbw', 'hbw', 'hb', 'brinell', 'hardness_bhn', 'bhn'],
}


class SpecValidator:
    """Validates MTR data against engineering specifications."""
    
    def __init__(self, specs_dir: Optional[str] = None):
        self.loader = SpecLoader.get_instance(specs_dir)
    
    def get_spec(self, spec_id: str) -> Optional[dict]:
        """Get a spec by ID."""
        return self.loader.get(spec_id)
    
    def list_specs(self) -> List[str]:
        """List all available spec IDs."""
        return self.loader.list_ids()
    
    def validate(self, mtr_data: Dict[str, Any], spec_id: str) -> CertValidation:
        """
        Validate MTR data against a specification.
        
        Args:
            mtr_data: Extracted MTR data with 'chemistry', 'mechanical', etc.
            spec_id: The specification ID to validate against
            
        Returns:
            CertValidation object with all results
        """
        spec = self.loader.get(spec_id)
        heat_number = mtr_data.get('heat_number', 'UNKNOWN')
        material_grade = mtr_data.get('material_grade', 'UNKNOWN')
        
        if not spec:
            result = CertValidation(
                spec_id=spec_id,
                heat_number=heat_number,
                material_grade=material_grade,
                overall_status='ERROR'
            )
            result.errors.append(f"Specification not found: {spec_id}")
            return result
        
        result = CertValidation(
            spec_id=spec_id,
            heat_number=heat_number,
            material_grade=material_grade,
        )
        
        # Validate chemistry
        if 'chemistry' in spec:
            result.chemistry_results = self._validate_chemistry(
                mtr_data.get('chemistry', {}),
                spec['chemistry']
            )
        
        # Validate mechanical properties
        if 'mechanical' in spec:
            result.mechanical_results = self._validate_mechanical(
                mtr_data.get('mechanical', {}),
                spec['mechanical']
            )
        
        # Validate special requirements
        if spec.get('special_requirements'):
            result.special_results = self._validate_special(
                mtr_data,
                spec['special_requirements']
            )
        
        # Determine overall status
        result.overall_status = self._determine_overall_status(result)
        
        return result
    
    @staticmethod
    def _check_range(vr: ValidationResult, actual: float, fmt: str = ".4f") -> None:
        """Check actual value against spec min/max and update the ValidationResult."""
        vr.actual_value = actual
        vr.status = 'PASS'
        if vr.spec_min is not None and actual < vr.spec_min:
            vr.status = 'FAIL'
            vr.note = f"Below minimum ({actual:{fmt}} < {vr.spec_min})"
        elif vr.spec_max is not None and actual > vr.spec_max:
            vr.status = 'FAIL'
            vr.note = f"Above maximum ({actual:{fmt}} > {vr.spec_max})"

    def _determine_overall_status(self, result: CertValidation) -> str:
        """Determine overall validation status from individual results."""
        all_results = result.all_results

        if not all_results:
            return 'UNKNOWN'

        statuses = [r.status for r in all_results]

        if 'FAIL' in statuses:
            return 'FAIL'
        elif 'MISSING' in statuses or 'INCOMPLETE' in statuses:
            return 'INCOMPLETE'
        elif all(s in ('PASS', 'SKIP') for s in statuses):
            return 'PASS'
        else:
            return 'UNKNOWN'
    
    def _validate_chemistry(self, mtr_chem: Dict[str, float], spec_chem: Dict[str, dict]) -> List[ValidationResult]:
        """Validate chemistry values against spec."""
        results = []
        
        for element, limits in spec_chem.items():
            actual = mtr_chem.get(element)
            
            vr = ValidationResult(
                property_name=element,
                spec_min=limits.get('min'),
                spec_max=limits.get('max'),
                unit='%'
            )
            
            if actual is None:
                vr.status = 'MISSING'
                vr.note = f"{element} not found in MTR"
            else:
                try:
                    actual = float(actual)
                except (ValueError, TypeError):
                    vr.status = 'INCOMPLETE'
                    vr.note = f"Could not parse value: {actual}"
                    results.append(vr)
                    continue
                self._check_range(vr, actual, fmt=".4f")

            results.append(vr)
        
        return results
    
    def _validate_mechanical(self, mtr_mech: Dict[str, Any], spec_mech: Dict[str, dict]) -> List[ValidationResult]:
        """Validate mechanical properties against spec."""
        results = []
        
        for prop_name, limits in spec_mech.items():
            actual, actual_unit = self._find_property_value(mtr_mech, prop_name)
            
            vr = ValidationResult(
                property_name=prop_name,
                spec_min=limits.get('min'),
                spec_max=limits.get('max'),
                unit=limits.get('unit', '')
            )
            
            if actual is None:
                # Try hardness conversion
                actual = self._try_hardness_conversion(mtr_mech, prop_name, vr)
            
            if actual is None:
                vr.status = 'MISSING'
                vr.note = f"{prop_name} not found in MTR"
                results.append(vr)
                continue
            
            try:
                actual = float(actual)
            except (ValueError, TypeError):
                vr.status = 'INCOMPLETE'
                vr.note = f"Could not parse value: {actual}"
                results.append(vr)
                continue

            # Unit conversion for stress values
            spec_unit = limits.get('unit', '').lower()
            if actual_unit and spec_unit in ('ksi', 'mpa'):
                if actual_unit.lower() != spec_unit:
                    original = actual
                    actual = convert_stress(actual, actual_unit, spec_unit)
                    if not vr.note:
                        vr.note = f"Converted from {original:.2f} {actual_unit}"

            self._check_range(vr, actual, fmt=".2f")
            
            results.append(vr)
        
        return results
    
    def _find_property_value(self, mtr_mech: Dict[str, Any], prop_name: str) -> tuple:
        """Find property value using aliases. Returns (value, unit) or (None, None)."""
        aliases = PROPERTY_ALIASES.get(prop_name, [prop_name])
        
        for alias in aliases:
            if alias in mtr_mech:
                val = mtr_mech[alias]
                if isinstance(val, dict):
                    return val.get('value'), val.get('unit')
                return val, None
        
        return None, None
    
    def _try_hardness_conversion(self, mtr_mech: Dict[str, Any], prop_name: str, vr: ValidationResult) -> Optional[float]:
        """Try to convert between hardness scales if needed."""
        if prop_name == 'hardness_hrc':
            hbw_val, _ = self._find_property_value(mtr_mech, 'hardness_hbw')
            if hbw_val is not None:
                converted = normalize_hardness(hbw_val, 'HBW')
                vr.note = f"Converted from {hbw_val:.0f} HBW"
                return converted['hrc']
        
        elif prop_name == 'hardness_hbw':
            hrc_val, _ = self._find_property_value(mtr_mech, 'hardness_hrc')
            if hrc_val is not None:
                converted = normalize_hardness(hrc_val, 'HRC')
                vr.note = f"Converted from {hrc_val:.1f} HRc"
                return converted['hbw']
        
        return None
    
    def _validate_special(self, mtr_data: Dict[str, Any], special_reqs: List[dict]) -> List[ValidationResult]:
        """Validate special requirements."""
        results = []
        
        for req in special_reqs:
            req_type = req.get('type', 'unknown')
            vr = ValidationResult(property_name=req_type, note=req.get('note', ''))
            
            if req_type == 'nace_compliance':
                vr = self._validate_nace(mtr_data, vr)
            elif req_type == 'temper_temperature':
                vr = self._validate_temper(mtr_data, req, vr)
            elif req_type == 'charpy_impact':
                vr = self._validate_charpy(mtr_data, req, vr)
            else:
                vr.status = 'SKIP'
                vr.note = f"Unknown requirement type: {req_type}"
            
            results.append(vr)
        
        return results
    
    def _validate_nace(self, mtr_data: Dict[str, Any], vr: ValidationResult) -> ValidationResult:
        """Validate NACE compliance requirement."""
        nace = mtr_data.get('nace_compliant')
        if nace is True:
            vr.status = 'PASS'
            vr.note = 'NACE compliant'
        elif nace is False:
            vr.status = 'FAIL'
            vr.note = 'Not NACE compliant'
        else:
            vr.status = 'MISSING'
            vr.note = 'NACE compliance not stated'
        return vr
    
    def _validate_temper(self, mtr_data: Dict[str, Any], req: dict, vr: ValidationResult) -> ValidationResult:
        """Validate tempering temperature requirement."""
        temper = mtr_data.get('temper_temperature')
        if temper is not None:
            try:
                temper = float(temper)
            except (ValueError, TypeError):
                vr.status = 'INCOMPLETE'
                vr.note = f'Could not parse temper temperature: {temper}'
                return vr
            vr.actual_value = temper
            vr.spec_min = req.get('min')
            vr.unit = req.get('unit', '°F')
            if temper >= req.get('min', 0):
                vr.status = 'PASS'
            else:
                vr.status = 'FAIL'
                vr.note = f"Below minimum ({temper} < {req['min']})"
        else:
            vr.status = 'MISSING'
            vr.note = 'Temper temperature not stated'
        return vr
    
    def _validate_charpy(self, mtr_data: Dict[str, Any], req: dict, vr: ValidationResult) -> ValidationResult:
        """Validate Charpy impact requirement."""
        charpy = mtr_data.get('charpy_impact')
        if charpy is not None:
            actual = charpy.get('avg') if isinstance(charpy, dict) else charpy
            try:
                actual = float(actual)
            except (ValueError, TypeError):
                vr.status = 'INCOMPLETE'
                vr.note = f'Could not parse Charpy value: {actual}'
                return vr
            vr.actual_value = actual
            vr.spec_min = req.get('min_avg')
            vr.unit = req.get('unit', 'ft-lbs')
            if actual >= req.get('min_avg', 0):
                vr.status = 'PASS'
            else:
                vr.status = 'FAIL'
                vr.note = f"Below minimum ({vr.actual_value} < {vr.spec_min})"
        else:
            vr.status = 'MISSING'
            vr.note = 'Charpy impact not tested'
        return vr


def format_validation_report(result: CertValidation, use_color: bool = True) -> str:
    """Format validation result as human-readable report."""
    
    # Color codes (ANSI)
    if use_color:
        GREEN = '\033[92m'
        RED = '\033[91m'
        YELLOW = '\033[93m'
        BOLD = '\033[1m'
        RESET = '\033[0m'
    else:
        GREEN = RED = YELLOW = BOLD = RESET = ''
    
    status_colors = {
        'PASS': GREEN,
        'FAIL': RED,
        'MISSING': YELLOW,
        'INCOMPLETE': YELLOW,
        'ERROR': RED,
    }
    
    lines = []
    lines.append("=" * 60)
    lines.append(f"{BOLD}MATERIAL CERT VALIDATION REPORT{RESET}")
    lines.append("=" * 60)
    lines.append(f"Spec:           {result.spec_id}")
    lines.append(f"Heat Number:    {result.heat_number}")
    lines.append(f"Material Grade: {result.material_grade}")
    
    status_color = status_colors.get(result.overall_status, '')
    lines.append(f"Overall Status: {status_color}{result.overall_status}{RESET}")
    lines.append(f"Summary:        {result.pass_count} pass, {result.fail_count} fail, {result.missing_count} missing")
    lines.append("")
    
    if result.chemistry_results:
        lines.append("-" * 40)
        lines.append(f"{BOLD}CHEMISTRY{RESET}")
        lines.append("-" * 40)
        lines.append(f"{'Element':<8} {'Min':>8} {'Max':>8} {'Actual':>8} {'Status':<10}")
        for r in result.chemistry_results:
            min_str = f"{r.spec_min:.3f}" if r.spec_min is not None else "-"
            max_str = f"{r.spec_max:.3f}" if r.spec_max is not None else "-"
            act_str = f"{r.actual_value:.3f}" if r.actual_value is not None else "-"
            sc = status_colors.get(r.status, '')
            lines.append(f"{r.property_name:<8} {min_str:>8} {max_str:>8} {act_str:>8} {sc}{r.status:<10}{RESET}")
        lines.append("")
    
    if result.mechanical_results:
        lines.append("-" * 40)
        lines.append(f"{BOLD}MECHANICAL PROPERTIES{RESET}")
        lines.append("-" * 40)
        lines.append(f"{'Property':<20} {'Min':>8} {'Max':>8} {'Actual':>8} {'Status':<10}")
        for r in result.mechanical_results:
            min_str = f"{r.spec_min:.1f}" if r.spec_min is not None else "-"
            max_str = f"{r.spec_max:.1f}" if r.spec_max is not None else "-"
            act_str = f"{r.actual_value:.2f}" if r.actual_value is not None else "-"
            sc = status_colors.get(r.status, '')
            lines.append(f"{r.property_name:<20} {min_str:>8} {max_str:>8} {act_str:>8} {sc}{r.status:<10}{RESET}")
        lines.append("")
    
    if result.special_results:
        lines.append("-" * 40)
        lines.append(f"{BOLD}SPECIAL REQUIREMENTS{RESET}")
        lines.append("-" * 40)
        for r in result.special_results:
            sc = status_colors.get(r.status, '')
            lines.append(f"{r.property_name}: {sc}{r.status}{RESET} - {r.note}")
        lines.append("")
    
    if result.errors:
        lines.append("-" * 40)
        lines.append(f"{RED}ERRORS{RESET}")
        lines.append("-" * 40)
        for err in result.errors:
            lines.append(f"  ! {err}")
    
    if result.warnings:
        lines.append("-" * 40)
        lines.append(f"{YELLOW}WARNINGS{RESET}")
        lines.append("-" * 40)
        for warn in result.warnings:
            lines.append(f"  ? {warn}")
    
    lines.append("=" * 60)
    return "\n".join(lines)
