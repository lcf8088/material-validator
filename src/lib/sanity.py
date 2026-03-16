"""
Sanity checks for extracted MTR data.

Catches obvious extraction errors before validation runs.
"""

from typing import Dict, List, Optional, Tuple, Any

# Reasonable ranges for common materials
# Values outside these ranges trigger warnings
CHEMISTRY_RANGES = {
    'C':  (0, 2.5),      # Carbon rarely > 2.5%
    'Mn': (0, 15),       # Manganese
    'P':  (0, 0.5),      # Phosphorus (usually < 0.05)
    'S':  (0, 0.5),      # Sulfur (usually < 0.05, 303 SS higher)
    'Si': (0, 5),        # Silicon
    'Cr': (0, 35),       # Chromium (max ~30% in superalloys)
    'Ni': (0, 80),       # Nickel (can be high in nickel alloys)
    'Mo': (0, 15),       # Molybdenum
    'V':  (0, 5),        # Vanadium
    'Cu': (0, 40),       # Copper
    'Ti': (0, 10),       # Titanium
    'Al': (0, 15),       # Aluminum
    'N':  (0, 1),        # Nitrogen
    'Nb': (0, 10),       # Niobium
    'W':  (0, 20),       # Tungsten
    'Co': (0, 70),       # Cobalt
    'B':  (0, 0.05),     # Boron (usually very low)
    'Sn': (0, 0.5),      # Tin
    'Ta': (0, 5),         # Tantalum
    'Fe': (0, 100),       # Iron (balance element)
    'Pb': (0, 5),         # Lead (free-machining alloys)
    'Zn': (0, 50),        # Zinc (brass)
    'Se': (0, 0.5),       # Selenium
    'Ca': (0, 0.1),       # Calcium
}

MECHANICAL_RANGES = {
    'yield_strength':     (5, 350),      # ksi - most steels 30-200
    'tensile_strength':   (10, 400),     # ksi - most steels 50-250
    'elongation':         (1, 80),       # % - most steels 5-40%
    'reduction_of_area':  (1, 90),       # % - most steels 20-70%
    'hardness_hrc':       (10, 70),      # Rockwell C
    'hardness_hbw':       (80, 750),     # Brinell
    'hardness_hrb':       (0, 100),      # Rockwell B
}

# Typical borderline threshold (percentage of limit)
BORDERLINE_THRESHOLD = 0.05  # 5%


def detect_suspicious_chemistry(
    chemistry: Dict[str, Any],
    spec_chemistry: Optional[Dict[str, Any]] = None,
) -> bool:
    """Detect if extracted chemistry looks suspicious and warrants an Opus retry.

    Combines multiple detection strategies to catch various extraction errors:
    1. Column shift by +1 (most common: C←Si, Si←Mn, Mn←P, P←S)
    2. Column shift by +2 or other mis-alignments
    3. Multiplier errors (correct column, wrong scale factor)
    4. Spec-based: too many chemistry failures against known spec limits

    Returns True if extraction looks unreliable.

    Args:
        chemistry: Extracted chemistry dict (element → value).
        spec_chemistry: Optional spec chemistry limits dict (element → {min, max}).
    """
    def _f(key):
        v = chemistry.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    signals = 0

    # --- Strategy 1: Column shift by +1 (physics-based, no spec needed) ---
    c, si, mn, p = _f('C'), _f('Si'), _f('Mn'), _f('P')

    # C > 0.15 and fits Si's typical range (0.10-1.00)
    if c is not None and c > 0.15 and 0.10 <= c <= 1.00:
        signals += 1

    # Si > 0.50 and fits Mn's typical range (0.10-2.00)
    if si is not None and si > 0.50 and 0.10 <= si <= 2.00:
        signals += 1

    # Mn < 0.10 and fits P's typical range (0-0.050)
    if mn is not None and mn < 0.10 and 0.0 <= mn <= 0.050:
        signals += 1

    # P < 0.005 and fits S's typical range
    if p is not None and p < 0.005:
        signals += 1

    if signals >= 2:
        return True

    # --- Strategy 2: Multiplier errors (value 10x or 100x off) ---
    # Ti is commonly misread: 0.10 read as 1.0 (÷10 instead of ÷100)
    ti = _f('Ti')
    if ti is not None and ti > 0.50 and ti <= 5.0:
        # Ti > 0.50% is unusual for most steels (except some titanium alloys)
        # Combined with C being off, strong signal
        if c is not None and c > 0.10:
            signals += 1

    # N typically < 0.05%; if > 0.10% it's likely a multiplier error
    n = _f('N')
    if n is not None and n > 0.10:
        signals += 1

    if signals >= 2:
        return True

    # --- Strategy 3: Spec-based failure counting ---
    if spec_chemistry and len(spec_chemistry) >= 3:
        failures = 0
        checked = 0
        for elem, limits in spec_chemistry.items():
            val = _f(elem)
            if val is None:
                continue
            checked += 1
            lo = limits.get('min')
            hi = limits.get('max')
            if lo is not None and val < float(lo) * 0.5:
                # Value is less than HALF the minimum — very suspicious
                failures += 1
            elif hi is not None and val > float(hi) * 2.0:
                # Value is more than DOUBLE the maximum — very suspicious
                failures += 1
        # 3+ elements way out of range is suspicious
        if checked >= 4 and failures >= 3:
            return True

    return False


def check_chemistry_sanity(chemistry: Dict[str, float]) -> List[Tuple[str, str, str]]:
    """
    Check chemistry values for obvious errors.
    
    Returns list of (element, value, warning_message) tuples.
    """
    warnings = []
    
    for element, value in chemistry.items():
        if value is None:
            continue

        try:
            value = float(value)
        except (ValueError, TypeError):
            continue

        element_title = element.strip().capitalize()

        # Check if value is negative
        if value < 0:
            warnings.append((element, str(value), "Negative value - extraction error"))
            continue

        # Check against known ranges
        if element_title in CHEMISTRY_RANGES:
            min_val, max_val = CHEMISTRY_RANGES[element_title]
            if value > max_val:
                warnings.append((
                    element, 
                    f"{value:.3f}%", 
                    f"Unusually high (typical max ~{max_val}%) - verify extraction"
                ))
            elif value > max_val * 0.8 and element_title in ('P', 'S', 'B'):
                # Extra scrutiny for elements that are usually very low
                warnings.append((
                    element,
                    f"{value:.3f}%",
                    f"Higher than typical - verify if intentional"
                ))
    
    # Check for common extraction mistakes
    # e.g., Cr and Ni swapped, decimal point errors
    try:
        cr = float(chemistry.get('Cr', 0))
    except (ValueError, TypeError):
        cr = 0
    try:
        ni = float(chemistry.get('Ni', 0))
    except (ValueError, TypeError):
        ni = 0
    
    # For stainless steels, Cr should be > Ni typically (except some austenitics)
    # Flag if Ni >> Cr which might indicate a swap
    if ni > 20 and cr < 10 and cr > 0:
        warnings.append((
            'Cr/Ni',
            f"Cr={cr:.2f}, Ni={ni:.2f}",
            "Possible Cr/Ni column swap - verify"
        ))

    # S/Sn swap detection
    # For steels (Fe-based or Cr > 5%), S (Sulfur) is typically << Sn (Tin)
    # If S > Sn and S > 0.01, it may be swapped
    try:
        s_val = float(chemistry.get('S', 0) or 0)
    except (ValueError, TypeError):
        s_val = 0
    try:
        sn_val = float(chemistry.get('Sn', 0) or 0)
    except (ValueError, TypeError):
        sn_val = 0
    try:
        cu_val = float(chemistry.get('Cu', 0) or 0)
    except (ValueError, TypeError):
        cu_val = 0

    # Only flag for steels/nickel alloys, not free-machining or copper alloys
    is_copper_alloy = cu_val > 50
    if s_val > sn_val and sn_val > 0 and not is_copper_alloy:
        warnings.append((
            'S/Sn',
            f"S={s_val:.4f}, Sn={sn_val:.4f}",
            "Possible S/Sn swap - Sulfur higher than Tin is unusual for steels"
        ))

    return warnings


def _is_austenitic(chemistry: Optional[Dict[str, Any]] = None) -> bool:
    """Detect austenitic stainless steel from chemistry (high Cr + high Ni)."""
    if not chemistry:
        return False
    try:
        cr = float(chemistry.get('Cr', 0) or 0)
        ni = float(chemistry.get('Ni', 0) or 0)
    except (ValueError, TypeError):
        return False
    # Austenitic SS: Cr >= 16% and Ni >= 6% (covers 303, 304, 316, 321, 347)
    return cr >= 16 and ni >= 6


def check_mechanical_sanity(
    mechanical: Dict[str, Any],
    chemistry: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str, str]]:
    """
    Check mechanical properties for obvious errors.

    Args:
        mechanical: Extracted mechanical properties dict.
        chemistry: Optional chemistry dict for material-type-aware ratio checks.

    Returns list of (property, value, warning_message) tuples.
    """
    warnings = []
    
    for prop, value in mechanical.items():
        if value is None:
            continue

        # Handle dict values (with units)
        if isinstance(value, dict):
            value = value.get('value')
            if value is None:
                continue

        try:
            value = float(value)
        except (ValueError, TypeError):
            continue

        prop_lower = prop.lower()
        
        # Check against known ranges
        for range_prop, (min_val, max_val) in MECHANICAL_RANGES.items():
            if range_prop in prop_lower or prop_lower in range_prop:
                if value < min_val:
                    warnings.append((
                        prop,
                        str(value),
                        f"Below typical minimum ({min_val}) - verify"
                    ))
                elif value > max_val:
                    warnings.append((
                        prop,
                        str(value),
                        f"Above typical maximum ({max_val}) - verify extraction"
                    ))
                break
    
    # Cross-checks
    ys = None
    ts = None
    
    for prop, value in mechanical.items():
        if isinstance(value, dict):
            value = value.get('value')
        if value is None:
            continue
        try:
            value = float(value)
        except (ValueError, TypeError):
            continue

        if 'yield' in prop.lower():
            ys = value
        elif 'tensile' in prop.lower():
            ts = value
    
    # Tensile should always be >= Yield
    if ys and ts and ts < ys:
        warnings.append((
            'YS/TS',
            f"YS={ys}, TS={ts}",
            "Tensile < Yield - impossible, extraction error"
        ))
    
    # YS/TS ratio thresholds depend on material type:
    #   Austenitic SS (303,304,316): 0.30-0.65 typical (low yield, high work hardening)
    #   Other steels (carbon, martensitic, ferritic): 0.60-0.92 typical
    austenitic = _is_austenitic(chemistry)
    if austenitic:
        error_lo, warn_lo, warn_hi = 0.20, 0.30, 0.75
        mat_label = "austenitic SS"
    else:
        error_lo, warn_lo, warn_hi = 0.40, 0.55, 0.95
        mat_label = "steel"

    if ys and ts and ts > 0:
        ratio = ys / ts
        if ratio > 1.0:
            warnings.append((
                'YS/TS ratio',
                f"{ratio:.2f} (YS={ys}, TS={ts})",
                "Yield > Tensile - impossible, extraction error"
            ))
        elif ratio < error_lo:
            warnings.append((
                'YS/TS ratio',
                f"{ratio:.2f} (YS={ys}, TS={ts})",
                f"YS/TS ratio below {error_lo} for {mat_label} - impossible, extraction error"
            ))
        elif ratio < warn_lo:
            warnings.append((
                'YS/TS ratio',
                f"{ratio:.2f} (YS={ys}, TS={ts})",
                f"YS/TS ratio below {warn_lo} for {mat_label} - unusual, verify values"
            ))
        elif ratio > warn_hi:
            warnings.append((
                'YS/TS ratio',
                f"{ratio:.2f} (YS={ys}, TS={ts})",
                f"YS/TS ratio above {warn_hi} for {mat_label} - unusually close, verify values"
            ))
    
    return warnings


def check_borderline_values(mtr_data: Dict[str, Any], spec: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """
    Check for values that pass but are within threshold of limits.
    
    Returns list of (property, value, warning_message) tuples.
    """
    warnings = []
    
    # Check chemistry
    mtr_chem = mtr_data.get('chemistry', {})
    spec_chem = spec.get('chemistry', {})
    
    for element, limits in spec_chem.items():
        actual = mtr_chem.get(element)
        if actual is None:
            continue
        try:
            actual = float(actual)
        except (ValueError, TypeError):
            continue

        spec_min = limits.get('min')
        spec_max = limits.get('max')
        
        if spec_min is not None and spec_min > 0:
            threshold = spec_min * BORDERLINE_THRESHOLD
            if actual < spec_min + threshold and actual >= spec_min:
                warnings.append((
                    element,
                    f"{actual:.4f}%",
                    f"Within {BORDERLINE_THRESHOLD*100:.0f}% of minimum ({spec_min}) - passes but borderline"
                ))
        
        if spec_max is not None:
            threshold = spec_max * BORDERLINE_THRESHOLD
            if actual > spec_max - threshold and actual <= spec_max:
                warnings.append((
                    element,
                    f"{actual:.4f}%",
                    f"Within {BORDERLINE_THRESHOLD*100:.0f}% of maximum ({spec_max}) - passes but borderline"
                ))
    
    # Check mechanical
    mtr_mech = mtr_data.get('mechanical', {})
    spec_mech = spec.get('mechanical', {})
    
    for prop, limits in spec_mech.items():
        actual = mtr_mech.get(prop)
        if actual is None:
            continue
        if isinstance(actual, dict):
            actual = actual.get('value')
        if actual is None:
            continue
        try:
            actual = float(actual)
        except (ValueError, TypeError):
            continue

        spec_min = limits.get('min')
        spec_max = limits.get('max')
        
        if spec_min is not None:
            threshold = spec_min * BORDERLINE_THRESHOLD
            if actual < spec_min + threshold and actual >= spec_min:
                warnings.append((
                    prop,
                    f"{actual:.2f}",
                    f"Within {BORDERLINE_THRESHOLD*100:.0f}% of minimum ({spec_min}) - passes but borderline"
                ))
        
        if spec_max is not None:
            threshold = spec_max * BORDERLINE_THRESHOLD
            if actual > spec_max - threshold and actual <= spec_max:
                warnings.append((
                    prop,
                    f"{actual:.2f}",
                    f"Within {BORDERLINE_THRESHOLD*100:.0f}% of maximum ({spec_max}) - passes but borderline"
                ))
    
    return warnings


def run_all_sanity_checks(mtr_data: Dict[str, Any], spec: Dict[str, Any] = None) -> Dict[str, List[Tuple[str, str, str]]]:
    """
    Run all sanity checks on MTR data.
    
    Returns dict with 'errors', 'warnings', 'borderline' lists.
    """
    results = {
        'errors': [],      # Definite extraction errors
        'warnings': [],    # Suspicious values to verify
        'borderline': [],  # Values that pass but are close to limits
    }
    
    # Chemistry sanity
    if 'chemistry' in mtr_data:
        for item in check_chemistry_sanity(mtr_data['chemistry']):
            if 'impossible' in item[2].lower() or 'error' in item[2].lower():
                results['errors'].append(item)
            else:
                results['warnings'].append(item)
    
    # Mechanical sanity
    if 'mechanical' in mtr_data:
        for item in check_mechanical_sanity(mtr_data['mechanical'], mtr_data.get('chemistry')):
            if 'impossible' in item[2].lower() or 'error' in item[2].lower():
                results['errors'].append(item)
            else:
                results['warnings'].append(item)
    
    # Borderline checks (only if spec provided)
    if spec:
        results['borderline'] = check_borderline_values(mtr_data, spec)
    
    return results


def format_sanity_report(results: Dict[str, List]) -> str:
    """Format sanity check results as human-readable text."""
    lines = []
    
    if results['errors']:
        lines.append("🚨 EXTRACTION ERRORS (must fix):")
        for prop, value, msg in results['errors']:
            lines.append(f"  • {prop}: {value} - {msg}")
        lines.append("")
    
    if results['warnings']:
        lines.append("⚠️ WARNINGS (verify extraction):")
        for prop, value, msg in results['warnings']:
            lines.append(f"  • {prop}: {value} - {msg}")
        lines.append("")
    
    if results['borderline']:
        lines.append("📋 BORDERLINE VALUES (passes but close to limit):")
        for prop, value, msg in results['borderline']:
            lines.append(f"  • {prop}: {value} - {msg}")
        lines.append("")
    
    if not any(results.values()):
        lines.append("✅ No sanity issues detected")
    
    return "\n".join(lines)
