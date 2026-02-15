"""
Verification report generator — plain-text report saved alongside archived TIFFs.

Produces an audit-ready document with validation results, override annotations,
and approval signature.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from .validator import CertValidation


def generate_verification_report(
    validation: Optional[CertValidation],
    mtr_data: Dict[str, Any],
    approved_by: str,
    source_file: Optional[str] = None,
    po_number: Optional[str] = None,
) -> str:
    """
    Generate a plain-text verification report.

    Args:
        validation: CertValidation result (may be None if no spec validation)
        mtr_data: Extracted MTR data dict
        approved_by: Name of the person approving
        source_file: Original source file path
        po_number: PO number (if available)

    Returns:
        Formatted report text
    """
    now = datetime.now(timezone.utc)
    timestamp = now.strftime('%Y-%m-%d %H:%M:%S UTC')

    lines = []
    w = 62  # report width

    lines.append("=" * w)
    lines.append("MATERIAL CERT VERIFICATION REPORT".center(w))
    lines.append("Downhole & Design".center(w))
    lines.append("=" * w)
    lines.append("")

    # --- Document info ---
    heat = mtr_data.get('heat_number') or mtr_data.get('batch_number') or 'N/A'
    grade = mtr_data.get('material_grade', 'N/A')
    spec = validation.spec_id if validation else mtr_data.get('specification', 'N/A')

    lines.append(f"  Spec:            {spec}")
    if mtr_data.get('batch_number') and not mtr_data.get('heat_number'):
        lines.append(f"  Batch Number:    {heat}")
    else:
        lines.append(f"  Heat Number:     {heat}")
    lines.append(f"  Material Grade:  {grade}")
    if po_number:
        lines.append(f"  PO Number:       {po_number}")
    if source_file:
        lines.append(f"  Source File:     {Path(source_file).name}")
    lines.append(f"  Report Date:     {timestamp}")
    lines.append("")

    if not validation:
        lines.append("  No spec validation performed.")
        lines.append("")
    else:
        # --- Overall status ---
        lines.append(f"  Overall Status:  {validation.overall_status}")
        lines.append(f"  Summary:         {validation.pass_count} pass, "
                     f"{validation.fail_count} fail, "
                     f"{validation.missing_count} missing")
        lines.append("")

        # --- Chemistry ---
        if validation.chemistry_results:
            lines.append("-" * w)
            lines.append("  CHEMISTRY")
            lines.append("-" * w)
            lines.append(f"  {'Element':<10}{'Min':>10}{'Max':>10}{'Actual':>10}  {'Status'}")
            lines.append("  " + "-" * (w - 4))
            for r in validation.chemistry_results:
                smin = f"{r.spec_min:.4f}" if r.spec_min is not None else "-"
                smax = f"{r.spec_max:.4f}" if r.spec_max is not None else "-"
                actual = f"{r.actual_value:.4f}" if r.actual_value is not None else "-"
                lines.append(f"  {r.property_name:<10}{smin:>10}{smax:>10}{actual:>10}  {r.status}")
                if r.is_overridden:
                    lines.append(f"    ** OVERRIDDEN from {r.original_status} "
                                 f"by {r.override_by}: {r.override_reason}")
            lines.append("")

        # --- Mechanical ---
        if validation.mechanical_results:
            lines.append("-" * w)
            lines.append("  MECHANICAL PROPERTIES")
            lines.append("-" * w)
            lines.append(f"  {'Property':<20}{'Min':>10}{'Max':>10}{'Actual':>10}  {'Status'}")
            lines.append("  " + "-" * (w - 4))
            for r in validation.mechanical_results:
                smin = f"{r.spec_min:.1f}" if r.spec_min is not None else "-"
                smax = f"{r.spec_max:.1f}" if r.spec_max is not None else "-"
                actual = f"{r.actual_value:.2f}" if r.actual_value is not None else "-"
                lines.append(f"  {r.property_name:<20}{smin:>10}{smax:>10}{actual:>10}  {r.status}")
                if r.is_overridden:
                    lines.append(f"    ** OVERRIDDEN from {r.original_status} "
                                 f"by {r.override_by}: {r.override_reason}")
            lines.append("")

        # --- Special requirements ---
        if validation.special_results:
            lines.append("-" * w)
            lines.append("  SPECIAL REQUIREMENTS")
            lines.append("-" * w)
            for r in validation.special_results:
                note = f" - {r.note}" if r.note else ""
                lines.append(f"  {r.property_name}: {r.status}{note}")
                if r.is_overridden:
                    lines.append(f"    ** OVERRIDDEN from {r.original_status} "
                                 f"by {r.override_by}: {r.override_reason}")
            lines.append("")

        # --- Errors / Warnings ---
        if validation.errors:
            lines.append("-" * w)
            lines.append("  ERRORS")
            lines.append("-" * w)
            for err in validation.errors:
                lines.append(f"    {err}")
            lines.append("")

        if validation.warnings:
            lines.append("-" * w)
            lines.append("  WARNINGS")
            lines.append("-" * w)
            for warn in validation.warnings:
                lines.append(f"    {warn}")
            lines.append("")

    # --- Approval signature ---
    lines.append("=" * w)
    lines.append("  APPROVAL")
    lines.append("=" * w)
    lines.append(f"  Approved By:     {approved_by}")
    lines.append(f"  Date:            {timestamp}")
    lines.append("")
    lines.append("  This report was generated by D&D MTR Validator.")
    lines.append("=" * w)

    return "\n".join(lines) + "\n"
