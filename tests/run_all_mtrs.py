#!/usr/bin/env python3
"""
Run all MTR test files through the pipeline and compare with previous results.
Tracks token usage per file and total.

Usage:
    python tests/run_all_mtrs.py
"""

import json
import os
import sys
import time
from pathlib import Path

# Fix Windows console encoding for Unicode characters (degree symbols etc.)
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from lib.pipeline import process_document

WATCH_FOLDER = Path(r"C:\Users\qascanner\Documents\GitHub\material-validator\.MTR Validator Watch Folder Test")
CONFIG_PATH = Path(r"C:\Users\qascanner\Documents\GitHub\material-validator\config.json")
RESULTS_DIR = Path(r"C:\Users\qascanner\Documents\GitHub\material-validator\tests\plan_results")
NEW_RESULTS_DIR = Path(r"C:\Users\qascanner\Documents\GitHub\material-validator\tests\plan_results_new")

# Files to process with their spec IDs (matching previous test runs)
TEST_FILES = {
    'PO1966Li3':  ('2026.02.Packing Slip.PO1966Li3.pdf', 'ES-M0001C'),
    '472110':     ('472110-1975.pdf', 'ES-M0003E'),
    '626119':     ('626119-3409-01-1783.pdf', 'ES-M0004A'),
    'B4535':      ('B4535-1831.pdf', 'ES-M0009B'),
    'SK908-1874': ('SK908-13628-1874.pdf', 'ES-M0009B'),
    'SK908-1875': ('SK908-13628-1875.pdf', 'ES-M0009B'),
    'PO1830':     ('2026.02.DOCS.PO1830.pdf', 'ES-M0001C'),
    'A0959X':     ('2026.02.DOCS.PO1783Li1.2.pdf', 'ES-M0004A'),
}


def load_api_key():
    with open(CONFIG_PATH) as f:
        return json.load(f)['anthropic_api_key']


def compare_results(alias, old_data, new_data):
    """Compare key fields between old and new results."""
    diffs = []

    # Compare top-level fields
    for key in ['success', 'spec_id', 'overall_status']:
        old_val = old_data.get(key)
        new_val = new_data.get(key)
        if old_val != new_val:
            diffs.append(f"  {key}: {old_val} -> {new_val}")

    # Compare normalized chemistry
    old_chem = old_data.get('normalized_data', {}).get('chemistry', {})
    new_chem = new_data.get('normalized_data', {}).get('chemistry', {})

    all_elements = set(list(old_chem.keys()) + list(new_chem.keys()))
    for elem in sorted(all_elements):
        old_v = old_chem.get(elem)
        new_v = new_chem.get(elem)
        if old_v != new_v:
            # Tolerate small float differences
            try:
                if old_v is not None and new_v is not None and abs(float(old_v) - float(new_v)) < 0.001:
                    continue
            except (ValueError, TypeError):
                pass
            diffs.append(f"  chemistry.{elem}: {old_v} -> {new_v}")

    # Compare normalized mechanical
    old_mech = old_data.get('normalized_data', {}).get('mechanical', {})
    new_mech = new_data.get('normalized_data', {}).get('mechanical', {})

    all_props = set(list(old_mech.keys()) + list(new_mech.keys()))
    for prop in sorted(all_props):
        old_v = old_mech.get(prop)
        new_v = new_mech.get(prop)
        if old_v != new_v:
            try:
                if old_v is not None and new_v is not None and abs(float(old_v) - float(new_v)) < 0.1:
                    continue
            except (ValueError, TypeError):
                pass
            diffs.append(f"  mechanical.{prop}: {old_v} -> {new_v}")

    # Compare key special fields
    for field in ['temper_temperature', 'temper_temperature_unit', 'charpy_temperature', 'charpy_temperature_unit', 'heat_number', 'material_grade']:
        old_v = old_data.get('normalized_data', {}).get(field)
        new_v = new_data.get('normalized_data', {}).get(field)
        if old_v != new_v:
            try:
                if old_v is not None and new_v is not None and abs(float(old_v) - float(new_v)) < 0.1:
                    continue
            except (ValueError, TypeError):
                pass
            diffs.append(f"  {field}: {old_v} -> {new_v}")

    return diffs


def main():
    api_key = load_api_key()
    NEW_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    total_input_tokens = 0
    total_output_tokens = 0
    total_time = 0
    all_diffs = {}

    print(f"{'='*70}")
    print(f"  MTR Pipeline Regression Test — {len(TEST_FILES)} files")
    print(f"{'='*70}\n")

    for alias, (filename, spec_id) in TEST_FILES.items():
        pdf_path = WATCH_FOLDER / filename
        if not pdf_path.exists():
            print(f"[SKIP] {alias}: file not found")
            continue

        print(f"[RUN]  {alias} ({filename}) spec={spec_id}")
        t0 = time.time()

        result = process_document(
            pdf_path=str(pdf_path),
            spec_id=spec_id,
            anthropic_api_key=api_key,
            preprocessing_dpi=300,
        )

        elapsed = time.time() - t0
        total_time += elapsed

        # Extract token usage from extracted_data
        token_usage = result.extracted_data.get('_token_usage', {})
        in_tok = token_usage.get('input_tokens', 0)
        out_tok = token_usage.get('output_tokens', 0)
        total_input_tokens += in_tok
        total_output_tokens += out_tok

        status_icon = "OK" if result.success else "!!"
        print(f"  [{status_icon}] status={result.overall_status}, time={elapsed:.1f}s, tokens={in_tok}+{out_tok}={in_tok+out_tok}")

        # Save new result
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
            'token_usage': token_usage,
            'elapsed_seconds': round(elapsed, 1),
        }
        if result.validation:
            out_data['validation'] = result.validation.to_dict()

        out_file = NEW_RESULTS_DIR / f"{alias}.json"
        with open(out_file, 'w') as f:
            json.dump(out_data, f, indent=2, default=str)

        # Compare with previous results
        old_file = RESULTS_DIR / f"{alias}.json"
        if old_file.exists():
            with open(old_file) as f:
                old_data = json.load(f)
            diffs = compare_results(alias, old_data, out_data)
            if diffs:
                all_diffs[alias] = diffs
                print(f"  DIFFS vs previous:")
                for d in diffs:
                    print(f"    {d}")
            else:
                print(f"  MATCH: identical to previous results")
        else:
            print(f"  NEW: no previous results to compare")

        print()

    # Summary
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"  Files processed:  {len(TEST_FILES)}")
    print(f"  Total time:       {total_time:.1f}s ({total_time/len(TEST_FILES):.1f}s avg)")
    print(f"  Total tokens:     {total_input_tokens + total_output_tokens:,}")
    print(f"    Input tokens:   {total_input_tokens:,}")
    print(f"    Output tokens:  {total_output_tokens:,}")
    print(f"  Files with diffs: {len(all_diffs)}/{len(TEST_FILES)}")

    if all_diffs:
        print(f"\n  Changed files:")
        for alias, diffs in all_diffs.items():
            print(f"    {alias}: {len(diffs)} difference(s)")
    else:
        print(f"\n  All results match previous run!")

    print(f"{'='*70}")


if __name__ == '__main__':
    main()
