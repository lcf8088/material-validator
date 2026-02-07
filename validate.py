#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Material Cert Validator CLI

Validates Material Test Reports (MTRs) against engineering specifications.

Usage:
    ./validate.py --list-specs                      # List available specs
    ./validate.py --show-spec <spec-id>             # Show spec details
    ./validate.py --json <mtr.json> --spec <spec>   # Validate from JSON
    ./validate.py --json <mtr.json> --auto          # Auto-detect spec
    ./validate.py --pdf <file.pdf>                  # Convert PDF to images
    ./validate.py --pipeline <file.pdf>             # Full OCR pipeline
    ./validate.py --pipeline <file.pdf> --spec <id> # Pipeline with spec
"""

import argparse
import json
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))

from lib.spec_loader import SpecLoader
from lib.validator import SpecValidator, format_validation_report
from lib.matcher import SpecMatcher
from lib.extractor import (
    pdf_to_images,
    parse_extraction_response,
    normalize_extracted_data,
)


def list_specs(loader: SpecLoader) -> None:
    """List all available specs."""
    print("\n" + "=" * 65)
    print("AVAILABLE SPECIFICATIONS")
    print("=" * 65)
    print(f"{'ID':<15} {'Material':<35} {'UNS':<10}")
    print("-" * 65)

    for spec_id in sorted(loader.list_ids()):
        spec = loader.get(spec_id)
        material = spec.get('material', 'Unknown')[:33]
        uns = spec.get('uns', '-')
        print(f"{spec_id:<15} {material:<35} {uns:<10}")

    print("=" * 65)
    print(f"Total: {len(loader.list_ids())} specifications\n")


def show_spec(loader: SpecLoader, spec_id: str) -> None:
    """Show detailed spec information."""
    spec = loader.get(spec_id)

    if not spec:
        print(f"Error: Spec not found: {spec_id}")
        print(f"Available specs: {', '.join(loader.list_ids())}")
        return

    print(f"\n{'='*60}")
    print(f"SPECIFICATION: {spec_id}")
    if spec.get('revision') is not None:
        print(f"Revision: {spec.get('revision')}  Date: {spec.get('date', '-')}")
    print(f"{'='*60}")
    print(f"Material:  {spec.get('material', '-')}")
    print(f"UNS:       {spec.get('uns', '-')}")
    print(f"Condition: {spec.get('condition', '-')}")
    print(f"Grades:    {', '.join(spec.get('grades', []))}")

    if 'chemistry' in spec:
        print(f"\n{'CHEMISTRY REQUIREMENTS':}")
        print(f"  {'Element':<8} {'Min':>10} {'Max':>10}")
        print(f"  {'-'*8} {'-'*10} {'-'*10}")
        for elem, limits in spec['chemistry'].items():
            min_val = f"{limits.get('min')}" if limits.get('min') is not None else "-"
            max_val = f"{limits.get('max')}" if limits.get('max') is not None else "-"
            print(f"  {elem:<8} {min_val:>10} {max_val:>10}")

    if 'mechanical' in spec:
        print(f"\n{'MECHANICAL REQUIREMENTS':}")
        print(f"  {'Property':<25} {'Min':>10} {'Max':>10} {'Unit':<8}")
        print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*8}")
        for prop, limits in spec['mechanical'].items():
            min_val = str(limits.get('min')) if limits.get('min') is not None else "-"
            max_val = str(limits.get('max')) if limits.get('max') is not None else "-"
            unit = limits.get('unit', '')
            print(f"  {prop:<25} {min_val:>10} {max_val:>10} {unit:<8}")

    if spec.get('special_requirements'):
        print(f"\n{'SPECIAL REQUIREMENTS':}")
        for req in spec['special_requirements']:
            req_type = req.get('type', 'unknown')
            note = req.get('note', '')
            print(f"  - {req_type}: {note}")

    print()


def validate_mtr(mtr_data: dict, spec_id: str, validator: SpecValidator,
                 output_json: bool = False, no_color: bool = False) -> int:
    """Run validation and print results. Returns exit code."""
    result = validator.validate(mtr_data, spec_id)

    if output_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_validation_report(result, use_color=not no_color))

    if result.overall_status == 'PASS':
        return 0
    elif result.overall_status == 'INCOMPLETE':
        return 1
    else:
        return 2


def run_pipeline(pdf_path: str, spec_id: str = None, api_key: str = "",
                 output_json: bool = False, no_color: bool = False) -> int:
    """Run the full OCR pipeline on a PDF and validate."""
    from lib.pipeline import process_document

    if not api_key:
        # Try to load from config
        try:
            config_path = Path(__file__).parent / 'config.json'
            if config_path.exists():
                with open(config_path) as f:
                    cfg = json.load(f)
                api_key = cfg.get('anthropic_api_key', '')
        except Exception:
            pass

    if not api_key:
        print("Error: No Anthropic API key. Set it in config.json or use --api-key.")
        return 1

    def on_progress(step, pct):
        if not output_json:
            print(f"  [{pct*100:3.0f}%] {step}")

    result = process_document(
        pdf_path=pdf_path,
        spec_id=spec_id,
        anthropic_api_key=api_key,
        on_progress=on_progress,
    )

    if output_json:
        output = {
            'success': result.success,
            'spec_id': result.spec_id,
            'extracted_data': result.normalized_data,
            'errors': result.errors,
            'warnings': result.warnings,
        }
        if result.validation:
            output['validation'] = result.validation.to_dict()
        print(json.dumps(output, indent=2))
    else:
        if result.errors:
            print(f"\nPipeline Errors:")
            for err in result.errors:
                print(f"  ! {err}")

        if result.normalized_data:
            print(f"\nExtracted Data:")
            print(json.dumps(result.normalized_data, indent=2))

        if result.validation:
            print()
            print(format_validation_report(result.validation, use_color=not no_color))

    return 0 if result.success else 2


def main():
    parser = argparse.ArgumentParser(
        description='Material Cert Validator - Validate MTRs against engineering specs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Input options
    input_group = parser.add_argument_group('Input')
    input_group.add_argument('--json', type=str, metavar='FILE',
                             help='Path to pre-extracted MTR JSON file')
    input_group.add_argument('--pipeline', type=str, metavar='FILE',
                             help='Run full OCR pipeline on a PDF file')

    # Spec options
    spec_group = parser.add_argument_group('Specification')
    spec_group.add_argument('--spec', type=str, metavar='ID',
                            help='Specification ID to validate against')
    spec_group.add_argument('--auto', action='store_true',
                            help='Auto-detect specification from MTR data')

    # Info options
    info_group = parser.add_argument_group('Information')
    info_group.add_argument('--list-specs', action='store_true',
                            help='List all available specifications')
    info_group.add_argument('--show-spec', type=str, metavar='ID',
                            help='Show detailed spec information')

    # Extraction options
    extract_group = parser.add_argument_group('Extraction')
    extract_group.add_argument('--pdf', type=str, metavar='FILE',
                               help='Convert PDF to images for extraction')
    extract_group.add_argument('--parse-response', type=str, metavar='FILE',
                               help='Parse vision LLM response from file')
    extract_group.add_argument('--api-key', type=str, metavar='KEY',
                               help='Anthropic API key (overrides config)')

    # Output options
    output_group = parser.add_argument_group('Output')
    output_group.add_argument('--output-json', action='store_true',
                              help='Output results as JSON')
    output_group.add_argument('--no-color', action='store_true',
                              help='Disable colored output')

    args = parser.parse_args()

    # Initialize components
    specs_dir = Path(__file__).parent / 'specs'
    loader = SpecLoader.get_instance(str(specs_dir))
    validator = SpecValidator(str(specs_dir))
    matcher = SpecMatcher(str(specs_dir))

    # Handle info commands
    if args.list_specs:
        list_specs(loader)
        return 0

    if args.show_spec:
        show_spec(loader, args.show_spec)
        return 0

    # Handle pipeline command
    if args.pipeline:
        return run_pipeline(
            args.pipeline,
            spec_id=args.spec,
            api_key=args.api_key or "",
            output_json=args.output_json,
            no_color=args.no_color,
        )

    # Handle extraction commands
    if args.pdf:
        try:
            images = pdf_to_images(args.pdf)
            print(f"Converted {len(images)} page(s):")
            for img in images:
                print(f"  {img}")
            return 0
        except Exception as e:
            print(f"Error converting PDF: {e}")
            return 1

    if args.parse_response:
        try:
            with open(args.parse_response) as f:
                response = f.read()
            data = parse_extraction_response(response)
            data = normalize_extracted_data(data)
            print(json.dumps(data, indent=2))
            return 0
        except Exception as e:
            print(f"Error parsing response: {e}")
            return 1

    # Get MTR data from JSON
    mtr_data = None

    if args.json:
        try:
            with open(args.json) as f:
                mtr_data = json.load(f)
        except Exception as e:
            print(f"Error loading JSON: {e}")
            return 1
    else:
        parser.print_help()
        return 1

    # Determine spec to use
    spec_id = args.spec

    if args.auto and not spec_id:
        match = matcher.select_best_spec(mtr_data)
        if match:
            spec_id, confidence, reason = match
            if not args.output_json:
                print(f"\nAuto-detected spec: {spec_id}")
                print(f"  Confidence: {confidence:.0%}")
                print(f"  Reason: {reason}\n")
        else:
            print("Error: Could not auto-detect specification")
            print(f"Available specs: {', '.join(loader.list_ids())}")
            return 1

    if not spec_id:
        print("Error: No specification provided. Use --spec <ID> or --auto")
        print(f"Available specs: {', '.join(loader.list_ids())}")
        return 1

    # Run validation
    return validate_mtr(mtr_data, spec_id, validator,
                        output_json=args.output_json,
                        no_color=args.no_color)


if __name__ == '__main__':
    sys.exit(main())
