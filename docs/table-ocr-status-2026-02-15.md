# Table-Aware OCR Implementation Status — 2026-02-15

## What Was Done

### Files Modified

1. **`src/lib/paddle_ocr.py`** — Major rewrite of `_extract_lines_from_result()`
   - Added helper functions: `_normalize_element()`, `_is_value_text()`, `_group_into_rows()`, `_x_center()`
   - Added `_detect_and_format_tables()` — detects chemistry tables from OCR bounding boxes
     - **Pass 1**: Finds header rows (≥4 element symbols, few values — distinguishes header-only rows from label:value rows)
     - **Pass 2**: Maps value rows to nearest header by x-center proximity (60px threshold)
     - **Pass 3**: Detects interleaved label:value format (e.g., `C: 0.075  Si: 0.23`)
   - Added `_build_ordered_output()` — maintains document order when inserting table blocks
   - Text items now include `w` (width) for proper x-center calculation
   - Output format: `[CHEMISTRY TABLE]\nC=0.075 | Mn=0.04 | Ta=<0.002 | ...`

2. **`src/lib/claude_parser.py`** — Prompt updated
   - Removed bandaid instruction: "IMPORTANT: Look for chemistry TABLE HEADERS first..."
   - Removed instruction about OCR breaking element labels across lines
   - Added: "Chemistry data may be provided in `[CHEMISTRY TABLE]` blocks with `Element=Value` format. Use these values directly."
   - Updated qualifier instruction to reference `Element=<Value` format

3. **`src/lib/extractor.py`** — Added [CHEMISTRY TABLE] qualifier parsing
   - Added Pass 1a before existing qualifier detection: parses `[CHEMISTRY TABLE]` blocks for `Element=<Value` patterns
   - Existing raw-text qualifier detection and grid-shift heuristics remain as fallback

### Test Results

- **All 44 unit tests pass** (paddle_ocr, extractor, claude_parser)
- **215/219 full test suite pass** (4 pre-existing failures unrelated to changes)
- **Synthetic unit tests pass**: both header+value and label:value formats work correctly

### Plan Test Results (Issues 4, 8a, 9a)

| Issue | Test | Result | Details |
|-------|------|--------|---------|
| **8a** | A0959X S/Sn not swapped | **PASS** | S=0.002, Sn=0.005 correct |
| **8a** | PO1966Li3 S/Sn correct | **PASS** | S=0.012, Sn=0.007 correct |
| **9a** | B4535 Ta value | **PASS** | Ta=0.002 correct |
| **9a** | B4535 Ta qualifier | **FAIL** | Qualifier was None, expected `<` |
| **9a** | SK908-1874 Ta value | **FAIL** | Ta=0.09, expected 0.01 |
| **9a** | SK908-1874 Ta qualifier | **FAIL** | No qualifier |
| **4** | SK908-1874 V is null | **FAIL** | V=0.01, expected null |
| **4** | SK908-1874 Ta own value | **FAIL** | Ta=0.09, expected ~0.01 |
| **4** | 472110 V absent/null | **PASS** | V=None correct |
| **4** | 472110 Nb correct | **FAIL** | Nb=None, expected ~0.028 |

**Summary: 5/10 pass, 5/10 fail**

## Debugging Done — Root Cause Analysis

### B4535 Table Detection: Working but Claude Ignores It

The OCR table detection correctly outputs:
```
[CHEMISTRY TABLE]
C=0.075 | Mn=0.04 | P=0.009 | S=0.002 | Si=0.23 | Cr=15.61 | Ni=71.70 | Cu=0.02 | Al=0.55
[CHEMISTRY TABLE]
B=0.0051 | Ta=< 0.002 | Co=0.02 | Nb=0.89 | Fe=8.25 | Pb=< 0.0001
```

But Claude's extraction **does not reliably use** the [CHEMISTRY TABLE] blocks. In a re-run with debug logging, Claude returned:
- `B: 0.002` (wrong, should be 0.0051)
- `Mo: 0.89` (fabricated — no Mo on cert)
- `Ta: 0.0001` (wrong value, but qualifier `<` was correctly added by extractor)
- `Cu: 0.02`, `Al: 0.55` (from table, correct alignment, but actual cert values may differ)

**Root cause**: Claude is still doing its own interpretation of the flat text portions AND the [CHEMISTRY TABLE] blocks, sometimes mixing values between them or ignoring the structured data.

### B4535 Table Alignment Issue

From raw bounding box analysis (all items in chemistry region):
```
HEADER ROW 1 (y≈870): C(88.5) Mn(205.5) P(303.5) S(419) Si(534) Cr(647) Ni(757) Cu(870.5) Ti(992.5) Al(1091)
VALUE ROW 1 (y≈900):  0.075(104) 0.04(209.5) 0.009(320.5) 0.002(437) 0.23(544) 15.61(659.5) 71.70(770) 0.02(877) [no Ti val] 0.55(1100)
HEADER ROW 2 (y≈930): B(88) Ta(202) Co(308) Nb(426) Fe(536) Pb(647.5)
VALUE ROW 2 (y≈960):  0.0051(108.5) <0.002(221.5) 0.02(314.5) 0.89(432) 8.25(544) <0.0001(671) 0.889(770)
```

**Issues found:**
- Ti header (xctr=992.5) has NO value in value row 1 — Ti value (2.43) is absent from OCR entirely
- Value `0.889` at xctr=770 in row 2 has no matching header in row 2 (closest is Pb at 647.5 = 122px away, beyond 60px threshold)
- The `0.889` appears to be `Nb` (Cb) continuation but sits under where `Ni` header is in row 1
- Missing from OCR detection entirely: `N` (nitrogen), Ti value, one Nb value

### SK908 Table Detection: Partial — Label:Value Format Not Fully Captured

SK908 OCR uses a mixed format. The OCR text shows:
```
Si:  Sul:  0.0010
0.0800  Cr:  15.4500  Ni:  71.8000  Mo:
Co:  0.0200  Cu:  0.0100  N2:
Ti:  2.4200  Al:  Fe:  8.4900
0.6200  Be:  W:
[CHEMISTRY TABLE]
C=0.0690 | Mn=0.0100 | P=0.0060
```

Only 3 elements got table-detected (C, Mn, P). The rest are in flat label:value format but split across multiple lines, which the label:value detection (Pass 3) doesn't handle — it only looks within a single row.

### 472110 (German Cert): Chemistry Mostly Missing

Only `Cr=12.68` extracted. This is a German document where the chemistry table format is very different. The table detection may not have found enough elements in a header row.

## What's Left To Do

### Critical Fixes Needed

1. **Claude not using [CHEMISTRY TABLE] blocks reliably**
   - The prompt instruction is too weak. Claude still mixes flat text with table data.
   - Options:
     a. **Make the prompt stronger**: "When [CHEMISTRY TABLE] blocks are present, use ONLY the values from those blocks for chemistry. Do not extract chemistry from any other text."
     b. **Strip non-table chemistry text**: Remove the raw chemistry lines from OCR output when a [CHEMISTRY TABLE] block covers them, so Claude can't see conflicting data.
     c. **Bypass Claude for chemistry entirely**: Parse [CHEMISTRY TABLE] blocks directly in the normalizer/extractor instead of relying on Claude. This is the most reliable approach.

2. **SK908 multi-line label:value detection**
   - The label:value format spans multiple OCR rows (e.g., `Si:` on one line, value on next)
   - Pass 3 only checks within a single row
   - Need to handle cross-row label→value pairing (look ahead to next row for orphan values)

3. **472110 German cert chemistry table detection**
   - Need to investigate what the 472110 OCR bounding boxes look like
   - German certs may use different element names or layout

4. **B4535 orphan values (0.889 at xctr=770)**
   - Value falls outside 60px of any header in its row
   - Consider: if a value in row N has no header match in row N's header, try matching against previous header rows
   - Or increase threshold for wider tables

5. **False positive qualifier on S**
   - The bare `< 0.002` pattern from `Ta=< 0.002` also matches S=0.002
   - Fix: skip bare-pattern matching for values that appear inside [CHEMISTRY TABLE] blocks (they're already handled by Pass 1a)

### Recommended Next Steps (Priority Order)

1. **Option 1c above**: Parse [CHEMISTRY TABLE] blocks directly in extractor/normalizer — don't rely on Claude for chemistry when structured data is available. This bypasses the biggest failure mode.
2. Fix multi-line label:value detection for SK908-style certs
3. Add orphan value recovery (try previous header rows)
4. Investigate 472110 OCR output for German cert handling
5. Fix false positive qualifier matching

### Files to Reference
- Raw bounding box data analysis is in this file above
- Plan test runner: `tests/test_plan_runner.py` — run with `--issue 4`, `--issue 8a`, `--issue 9a`
- Test documents: `.MTR Validator Watch Folder Test/` (B4535-1831.pdf, SK908-13628-1874.pdf, 472110-1975.pdf)
- Full OCR output for B4535 and SK908 was dumped during debugging (see session transcript if needed)
