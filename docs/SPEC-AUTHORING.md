# DDIC Material Specification Authoring Guide

How to convert Downhole & Design International Corp material specification PDFs into YAML spec files for the Material Validator system.

---

## Quick Reference

| What | Where |
|------|-------|
| Spec files go in | `specs/` (project root) |
| File format | YAML (`.yaml`) |
| Naming pattern | `ES-M####L.yaml` |
| Loaded automatically | Yes, on app startup |
| Hot-reload | Settings > reload, or `SpecLoader.reload()` |

---

## 1. Spec ID Convention

Every spec follows the pattern **`ES-M####L`**:

```
ES  -  M  ####  L
|      |  |     |
|      |  |     +-- Variant letter (see table below)
|      |  +-------- 4-digit material number (0001-9999)
|      +----------- "M" for Material
+------------------ Company prefix (Engineering Specification)
```

### Material Number Ranges

| Range | Material Family |
|-------|----------------|
| 0001-0099 | Low-alloy steels (4140, 4142, 4340, etc.) |
| 0100-0199 | Carbon steels (1018, 1045, etc.) |
| 0200-0299 | Tool steels (H13, D2, etc.) |
| 0300-0399 | Stainless steels (303, 304, 316, 410, 420, etc.) |
| 0400-0499 | Nickel alloys (Inconel, Monel, Hastelloy) |
| 0500-0599 | Copper alloys (Beryllium copper, brass, bronze) |
| 0600-0699 | Titanium alloys |
| 0700-0799 | Elastomers / non-metallics |

### Variant Letters

| Letter | Meaning | Example |
|--------|---------|---------|
| A | Default / baseline variant | ES-M0003A (303 SS, standard) |
| B-D | Incremental variants | ES-M0001C (4140, standard strength) |
| E | Engineered / special requirements | ES-M0003E (420 SS, Charpy required) |
| G | High-strength variant | ES-M0001G (4140, 110 ksi MYS) |
| H-Z | Additional variants as needed | Reserved for future use |

**Same material, different requirements = same number, different letter.**
Example: 4140 at 80 ksi yield = ES-M0001C, 4140 at 110 ksi yield = ES-M0001G.

---

## 2. YAML Template

Use this template for every new spec. Copy it, fill in the values from the DDIC specification PDF.

```yaml
# ============================================================
# DDIC Material Specification: ES-M____
# ============================================================

id: "ES-M____"
revision: 0
date: "YYYY-MM-DD"
material: ""                    # Full material description
grades:                          # All accepted grade names
  - ""
uns: ""                          # UNS number (e.g., G41400)
condition: ""                    # Heat treatment (e.g., Quench and Tempered)

# ------------------------------------------------------------
# Chemistry (weight %)
# Include ONLY elements listed in the spec.
# Use min, max, or both. Omit what isn't specified.
# ------------------------------------------------------------
chemistry:
  C:  { min: 0.00, max: 0.00 }
  Mn: { min: 0.00, max: 0.00 }
  P:  { max: 0.000 }
  S:  { max: 0.000 }
  Si: { min: 0.00, max: 0.00 }
  Cr: { min: 0.00, max: 0.00 }
  Ni: { min: 0.00, max: 0.00 }
  Mo: { min: 0.00, max: 0.00 }

# ------------------------------------------------------------
# Mechanical Properties
# Always include unit. Use min, max, or both.
# ------------------------------------------------------------
mechanical:
  yield_strength:     { min: 0, unit: ksi }
  tensile_strength:   { min: 0, unit: ksi }
  elongation:         { min: 0, unit: '%' }
  reduction_of_area:  { min: 0, unit: '%' }
  hardness_hrc:       { max: 0 }

# ------------------------------------------------------------
# Special Requirements
# Use [] if none. See supported types below.
# ------------------------------------------------------------
special_requirements: []
```

---

## 3. Field-by-Field Instructions

### Header Fields

Read these from the title block / header section of the DDIC spec PDF.

| YAML Field | Where to Find on PDF | Rules |
|------------|---------------------|-------|
| `id` | Document number (top right or header) | Must match filename exactly |
| `revision` | Rev block or title block | Integer, or `null` if not tracked yet |
| `date` | Date in title block | `YYYY-MM-DD` format, or `null` |
| `material` | Title / first line | Full name, include variant info (e.g., "110 MYS") |
| `grades` | Grade / designation section | List ALL accepted names, including AISI prefix variants |
| `uns` | UNS or specification reference | e.g., G41400, S30300, N06625 |
| `condition` | Condition / heat treatment section | e.g., "Quench and Tempered", "Annealed" |

**Grades list tips:**
- Include every way a supplier might write the grade on an MTR
- Include with and without "AISI" prefix
- Include slash variants (e.g., "4140/42")
- Include "Type" prefix for stainless (e.g., "Type 303")
- Include common shorthand (e.g., "303 SS")

Example for 4140:
```yaml
grades:
  - "4140"
  - "4142"
  - "AISI 4140"
  - "AISI 4142"
  - "4140/42"
  - "AISI 4140/42"
```

### Chemistry Section

Read from the chemical composition table on the spec PDF.

**Rules:**
- Element symbols must be **Title Case**: `C`, `Cr`, `Mn`, `Ni`, `Mo` (not `CR` or `cr`)
- Values are **weight percentages** as decimals (0.040 = 0.040%, not 4.0%)
- Use `min` and/or `max` as the spec dictates
- **Omit** elements not listed in the spec (do not include with null)
- For max-only elements (impurity limits like P, S), only include `max`
- For min-only elements (e.g., Ni min 58% in Inconel), only include `min`

**Supported elements:**

| Symbol | Element | Symbol | Element |
|--------|---------|--------|---------|
| C | Carbon | Cu | Copper |
| Mn | Manganese | V | Vanadium |
| P | Phosphorus | Nb | Niobium |
| S | Sulfur | Ti | Titanium |
| Si | Silicon | Al | Aluminum |
| Cr | Chromium | N | Nitrogen |
| Ni | Nickel | B | Boron |
| Mo | Molybdenum | W | Tungsten |
| Co | Cobalt | | |

**Example patterns:**
```yaml
# Both min and max (range)
Cr: { min: 0.80, max: 1.10 }

# Max only (impurity limit)
P:  { max: 0.035 }

# Min only (minimum required)
Ni: { min: 58.0 }
```

### Mechanical Properties Section

Read from the mechanical requirements table on the spec PDF.

**Supported properties and their YAML keys:**

| PDF Label | YAML Key | Typical Unit |
|-----------|----------|-------------|
| Yield Strength / 0.2% Offset | `yield_strength` | ksi |
| Tensile Strength / UTS | `tensile_strength` | ksi |
| Elongation (2" or 4D) | `elongation` | % |
| Reduction of Area | `reduction_of_area` | % |
| Hardness (Rockwell C) | `hardness_hrc` | *(none)* |
| Hardness (Brinell) | `hardness_hbw` | *(none)* |

**Rules:**
- Always include `unit` for strength properties (`ksi` or `MPa`)
- Use `'%'` (quoted) for percentage units
- Hardness does not need a unit field
- If spec gives a range (e.g., YS 80-95 ksi), use both `min` and `max`
- If spec gives only a minimum, use only `min`
- If spec gives only a maximum, use only `max`
- **Do not convert units** - enter values as printed on the spec; the validator handles conversions

**Example patterns:**
```yaml
# Minimum only
yield_strength:   { min: 110, unit: ksi }

# Range (min and max)
yield_strength:   { min: 80, max: 95, unit: ksi }

# Maximum only (hardness cap)
hardness_hrc:     { max: 36 }

# Both hardness scales (if spec lists both)
hardness_hrc:     { max: 26 }
hardness_hbw:     { max: 255 }
```

### Special Requirements Section

Read from supplementary / special requirements sections of the spec PDF.

**Use an empty list `[]` if the spec has no special requirements.**

Three types are currently supported:

#### NACE Compliance
For specs requiring NACE MR0175 / ISO 15156 compliance:
```yaml
special_requirements:
  - type: nace_compliance
    required: true
    note: "NACE MR0175 / ISO 15156 compliant"
```

#### Temper Temperature
For specs requiring a minimum tempering temperature:
```yaml
special_requirements:
  - type: temper_temperature
    min: 1025
    unit: "°F"
    note: "Minimum tempering temperature"
```

#### Charpy Impact
For specs requiring impact toughness testing:
```yaml
special_requirements:
  - type: charpy_impact
    min_avg: 15
    unit: "ft-lbs"
    temperature: 32
    temp_unit: "°F"
    note: "Average of 3 specimens at 32°F"
```

#### Multiple Special Requirements
A spec can have any combination:
```yaml
special_requirements:
  - type: nace_compliance
    required: true
    note: "NACE MR0175"
  - type: temper_temperature
    min: 1025
    unit: "°F"
  - type: charpy_impact
    min_avg: 15
    unit: "ft-lbs"
    temperature: -20
    temp_unit: "°F"
    note: "Sub-zero impact test"
```

---

## 4. Batch Processing Workflow

Follow this process to convert a stack of DDIC spec PDFs into the system.

### Step 1: Inventory

Create a tracking spreadsheet or checklist with columns:

| Spec ID | Material | Status | Notes |
|---------|----------|--------|-------|
| ES-M0001C | 4140 Std | Done | |
| ES-M0001G | 4140 110 MYS | Done | |
| ES-M0005A | 4340 | To Do | Needs Charpy req |
| ... | ... | ... | ... |

### Step 2: Author YAML files

For each spec PDF:

1. Open the DDIC spec PDF
2. Copy the template from Section 2 above
3. Save as `specs/ES-M####L.yaml` (filename must match the `id` field)
4. Fill in header fields from the title block
5. Transcribe chemistry table - enter each element's min/max range
6. Transcribe mechanical table - enter each property with its unit
7. Transcribe special requirements (NACE, temper temp, Charpy, or `[]`)
8. Review the file for typos (decimal places matter)

### Step 3: Validate YAML syntax

Run the import test to confirm the file loads without errors:

```bash
python -m pytest tests/test_02_spec_loader.py -v
```

This will catch:
- YAML syntax errors (bad indentation, missing colons)
- Missing `id` field
- Duplicate spec IDs

### Step 4: Verify with a known MTR

If you have a test MTR JSON for this material, validate against the new spec:

```bash
# Validate a specific MTR against the new spec
python validate.py --json tests/mtrs/your-test-mtr.json --spec ES-M0005A

# Or use auto-detect to confirm matching works
python validate.py --json tests/mtrs/your-test-mtr.json --auto
```

### Step 5: Record completion

Update your tracking spreadsheet. Mark the spec as "Done" with the date.

---

## 5. Recording & Change Control

### New Spec Checklist

Before marking a spec as complete, verify:

- [ ] Filename matches `id` field exactly (e.g., `ES-M0005A.yaml` has `id: "ES-M0005A"`)
- [ ] `revision` and `date` are set (use `0` and today's date for new specs)
- [ ] `grades` list includes all supplier name variants
- [ ] `uns` is correct (verify against a reference like MatWeb or the spec itself)
- [ ] All chemistry elements use Title Case (`Cr` not `CR`)
- [ ] Chemistry values are weight percentages (0.040 not 4.0)
- [ ] Mechanical properties have `unit` fields where required
- [ ] `special_requirements` is present (use `[]` if none)
- [ ] `python -m pytest tests/test_02_spec_loader.py -v` passes
- [ ] At least one test MTR validates correctly against the spec

### Revising an Existing Spec

When a DDIC spec is revised:

1. Open the existing YAML file
2. Increment the `revision` number
3. Update the `date` to the revision date
4. Modify only the changed requirements
5. Run `python -m pytest tests/ -v` to confirm nothing breaks
6. Git commit with message: `Update ES-M####L rev N: <what changed>`

### Git Commit Convention

```
Add ES-M0005A: 4340 Alloy Steel spec
Add ES-M0006A, ES-M0006B: Inconel 625/718 specs
Update ES-M0001G rev 1: raise min YS to 115 ksi
```

---

## 6. Worked Examples

### Example A: Simple Alloy Steel (no special requirements)

**From PDF:** 4340 steel, Q&T, YS min 125 ksi, full chemistry table.

```yaml
id: "ES-M0005A"
revision: 0
date: "2026-02-09"
material: "4340 Alloy Steel"
grades:
  - "4340"
  - "AISI 4340"
uns: "G43400"
condition: "Quench and Tempered"

chemistry:
  C:  { min: 0.38, max: 0.43 }
  Mn: { min: 0.60, max: 0.80 }
  P:  { max: 0.035 }
  S:  { max: 0.040 }
  Si: { min: 0.15, max: 0.35 }
  Cr: { min: 0.70, max: 0.90 }
  Ni: { min: 1.65, max: 2.00 }
  Mo: { min: 0.20, max: 0.30 }

mechanical:
  yield_strength:     { min: 125, unit: ksi }
  tensile_strength:   { min: 145, unit: ksi }
  elongation:         { min: 10, unit: '%' }
  reduction_of_area:  { min: 35, unit: '%' }
  hardness_hrc:       { min: 28, max: 36 }

special_requirements: []
```

### Example B: Stainless with Charpy Requirement

**From PDF:** 410 SS, Q&T, YS 80-100 ksi, Charpy at -20F.

```yaml
id: "ES-M0003F"
revision: 0
date: "2026-02-09"
material: "410 Stainless Steel - Subsea"
grades:
  - "410"
  - "AISI 410"
  - "410 SS"
  - "Type 410"
  - "UNS S41000"
uns: "S41000"
condition: "Quench and Tempered"

chemistry:
  C:  { min: 0.08, max: 0.15 }
  Mn: { max: 1.00 }
  P:  { max: 0.040 }
  S:  { max: 0.030 }
  Si: { max: 1.00 }
  Cr: { min: 11.50, max: 13.50 }

mechanical:
  yield_strength:     { min: 80, max: 100, unit: ksi }
  tensile_strength:   { min: 100, unit: ksi }
  elongation:         { min: 15, unit: '%' }
  reduction_of_area:  { min: 45, unit: '%' }
  hardness_hrc:       { max: 28 }

special_requirements:
  - type: charpy_impact
    min_avg: 20
    unit: "ft-lbs"
    temperature: -20
    temp_unit: "°F"
    note: "Average of 3 specimens at -20°F"
  - type: nace_compliance
    required: true
    note: "NACE MR0175"
```

### Example C: Nickel Alloy (min-only chemistry, high Ni)

**From PDF:** Inconel 625, solution annealed.

```yaml
id: "ES-M0004A"
revision: 0
date: "2026-02-09"
material: "Inconel 625"
grades:
  - "625"
  - "Inconel 625"
  - "Alloy 625"
  - "N06625"
uns: "N06625"
condition: "Solution Annealed"

chemistry:
  C:  { max: 0.10 }
  Mn: { max: 0.50 }
  Si: { max: 0.50 }
  P:  { max: 0.015 }
  S:  { max: 0.015 }
  Cr: { min: 20.0, max: 23.0 }
  Ni: { min: 58.0 }
  Mo: { min: 8.0, max: 10.0 }
  Nb: { min: 3.15, max: 4.15 }
  Ti: { max: 0.40 }
  Al: { max: 0.40 }
  Co: { max: 1.0 }

mechanical:
  yield_strength:     { min: 60, unit: ksi }
  tensile_strength:   { min: 120, unit: ksi }
  elongation:         { min: 30, unit: '%' }

special_requirements: []
```

---

## 7. Common Mistakes

| Mistake | What Happens | Fix |
|---------|-------------|-----|
| `CR` instead of `Cr` | Element not matched during validation | Use Title Case for all elements |
| `0.40` vs `4.0` for Sulfur max | All MTRs fail S check | Chemistry values are weight % (0.040 = 0.040%) |
| Missing `unit: ksi` on yield | Validator may miscompare units | Always include `unit` on strength properties |
| Filename doesn't match `id` | Spec loads but ID lookup fails | Filename and `id` field must be identical |
| `special_requirements:` (no value) | YAML parse error | Use `special_requirements: []` for empty list |
| Forgot a grade alias | Auto-detection misses this supplier's MTR format | Add all known supplier name variants to `grades` |
| Wrong UNS number | Auto-detection matches wrong spec | Double-check UNS against ASTM/SAE reference |
| `min: 80, max: 95` on same line | YAML syntax error if not in braces | Use `{ min: 80, max: 95, unit: ksi }` |

---

## 8. CLI Verification Commands

After adding specs, run these to confirm everything works:

```bash
# 1. Check all specs load (catches YAML syntax errors)
python -m pytest tests/test_02_spec_loader.py -v

# 2. List all loaded specs (confirm new ones appear)
python validate.py --list-specs

# 3. Show a specific spec's details
python validate.py --show-spec ES-M0005A

# 4. Validate a test MTR against the new spec
python validate.py --json tests/mtrs/heat-D2213660-4140.json --spec ES-M0001G

# 5. Test auto-detection picks the right spec
python validate.py --json tests/mtrs/heat-D2213660-4140.json --auto

# 6. Run full test suite (confirms nothing is broken)
python -m pytest tests/ -v
```

---

## 9. Auto-Detection: How Specs Get Matched to MTRs

When a user drops an MTR PDF and the system auto-detects the spec, the matching works in this priority order:

1. **UNS number match** (90% confidence) - Most reliable. If the MTR contains a UNS number and it matches a spec, that spec is selected.

2. **Grade name match** (80% confidence for exact, 60% for partial) - The MTR's material grade is compared against every entry in each spec's `grades` list.

3. **Yield strength tie-breaker** - When multiple specs match the same material (e.g., both ES-M0001C and ES-M0001G match "4140"), the MTR's yield strength value determines which spec fits best:
   - MTR with YS of 85 ksi matches ES-M0001C (min 80 ksi)
   - MTR with YS of 115 ksi matches ES-M0001G (min 110 ksi)

**This is why the `grades` list and `uns` field are critical** - they directly control whether an MTR gets matched to your spec.
