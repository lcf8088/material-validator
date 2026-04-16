"""
Audit YAML specs against lean spec markdown files.

For each ES-M*.yaml in specs/, finds the corresponding lean spec
.txt in docs/MTR Lean Specs/, parses markdown tables, and reports
any value mismatches or missing/extra fields.
"""
import re
import sys
import yaml
from pathlib import Path

ROOT = Path(__file__).parent
SPECS_DIR = ROOT / "specs"
LEAN_DIR = ROOT / "docs" / "MTR Lean Specs"


def parse_md_table(text: str) -> list[dict]:
    """Parse a markdown table into list of dicts keyed by header."""
    lines = [l.strip() for l in text.splitlines() if l.strip().startswith("|")]
    if len(lines) < 2:
        return []
    # Drop separator row (---)
    lines = [l for l in lines if not re.match(r"^\|[\s\-|:]+\|$", l)]
    if len(lines) < 2:
        return []
    headers = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[1:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


def parse_num(s: str) -> float | None:
    """Parse a numeric cell; return None for '-' or blank or 'Report'."""
    if s is None:
        return None
    orig = s.strip()
    if orig in ("", "-", "—", "Balance", "Remainder", "Report"):
        return None
    s = orig.replace(",", "")
    # Strip parenthetical annotations like "30 HRc (277 HBW)"
    s = re.sub(r"\s*\(.*?\)\s*", "", s)
    # Keep only leading number (optional leading qualifier <, >, ≤, ≥)
    m = re.match(r"^\s*[<>≤≥]?=?\s*(-?\d+(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def extract_section(text: str, header: str) -> str:
    """Extract content between a markdown `## Header` and the next `## `."""
    pattern = rf"##\s+{re.escape(header)}\s*\n(.*?)(?=\n##\s|\Z)"
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else ""


def parse_lean_chemistry(text: str) -> dict[str, tuple[float | None, float | None]]:
    """Returns {element: (min, max)} from Chemical Composition section."""
    section = extract_section(text, "Chemical Composition")
    if not section:
        return {}
    rows = parse_md_table(section)
    result = {}
    for row in rows:
        elem = row.get("Element") or row.get("Component") or ""
        elem = elem.strip()
        if not elem or elem.startswith("-"):
            continue
        min_s = row.get("Minimum (%)") or row.get("Minimum") or ""
        max_s = row.get("Maximum (%)") or row.get("Maximum") or ""
        result[elem] = (parse_num(min_s), parse_num(max_s))
    return result


def parse_lean_mechanical(text: str) -> list[dict]:
    """Returns list of {property, min, max, unit} rows from all mechanical tables."""
    section = extract_section(text, "Mechanical Properties")
    if not section:
        return []
    rows = []
    for block in re.split(r"\n\s*\n", section):
        if "|" not in block:
            continue
        table_rows = parse_md_table(block)
        for tr in table_rows:
            prop = (tr.get("Property") or tr.get("Property (All UNS)") or "").strip()
            if not prop:
                continue
            min_s = tr.get("Minimum", "")
            max_s = tr.get("Maximum", "")
            tm_s = tr.get("Test Method", "")
            rows.append({
                "property": prop,
                "min": parse_num(min_s),
                "max": parse_num(max_s),
                "min_raw": min_s,
                "max_raw": max_s,
                "test_method": tm_s,
            })
    return rows


# Map lean spec property names to YAML mechanical keys
PROP_MAP = {
    "Yield Strength": "yield_strength",
    "Tensile Strength": "tensile_strength",
    "Tensile Strength at Break": "tensile_strength",
    "Tensile Strength at Yield": "yield_strength",
    "Elongation": "elongation",
    "Elongation at Break": "elongation",
    "Reduction in Area": "reduction_of_area",
    "Reduction of Area": "reduction_of_area",
    "Compression Set": "compression_set",
    "Tensile Modulus (100%)": "tensile_modulus_100",
    "Modulus of Elasticity": "modulus_of_elasticity",
    "Specific Gravity": "specific_gravity",
    "Transverse Rupture Strength": "transverse_rupture_strength",
}


def hardness_key(row: dict) -> str | None:
    """Map a hardness row to a YAML key by checking all cells."""
    blob = " ".join([
        row.get("property", ""),
        row.get("min_raw", ""),
        row.get("max_raw", ""),
        row.get("test_method", ""),
    ]).lower()
    if "shore a" in blob:
        return "hardness_shore_a"
    if "shore d" in blob:
        return "hardness_shore_d"
    if "hrc" in blob:
        return "hardness_hrc"
    if "hrb" in blob or re.search(r"\brb\b", blob):
        return "hardness_hrb"
    if "hra" in blob or "b294" in blob:
        return "hardness_hra"
    if "hbw" in blob or "brinell" in blob or "e10" in blob:
        return "hardness_hbw"
    return None


def lean_file_for(spec_id: str) -> Path | None:
    """Find the lean spec .txt for a given spec id (handles variants and supplements)."""
    # Strip supplier suffix for ES-M0003G variants → use the base ES-M#### file
    m = re.match(r"(ES-M\d+[A-Z])", spec_id)
    base_id = m.group(1) if m else spec_id
    for f in LEAN_DIR.glob(f"{base_id}_*.txt"):
        return f
    return None


def approx_eq(a, b, tol=1e-4):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) < tol


# Map YAML element keys to lean spec element names (for reverse lookup)
def normalize_elem(e: str) -> str:
    e = e.strip()
    return e


# Specs that bundle supplier-specific chemistry tables (skip chemistry audit)
BUNDLED_CHEM_SPECS = {"ES-M0003G-JFE", "ES-M0003G-NKK", "ES-M0003G-S41425",
                     "ES-M0003G-S41426", "ES-M0003G-S41427"}
# API 14A supplements: base-spec content, melt_practice only is new
SUPPLEMENT_SPECS = {"ES-M0009F", "ES-M0009G", "ES-M0009H", "ES-M0009J",
                    "ES-M0009K", "ES-M0001L", "ES-M0001P"}


def audit_spec(yaml_path: Path) -> list[str]:
    """Audit one YAML file against its lean spec. Returns list of issues."""
    with open(yaml_path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    spec_id = spec["id"]
    issues = []

    lean_path = lean_file_for(spec_id)
    if lean_path is None:
        issues.append(f"[MISSING] no lean file matches {spec_id}")
        return issues

    lean_text = lean_path.read_text(encoding="utf-8")
    is_variant = spec_id in BUNDLED_CHEM_SPECS
    is_supplement = spec_id in SUPPLEMENT_SPECS

    # --- Chemistry audit ---
    if not is_variant and not is_supplement:
        lean_chem = parse_lean_chemistry(lean_text)
        yaml_chem = spec.get("chemistry", {}) or {}

        # Compound/common-name → element symbol mapping
        COMPOUND_TO_ELEMENT = {
            "Cobalt binder": "Co",
            "Tungsten Carbide": "WC",  # not an element; handled separately
            "Tin": "Sn",
        }

        def lean_aliases(lean_key: str) -> set[str]:
            """Return set of element symbols equivalent to the lean key."""
            # map common compound names
            if lean_key in COMPOUND_TO_ELEMENT:
                return {COMPOUND_TO_ELEMENT[lean_key]}
            # strip parens: "Ni (Ni+Co)" → "Ni"; "Sn (Tin)" → "Sn"
            s = re.sub(r"\s*\(.*?\)", "", lean_key).strip()
            # split on + and /: "Cb/Nb+Ta" → ["Cb", "Nb", "Ta"]
            parts = re.split(r"[+/]", s)
            return {p.strip() for p in parts if p.strip()}

        CATCHALL_ROWS = {"Other, each", "Other, total"}
        COMPOUND_ROWS = {"Tungsten Carbide", "Cobalt binder"}  # handled via composition

        # Check every element in YAML
        for elem, rng in yaml_chem.items():
            lean_key = None
            for lk in lean_chem:
                if elem in lean_aliases(lk):
                    lean_key = lk
                    break
            if lean_key is None:
                issues.append(f"  [EXTRA-CHEM] {elem}: not in lean spec")
                continue
            lmin, lmax = lean_chem[lean_key]
            ymin = rng.get("min") if isinstance(rng, dict) else None
            ymax = rng.get("max") if isinstance(rng, dict) else None
            if not approx_eq(ymin, lmin):
                issues.append(f"  [CHEM-MIN] {elem}: yaml={ymin} lean={lmin}  (lean key: '{lean_key}')")
            if not approx_eq(ymax, lmax):
                issues.append(f"  [CHEM-MAX] {elem}: yaml={ymax} lean={lmax}  (lean key: '{lean_key}')")

        # Check elements in lean missing from YAML
        for lk, (lmin, lmax) in lean_chem.items():
            if lk in CATCHALL_ROWS or lk in COMPOUND_ROWS:
                continue
            aliases = lean_aliases(lk)
            present = any(e in aliases for e in yaml_chem)
            if not present and (lmin is not None or lmax is not None):
                issues.append(f"  [MISSING-CHEM] lean has '{lk}' ({lmin}-{lmax}), not in yaml")

    # --- Mechanical audit ---
    if not is_variant and not is_supplement:
        lean_mech_rows = parse_lean_mechanical(lean_text)
        yaml_mech = spec.get("mechanical", {}) or {}
        # Build expected YAML key → lean row map
        expected = {}  # {yaml_key: [lean rows]}
        for row in lean_mech_rows:
            prop = row["property"]
            # Skip info-only rows (both min and max are "Report" or blank)
            if row["min"] is None and row["max"] is None and (
                "report" in row["min_raw"].lower() or "report" in row["max_raw"].lower()
            ):
                continue
            # Skip rows with no numeric values (purely informational)
            if row["min"] is None and row["max"] is None:
                continue
            if "Hardness" in prop:
                key = hardness_key(row)
            elif prop in PROP_MAP:
                key = PROP_MAP[prop]
            elif "Charpy" in prop:
                continue
            else:
                continue
            if key is None:
                continue
            expected.setdefault(key, []).append(row)

        for yaml_key, val in yaml_mech.items():
            if yaml_key not in expected:
                issues.append(f"  [EXTRA-MECH] {yaml_key}: not in lean spec mechanical table")
                continue
            # Check values match at least one matching lean row
            ymin = val.get("min") if isinstance(val, dict) else None
            ymax = val.get("max") if isinstance(val, dict) else None
            matched = False
            lean_vals = []
            for row in expected[yaml_key]:
                lmin, lmax = row["min"], row["max"]
                lean_vals.append(f"{row['property']}: min={lmin} max={lmax}")
                if approx_eq(ymin, lmin) and approx_eq(ymax, lmax):
                    matched = True
                    break
            if not matched:
                issues.append(f"  [MECH-MISMATCH] {yaml_key}: yaml(min={ymin}, max={ymax}) vs lean={lean_vals}")
        for yaml_key in expected:
            if yaml_key not in yaml_mech:
                rows = expected[yaml_key]
                issues.append(f"  [MISSING-MECH] {yaml_key}: lean has {[(r['min'],r['max']) for r in rows]}")

    return issues


def main():
    total = 0
    clean = 0
    any_issues = {}
    for yaml_path in sorted(SPECS_DIR.glob("*.yaml")):
        total += 1
        issues = audit_spec(yaml_path)
        if issues:
            any_issues[yaml_path.name] = issues
        else:
            clean += 1

    print(f"\n=== AUDIT RESULTS ===")
    print(f"Total specs: {total}")
    print(f"Clean: {clean}")
    print(f"With issues: {len(any_issues)}\n")

    for name, issues in any_issues.items():
        print(f"--- {name} ---")
        for i in issues:
            print(i)
        print()


if __name__ == "__main__":
    main()
