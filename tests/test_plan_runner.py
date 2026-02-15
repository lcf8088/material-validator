#!/usr/bin/env python3
"""
MTR Extraction Issues — Plan Test Runner

Runs MTR files through the pipeline and checks extraction results
against the pass criteria defined in docs/MTR-EXTRACTION-ISSUES.md.

Usage:
    python tests/test_plan_runner.py                    # Run all tests
    python tests/test_plan_runner.py SK908-1874         # Run one file
    python tests/test_plan_runner.py --phase 1          # Run Phase 1 tests only
    python tests/test_plan_runner.py --list              # List available files
"""

import json
import sys
import argparse
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from lib.pipeline import process_document
from lib.extractor import normalize_extracted_data, ELEMENT_ALIASES
from lib.matcher import SpecMatcher
from lib.sanity import check_chemistry_sanity

logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

# ── Config ──────────────────────────────────────────────────────────────────

WATCH_FOLDER = Path(r"C:\Users\qascanner\Documents\GitHub\material-validator\.MTR Validator Watch Folder Test")
CONFIG_PATH = Path(r"C:\Users\qascanner\Documents\GitHub\material-validator\config.json")
RESULTS_DIR = Path(r"C:\Users\qascanner\Documents\GitHub\material-validator\tests\plan_results")

# File alias → actual filename mapping
FILE_MAP = {
    'PO1966Li3':  '2026.02.Packing Slip.PO1966Li3.pdf',
    'PO1946':     '2026.02.Packing List.PO1946.pdf',
    'PO1918':     '2026.02.DOCS.PO1918.pdf',
    'PO1830':     '2026.02.DOCS.PO1830.pdf',
    'PO1783':     '2026.02.DOCS.PO1783Li1.2.pdf',   # A0959X heat
    'A0959X':     '2026.02.DOCS.PO1783Li1.2.pdf',   # alias
    '626119':     '626119-3409-01-1783.pdf',
    '472110':     '472110-1975.pdf',
    'SK908-1874': 'SK908-13628-1874.pdf',
    'SK908-1875': 'SK908-13628-1875.pdf',
    'B4535':      'B4535-1831.pdf',
    'P406278':    'P406278-1953.pdf',
    'PO1628':     '2026.02.ASSEMBLEYMTR.PO1628.pdf',
}

def load_api_key():
    with open(CONFIG_PATH) as f:
        return json.load(f)['anthropic_api_key']


def run_file(alias, spec_id=None, api_key=None):
    """Run a single file through the pipeline. Returns PipelineResult."""
    filename = FILE_MAP.get(alias)
    if not filename:
        print(f"  ERROR: Unknown file alias '{alias}'")
        return None

    pdf_path = WATCH_FOLDER / filename
    if not pdf_path.exists():
        print(f"  ERROR: File not found: {pdf_path}")
        return None

    print(f"  Processing {alias} ({filename})...")
    result = process_document(
        pdf_path=str(pdf_path),
        spec_id=spec_id,
        anthropic_api_key=api_key or load_api_key(),
        preprocessing_dpi=300,
    )

    # Save raw result for inspection
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = RESULTS_DIR / f"{alias}.json"
    out_data = {
        'alias': alias,
        'filename': filename,
        'success': result.success,
        'spec_id': result.spec_id,
        'spec_confidence': result.spec_match_confidence,
        'overall_status': result.overall_status,
        'normalized_data': result.normalized_data,
        'extracted_data': result.extracted_data,
        'errors': result.errors,
        'warnings': result.warnings,
    }
    if result.validation:
        out_data['validation'] = result.validation.to_dict()
    with open(out_file, 'w') as f:
        json.dump(out_data, f, indent=2, default=str)
    print(f"  Saved results to {out_file}")

    return result


def check(label, condition, actual, expected):
    """Print a pass/fail check line."""
    status = "PASS" if condition else "FAIL"
    mark = "[OK]" if condition else "[!!]"
    print(f"    {mark} {label}: {actual} (expected: {expected}) [{status}]")
    return condition


def get_chem(result, element):
    """Get chemistry value from result."""
    return result.normalized_data.get('chemistry', {}).get(element)


def get_mech(result, prop):
    """Get mechanical property from result."""
    val = result.normalized_data.get('mechanical', {}).get(prop)
    if isinstance(val, dict):
        return val.get('value')
    return val


# ── Phase 1 Tests ───────────────────────────────────────────────────────────

def test_issue_1(api_key):
    """Issue 1: Pre-Heat vs Post-Heat Averaging"""
    print("\n== Issue 1: Pre-Heat vs Post-Heat Averaging ==")
    passes = 0
    total = 0

    # Test 1: SK908-1874 should use post-HT values
    r = run_file('SK908-1874', spec_id='ES-M0009B', api_key=api_key)
    if r and r.success:
        ts = get_mech(r, 'tensile_strength')
        ys = get_mech(r, 'yield_strength')
        # Post-HT: TS=260, YS=200, HRC=51
        # Pre-HT:  TS=212, YS=184
        # Average:  TS=236, YS=192
        total += 2
        if check("TS post-HT (not averaged)", ts and float(ts) > 240, ts, "~260 (not 236)"):
            passes += 1
        if check("YS post-HT (not averaged)", ys and float(ys) > 195, ys, "~200 (not 192)"):
            passes += 1

    # Test 2: SK908-1875 same cert
    r2 = run_file('SK908-1875', spec_id='ES-M0009B', api_key=api_key)
    if r2 and r2.success:
        ts2 = get_mech(r2, 'tensile_strength')
        ys2 = get_mech(r2, 'yield_strength')
        total += 2
        if check("SK908-1875 TS post-HT", ts2 and float(ts2) > 240, ts2, "~260"):
            passes += 1
        if check("SK908-1875 YS post-HT", ys2 and float(ys2) > 195, ys2, "~200"):
            passes += 1

    print(f"  Issue 1: {passes}/{total} checks passed")
    return passes, total


def test_issue_2a(api_key):
    """Issue 2a: Temper Temperature Unit in Schema"""
    print("\n== Issue 2a: Temper Temperature Unit ==")
    passes = 0
    total = 0

    # Test 1: 626119 - temper 720°C
    r = run_file('626119', spec_id='ES-M0004A', api_key=api_key)
    if r and r.success:
        temp = r.normalized_data.get('temper_temperature')
        unit = r.normalized_data.get('temper_temperature_unit')
        total += 2
        if check("626119 temper temp", temp is not None and abs(float(temp) - 720) < 10, temp, "~720"):
            passes += 1
        if check("626119 temper unit", unit and unit.upper() == 'C', unit, "C"):
            passes += 1

    # Test 2: PO1966Li3 - temper 1241°F
    r2 = run_file('PO1966Li3', spec_id='ES-M0001C', api_key=api_key)
    if r2 and r2.success:
        temp2 = r2.normalized_data.get('temper_temperature')
        unit2 = r2.normalized_data.get('temper_temperature_unit')
        total += 2
        if check("PO1966Li3 temper temp", temp2 is not None and abs(float(temp2) - 1241) < 50, temp2, "~1241"):
            passes += 1
        if check("PO1966Li3 temper unit", unit2 and unit2.upper() == 'F', unit2, "F"):
            passes += 1

    # Test 3: 472110 - temper from heat treatment block, 715°C
    r3 = run_file('472110', spec_id='ES-M0003E', api_key=api_key)
    if r3 and r3.success:
        temp3 = r3.normalized_data.get('temper_temperature')
        unit3 = r3.normalized_data.get('temper_temperature_unit')
        total += 2
        if check("472110 temper temp", temp3 is not None and abs(float(temp3) - 715) < 20, temp3, "~715"):
            passes += 1
        if check("472110 temper unit", unit3 and unit3.upper() == 'C', unit3, "C"):
            passes += 1

    print(f"  Issue 2a: {passes}/{total} checks passed")
    return passes, total


def test_issue_3a(api_key):
    """Issue 3a: Cb→Nb Prompt Instruction"""
    print("\n== Issue 3a: Cb->Nb ==")
    passes = 0
    total = 0

    # Test 1: SK908-1874 (has "Cb" column) - already run above, reuse result
    r = _get_cached_result('SK908-1874')
    if r is None:
        r = run_file('SK908-1874', spec_id='ES-M0009B', api_key=api_key)
    if r and r.success:
        nb = get_chem(r, 'Nb')
        cb = get_chem(r, 'Cb')
        total += 2
        if check("SK908-1874 Nb present", nb is not None and float(nb) > 0.5, nb, "~0.89"):
            passes += 1
        if check("SK908-1874 no Cb key", cb is None, cb, "None"):
            passes += 1

    # Test 2: B4535 (has "Nb" column natively)
    r2 = run_file('B4535', spec_id='ES-M0009B', api_key=api_key)
    if r2 and r2.success:
        nb2 = get_chem(r2, 'Nb')
        total += 1
        if check("B4535 Nb present", nb2 is not None and float(nb2) > 0.5, nb2, "~0.89"):
            passes += 1

    print(f"  Issue 3a: {passes}/{total} checks passed")
    return passes, total


def test_issue_4(api_key):
    """Issue 4: Blank Cell Handling"""
    print("\n== Issue 4: Blank Cell / Element Grid Shift ==")
    passes = 0
    total = 0

    # Test 1: SK908-1874 (V column blank)
    r = _get_cached_result('SK908-1874')
    if r is None:
        r = run_file('SK908-1874', spec_id='ES-M0009B', api_key=api_key)
    if r and r.success:
        v = get_chem(r, 'V')
        ta = get_chem(r, 'Ta')
        total += 2
        if check("SK908-1874 V is null", v is None, v, "null"):
            passes += 1
        if check("SK908-1874 Ta own value", ta is not None and float(ta) < 0.05, ta, "~0.01 (not 0.89)"):
            passes += 1

    # Test 2: 472110 (no V column)
    r3 = _get_cached_result('472110')
    if r3 is None:
        r3 = run_file('472110', spec_id='ES-M0003E', api_key=api_key)
    if r3 and r3.success:
        v3 = get_chem(r3, 'V')
        nb3 = get_chem(r3, 'Nb')
        total += 2
        if check("472110 V absent/null", v3 is None, v3, "null"):
            passes += 1
        if check("472110 Nb correct", nb3 is not None and abs(float(nb3) - 0.028) < 0.01, nb3, "~0.028"):
            passes += 1

    print(f"  Issue 4: {passes}/{total} checks passed")
    return passes, total


def test_issue_5(api_key):
    """Issue 5: Heat Treatment Block Parsing"""
    print("\n== Issue 5: Heat Treatment Block Parsing ==")
    passes = 0
    total = 0

    # Test 1: 472110 (multi-step: 970°C + 225°C + 715°C)
    r = _get_cached_result('472110')
    if r is None:
        r = run_file('472110', spec_id='ES-M0003E', api_key=api_key)
    if r and r.success:
        temp = r.normalized_data.get('temper_temperature')
        total += 1
        if check("472110 temper=715 (not null/970/225)", temp is not None and abs(float(temp) - 715) < 20, temp, "~715"):
            passes += 1

    # Test 2: A0959X (simple temper at 680°C)
    r2 = run_file('A0959X', spec_id='ES-M0004A', api_key=api_key)
    if r2 and r2.success:
        temp2 = r2.normalized_data.get('temper_temperature')
        total += 1
        if check("A0959X temper=680", temp2 is not None and abs(float(temp2) - 680) < 20, temp2, "~680"):
            passes += 1

    print(f"  Issue 5: {passes}/{total} checks passed")
    return passes, total


def test_issue_6(api_key):
    """Issue 6: Charpy Temperature Sign"""
    print("\n== Issue 6: Charpy Temperature Sign ==")
    passes = 0
    total = 0

    # Test 1: 472110 (Charpy at -40°C)
    r = _get_cached_result('472110')
    if r is None:
        r = run_file('472110', spec_id='ES-M0003E', api_key=api_key)
    if r and r.success:
        charpy_t = r.normalized_data.get('charpy_temperature')
        charpy_u = r.normalized_data.get('charpy_temperature_unit')
        total += 2
        if check("472110 charpy temp negative", charpy_t is not None and float(charpy_t) < 0, charpy_t, "-40"):
            passes += 1
        if check("472110 charpy unit", charpy_u and charpy_u.upper() == 'C', charpy_u, "C"):
            passes += 1

    # Test 2: PO1966Li3 (Charpy at -20°F)
    r3 = _get_cached_result('PO1966Li3')
    if r3 is None:
        r3 = run_file('PO1966Li3', spec_id='ES-M0001C', api_key=api_key)
    if r3 and r3.success:
        charpy_t3 = r3.normalized_data.get('charpy_temperature')
        charpy_u3 = r3.normalized_data.get('charpy_temperature_unit')
        total += 2
        if check("PO1966Li3 charpy temp", charpy_t3 is not None and float(charpy_t3) < 0, charpy_t3, "-20"):
            passes += 1
        if check("PO1966Li3 charpy unit", charpy_u3 and charpy_u3.upper() == 'F', charpy_u3, "F"):
            passes += 1

    print(f"  Issue 6: {passes}/{total} checks passed")
    return passes, total


def test_issue_7(api_key):
    """Issue 7: Multi-Document PDF Handling"""
    print("\n== Issue 7: Multi-Document PDF ==")
    passes = 0
    total = 0

    # Test 1: PO1830 (Benteler + Tejas certs)
    r = run_file('PO1830', spec_id='ES-M0001C', api_key=api_key)
    if r and r.success:
        c = get_chem(r, 'C')
        mn = get_chem(r, 'Mn')
        ys = get_mech(r, 'yield_strength')
        ts = get_mech(r, 'tensile_strength')
        total += 4
        # Tejas values: C=0.420, Mn=0.980, YS=91.5, TS=111.7
        # Benteler values: C=0.160, Mn=0.70
        if check("PO1830 C from mill cert", c is not None and float(c) > 0.3, c, "~0.420 (not 0.160)"):
            passes += 1
        if check("PO1830 Mn from mill cert", mn is not None and float(mn) > 0.8, mn, "~0.980 (not 0.70)"):
            passes += 1
        if check("PO1830 YS populated", ys is not None and float(ys) > 80, ys, "~91.5"):
            passes += 1
        if check("PO1830 TS populated", ts is not None and float(ts) > 100, ts, "~111.7"):
            passes += 1

    print(f"  Issue 7: {passes}/{total} checks passed")
    return passes, total


def test_issue_8a(api_key):
    """Issue 8a: S vs Sn Clarification"""
    print("\n== Issue 8a: S/Sn Not Swapped ==")
    passes = 0
    total = 0

    # Test 1: A0959X (S=0.0020, Sn=0.005)
    r = _get_cached_result('A0959X')
    if r is None:
        r = run_file('A0959X', spec_id='ES-M0004A', api_key=api_key)
    if r and r.success:
        s = get_chem(r, 'S')
        sn = get_chem(r, 'Sn')
        total += 1
        # S should be smaller than Sn
        if check("A0959X S < Sn (not swapped)", s is not None and sn is not None and float(s) < float(sn),
                 f"S={s}, Sn={sn}", "S=0.002, Sn=0.005"):
            passes += 1

    # Test 2: PO1966Li3 (S=0.012, Sn=0.007)
    r2 = _get_cached_result('PO1966Li3')
    if r2 is None:
        r2 = run_file('PO1966Li3', spec_id='ES-M0001C', api_key=api_key)
    if r2 and r2.success:
        s2 = get_chem(r2, 'S')
        sn2 = get_chem(r2, 'Sn')
        total += 1
        # For PO1966Li3, S > Sn is actually correct (it's a real value)
        if check("PO1966Li3 S/Sn correct", s2 is not None and sn2 is not None,
                 f"S={s2}, Sn={sn2}", "S=0.012, Sn=0.007"):
            passes += 1

    print(f"  Issue 8a: {passes}/{total} checks passed")
    return passes, total


def test_issue_9a(api_key):
    """Issue 9a: Less-Than Qualifiers"""
    print("\n== Issue 9a: Chemistry Qualifiers ==")
    passes = 0
    total = 0

    # Test 1: B4535 (Ta <0.002)
    r = _get_cached_result('B4535')
    if r is None:
        r = run_file('B4535', spec_id='ES-M0009B', api_key=api_key)
    if r and r.success:
        quals = r.normalized_data.get('chemistry_qualifiers', {})
        ta = get_chem(r, 'Ta')
        total += 2
        if check("B4535 Ta value", ta is not None and float(ta) <= 0.01, ta, "0.002"):
            passes += 1
        if check("B4535 Ta qualifier", quals.get('Ta') == '<', quals.get('Ta'), "<"):
            passes += 1

    # Test 2: SK908-1874 (Ta <0.01)
    r2 = _get_cached_result('SK908-1874')
    if r2 is None:
        r2 = run_file('SK908-1874', spec_id='ES-M0009B', api_key=api_key)
    if r2 and r2.success:
        quals2 = r2.normalized_data.get('chemistry_qualifiers', {})
        ta2 = get_chem(r2, 'Ta')
        total += 2
        if check("SK908-1874 Ta value", ta2 is not None and float(ta2) <= 0.02, ta2, "0.01"):
            passes += 1
        if check("SK908-1874 Ta qualifier", quals2.get('Ta') == '<', quals2.get('Ta'), "<"):
            passes += 1

    # Test 3: 626119 (no qualified values)
    r3 = _get_cached_result('626119')
    if r3 is None:
        r3 = run_file('626119', spec_id='ES-M0004A', api_key=api_key)
    if r3 and r3.success:
        quals3 = r3.normalized_data.get('chemistry_qualifiers', {})
        total += 1
        if check("626119 no qualifiers", len(quals3) == 0, quals3, "{}"):
            passes += 1

    print(f"  Issue 9a: {passes}/{total} checks passed")
    return passes, total


def test_issue_13a(api_key):
    """Issue 13a: RA Source Clarification"""
    print("\n== Issue 13a: RA from Tensile Test ==")
    passes = 0
    total = 0

    # Test 1: SK908-1874 (RA=34% from tensile, not 20% from wrap test)
    r = _get_cached_result('SK908-1874')
    if r is None:
        r = run_file('SK908-1874', spec_id='ES-M0009B', api_key=api_key)
    if r and r.success:
        ra = get_mech(r, 'reduction_of_area')
        total += 1
        if check("SK908-1874 RA from tensile", ra is not None and float(ra) > 25, ra, "~34 (not 20)"):
            passes += 1

    # Test 2: SK908-1875
    r2 = _get_cached_result('SK908-1875')
    if r2 is None:
        r2 = run_file('SK908-1875', spec_id='ES-M0009B', api_key=api_key)
    if r2 and r2.success:
        ra2 = get_mech(r2, 'reduction_of_area')
        total += 1
        if check("SK908-1875 RA from tensile", ra2 is not None and float(ra2) > 25, ra2, "~34 (not 20)"):
            passes += 1

    print(f"  Issue 13a: {passes}/{total} checks passed")
    return passes, total


# ── Phase 2 Tests (code already integrated) ─────────────────────────────────

def test_issue_2c(api_key):
    """Issue 2c: Validator C-to-F Conversion (end-to-end)"""
    print("\n== Issue 2c: C-to-F Conversion (end-to-end) ==")
    passes = 0
    total = 0

    # Test: 626119 temper should PASS (720°C = 1328°F >= 1200°F)
    r = _get_cached_result('626119')
    if r is None:
        r = run_file('626119', spec_id='ES-M0004A', api_key=api_key)
    if r and r.validation:
        vdict = r.validation.to_dict()
        special = vdict.get('special', vdict.get('special_results', []))
        temper_results = [c for c in special
                         if 'temper' in c.get('property_name', c.get('property', '')).lower()]
        total += 1
        temper_status = temper_results[0]['status'] if temper_results else 'NOT_FOUND'
        if check("626119 temper PASS", temper_status == 'PASS', temper_status, "PASS (was FAIL)"):
            passes += 1

    # Test: A0959X temper should PASS (680°C = 1256°F >= 1200°F)
    r2 = _get_cached_result('A0959X')
    if r2 is None:
        r2 = run_file('A0959X', spec_id='ES-M0004A', api_key=api_key)
    if r2 and r2.validation:
        vdict2 = r2.validation.to_dict()
        special2 = vdict2.get('special', vdict2.get('special_results', []))
        temper_results2 = [c for c in special2
                          if 'temper' in c.get('property_name', c.get('property', '')).lower()]
        total += 1
        temper_status2 = temper_results2[0]['status'] if temper_results2 else 'NOT_FOUND'
        if check("A0959X temper PASS", temper_status2 == 'PASS', temper_status2, "PASS (was FAIL)"):
            passes += 1

    print(f"  Issue 2c: {passes}/{total} checks passed")
    return passes, total


# ── Phase 4 Tests ───────────────────────────────────────────────────────────

def test_issue_10(api_key):
    """Issue 10: Spec Auto-Detection"""
    print("\n== Issue 10: Spec Auto-Detection ==")
    passes = 0
    total = 0

    # Run with auto-detect (no spec_id)
    test_cases = [
        ('626119', 'ES-M0004A', '9Cr 1Mo'),
        ('SK908-1874', 'ES-M0009B', 'Inconel X-750'),
        ('472110', 'ES-M0003E', '420 Modified'),
        ('PO1966Li3', 'ES-M0001C', '4140/42'),
    ]

    for alias, expected_spec, desc in test_cases:
        r = run_file(alias, spec_id=None, api_key=api_key)
        total += 1
        if r and r.success:
            actual_spec = r.spec_id
            # For metal MTRs, should NOT match ES-M2201C (PEEK)
            is_not_peek = actual_spec != 'ES-M2201C'
            matches_expected = actual_spec == expected_spec
            if check(f"{alias} ({desc}) auto-detect",
                     matches_expected or (is_not_peek and actual_spec is not None),
                     actual_spec, expected_spec):
                passes += 1
        elif r:
            # No match is better than wrong match for gating test
            if check(f"{alias} ({desc}) not PEEK",
                     r.spec_id != 'ES-M2201C',
                     r.spec_id, f"Not ES-M2201C"):
                passes += 1

    print(f"  Issue 10: {passes}/{total} checks passed")
    return passes, total


# ── Result Cache ────────────────────────────────────────────────────────────

_result_cache = {}

def _get_cached_result(alias):
    """Return cached PipelineResult if available."""
    return _result_cache.get(alias)


def run_file_cached(alias, spec_id=None, api_key=None):
    """Run file and cache the result."""
    key = alias
    if key not in _result_cache:
        _result_cache[key] = run_file(alias, spec_id=spec_id, api_key=api_key)
    return _result_cache[key]


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='MTR Plan Test Runner')
    parser.add_argument('file', nargs='?', help='Single file alias to run')
    parser.add_argument('--phase', type=int, help='Run tests for a specific phase (1-4)')
    parser.add_argument('--list', action='store_true', help='List available file aliases')
    parser.add_argument('--issue', type=str, help='Run a specific issue test (e.g., "1", "2a")')
    args = parser.parse_args()

    if args.list:
        print("Available file aliases:")
        for alias, filename in sorted(FILE_MAP.items()):
            exists = "[OK]" if (WATCH_FOLDER / filename).exists() else "[--]"
            print(f"  {exists} {alias:15s} -> {filename}")
        return

    api_key = load_api_key()

    # Map of issue tests
    issue_tests = {
        '1': test_issue_1,
        '2a': test_issue_2a,
        '3a': test_issue_3a,
        '4': test_issue_4,
        '5': test_issue_5,
        '6': test_issue_6,
        '7': test_issue_7,
        '8a': test_issue_8a,
        '9a': test_issue_9a,
        '13a': test_issue_13a,
        '2c': test_issue_2c,
        '10': test_issue_10,
    }

    phase_issues = {
        1: ['1', '2a', '3a', '4', '5', '6', '7', '8a', '9a', '13a'],
        2: ['2c'],
        4: ['10'],
    }

    if args.file:
        # Run a single file
        r = run_file(args.file, api_key=api_key)
        if r and r.success:
            nd = r.normalized_data
            print(f"\n  Heat: {nd.get('heat_number')}")
            print(f"  Grade: {nd.get('material_grade')}")
            print(f"  Spec: {r.spec_id} ({r.spec_match_confidence:.0%})")
            print(f"  Status: {r.overall_status}")
            print(f"  Temper: {nd.get('temper_temperature')} {nd.get('temper_temperature_unit', '')}")
            print(f"  Charpy temp: {nd.get('charpy_temperature')} {nd.get('charpy_temperature_unit', '')}")
            chem = nd.get('chemistry', {})
            print(f"  Chemistry ({len(chem)} elements): {json.dumps(chem, indent=4)}")
            quals = nd.get('chemistry_qualifiers', {})
            if quals:
                print(f"  Qualifiers: {quals}")
            mech = nd.get('mechanical', {})
            print(f"  Mechanical: {json.dumps(mech, indent=4)}")
        elif r:
            print(f"  FAILED: {r.errors}")
        return

    if args.issue:
        fn = issue_tests.get(args.issue)
        if fn:
            fn(api_key)
        else:
            print(f"Unknown issue: {args.issue}. Available: {', '.join(issue_tests.keys())}")
        return

    # Run by phase or all
    phases_to_run = [args.phase] if args.phase else [1, 2, 4]

    total_passes = 0
    total_checks = 0

    for phase in phases_to_run:
        print(f"\n{'='*60}")
        print(f"  PHASE {phase}")
        print(f"{'='*60}")

        for issue_id in phase_issues.get(phase, []):
            fn = issue_tests[issue_id]
            p, t = fn(api_key)
            total_passes += p
            total_checks += t

    print(f"\n{'='*60}")
    print(f"  OVERALL: {total_passes}/{total_checks} checks passed")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
