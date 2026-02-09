"""
Unit and scale converters for material property values.
"""

# Stress conversions
MPA_TO_KSI = 0.145038
KSI_TO_MPA = 6.89476
PSI_TO_KSI = 0.001
KSI_TO_PSI = 1000


def convert_stress(value: float, from_unit: str, to_unit: str) -> float:
    """Convert stress values between units."""
    from_unit = from_unit.lower().strip()
    to_unit = to_unit.lower().strip()

    # Normalize unit names
    unit_map = {
        'ksi': 'ksi',
        'mpa': 'mpa',
        'n/mm2': 'mpa',
        'n/mm²': 'mpa',
        'psi': 'psi',
    }

    from_unit = unit_map.get(from_unit, from_unit)
    to_unit = unit_map.get(to_unit, to_unit)

    if from_unit == to_unit:
        return value

    # Convert everything through ksi as the pivot unit
    # Step 1: convert from_unit → ksi
    if from_unit == 'ksi':
        value_ksi = value
    elif from_unit == 'mpa':
        value_ksi = value * MPA_TO_KSI
    elif from_unit == 'psi':
        value_ksi = value * PSI_TO_KSI
    else:
        raise ValueError(f"Unknown source unit: {from_unit}")

    # Step 2: convert ksi → to_unit
    if to_unit == 'ksi':
        return value_ksi
    elif to_unit == 'mpa':
        return value_ksi * KSI_TO_MPA
    elif to_unit == 'psi':
        return value_ksi * KSI_TO_PSI
    else:
        raise ValueError(f"Unknown target unit: {to_unit}")


# Hardness conversions (approximate - ASTM E140)
# These are approximate conversions for carbon/alloy steels
HRC_TO_HBW = {
    # HRc: HBW (approximate for steel)
    20: 226, 21: 231, 22: 237, 23: 243, 24: 247,
    25: 253, 26: 258, 27: 264, 28: 271, 29: 279,
    30: 286, 31: 294, 32: 301, 33: 311, 34: 319,
    35: 327, 36: 336, 37: 344, 38: 353, 39: 362,
    40: 371, 41: 381, 42: 390, 43: 400, 44: 409,
}

HBW_TO_HRC = {v: k for k, v in HRC_TO_HBW.items()}
SORTED_HBW_KEYS = sorted(HBW_TO_HRC.keys())


def hrc_to_hbw(hrc: float) -> float:
    """Convert Rockwell C to Brinell (approximate)."""
    if hrc < 20:
        # Below HRc 20, use linear approximation
        return 200 + (hrc * 1.3)
    
    # Interpolate from table
    lower = int(hrc)
    upper = lower + 1
    
    if lower in HRC_TO_HBW and upper in HRC_TO_HBW:
        frac = hrc - lower
        return HRC_TO_HBW[lower] + frac * (HRC_TO_HBW[upper] - HRC_TO_HBW[lower])
    elif lower in HRC_TO_HBW:
        return HRC_TO_HBW[lower]
    else:
        # Extrapolate for high values
        return 371 + (hrc - 40) * 10


def hbw_to_hrc(hbw: float) -> float:
    """Convert Brinell to Rockwell C (approximate)."""
    if hbw < 226:
        # Below HBW 226, use linear approximation (roughly HRc 20)
        return max(0, (hbw - 200) / 1.3)
    
    # Find closest values in table
    for i, val in enumerate(SORTED_HBW_KEYS):
        if hbw <= val:
            if i == 0:
                return HBW_TO_HRC[val]
            # Interpolate
            lower_hbw = SORTED_HBW_KEYS[i-1]
            upper_hbw = val
            lower_hrc = HBW_TO_HRC[lower_hbw]
            upper_hrc = HBW_TO_HRC[upper_hbw]
            frac = (hbw - lower_hbw) / (upper_hbw - lower_hbw)
            return lower_hrc + frac * (upper_hrc - lower_hrc)
    
    # Above table, extrapolate
    return 44 + (hbw - 409) / 10


def normalize_hardness(value: float, scale: str) -> dict:
    """
    Normalize hardness value to both HRc and HBW.
    Returns dict with both scales for comparison flexibility.
    """
    scale = scale.upper().strip()
    
    result = {'original_value': value, 'original_scale': scale}
    
    if scale in ('HRC', 'ROCKWELL C', 'RC'):
        result['hrc'] = value
        result['hbw'] = hrc_to_hbw(value)
    elif scale in ('HBW', 'HB', 'BRINELL', 'BHN'):
        result['hbw'] = value
        result['hrc'] = hbw_to_hrc(value)
    elif scale in ('HRB', 'ROCKWELL B', 'RB'):
        # HRB is typically for softer materials, rough conversion
        # HRB 100 ≈ HBW 240, HRB 0 ≈ HBW 60
        result['hbw'] = 60 + (value * 1.8)
        result['hrc'] = hbw_to_hrc(result['hbw'])
    else:
        raise ValueError(f"Unknown hardness scale: {scale}")
    
    return result


if __name__ == '__main__':
    # Quick tests
    print("Stress conversions:")
    print(f"  100 ksi = {convert_stress(100, 'ksi', 'mpa'):.1f} MPa")
    print(f"  689 MPa = {convert_stress(689, 'mpa', 'ksi'):.1f} ksi")
    
    print("\nHardness conversions:")
    print(f"  22 HRc = {hrc_to_hbw(22):.0f} HBW")
    print(f"  255 HBW = {hbw_to_hrc(255):.1f} HRc")
    print(f"  170 HBW = {hbw_to_hrc(170):.1f} HRc")
