# Critical Review of MTR Scan Investigation — February 13, 2026

> Self-review of the initial investigation findings. PDFs were re-examined directly (rendered via PyMuPDF), validation history re-read line-by-line, and source code (claude_parser.py, validator.py, extractor.py) analyzed for root causes.

---

## Errors and Overstatements in the Original Investigation

### 1. WRONG: "Heat JT707" for SK908 files (Files 7, 8)

The original investigation implied the actual heat was "JT707" (pulled from the assembly MTR investigation, File 11). This was **wrong** — JT707 is a different heat from a completely different document (the PO1628 assembly MTR).

**Correction**: The Gibbs Wire cert for Files 7/8 clearly labels "Heat Number: SK908" on page 2. **SK908 IS the correct heat number.** The system extracted it correctly. The confusion arose because the assembly MTR (File 11) also contains Gibbs Wire X-750 certs, but for a different heat (JT707).

### 2. WRONG: "8/10 first validations defaulted to ES-M2201C"

Looking at the actual validation records:
- Record 1 (heat 4000026033) → ES-M0001G (CORRECT on first attempt)
- Record 3 (heat 79017611) → ES-M0001G (CORRECT on first attempt)
- Record 2 (PEEK V105367) → ES-M2201C (correct — it IS PEEK)
- Records 4-10 (7 files) → ES-M2201C (wrong)

**Correction**: It was **7/10 first attempts** (or 6/8 non-PEEK heats) that defaulted to the wrong spec. Two 4140/42 heats were correctly auto-detected. The matcher works for 4140/42 (grade name matching) but fails for 9Cr, Inconel, L-80, and 420.

### 3. OVERSTATEMENT: "C-to-F temperature conversion bug"

The validator code (`_validate_temper`, line 401-422) isn't buggy — it simply doesn't have the temperature unit. The extraction prompt (`claude_parser.py` line 61) defines `"temper_temperature": null` with **no companion unit field**. Claude returns the raw number, the normalizer strips any unit suffix (`extractor.py` line 195), and the validator compares bare numbers.

**Correction**: This is a **missing field in the extraction schema** issue, not a conversion bug. The fix requires:
1. Add `temper_temperature_unit` to the extraction prompt schema
2. Preserve the unit through normalization (currently stripped at line 195)
3. Add conversion logic in `_validate_temper`

### 4. WRONG: "B4535 — Ta <0.01 stored as 0.01"

I re-read the B4535 cert (Central Wire). The document says **Ta: <0.002**, not <0.01. The system stored Ta=0.002.

**Correction**: The qualifier loss is real but the values are different from what was reported. Actual: `<0.002` → stored as `0.002`. The <0.01 claim was confused with the SK908 cert (where Ta=0.0100 is a different issue entirely — in SK908, Ta's value was overwritten by Cb's value).

### 5. OVERSTATEMENT: S/Sn swap severity (File 6, A0959X)

The swap is real (S should be 0.0020, Sn should be 0.005), but looking at the ES-M0004A validation (record 14): S has spec_max=0.01, and the extracted value 0.005 passes. The true value 0.0020 would also pass. Sn is not tracked in the spec.

**Correction**: The S/Sn swap is a data integrity issue but **does not affect the validation outcome** for this particular spec. Severity should be downgraded from MEDIUM to LOW for this specific case (though it could matter for specs with tighter S limits).

### 6. MISSED: The extraction prompt INSTRUCTS Claude to average

The original investigation blamed Claude for "averaging pre-heat and post-heat columns." But `claude_parser.py` line 28 explicitly says:

```
- For multiple specimens/tests, use averages for mechanical properties.
```

Claude is **correctly following the instruction**. The bug is in the prompt, not in Claude's behavior. The instruction is too broad — it should average multiple specimens from the same test condition but NOT average different test conditions (pre-heat vs post-heat).

### 7. MISSED: B4535 uses "After Heat Treat Capabilities" not actual test results

Re-reading the B4535 cert directly, the document has:
- **"As Shipped" section**: Tensile = 192 KSI (actual tested value)
- **"After Heat Treat Capabilities" section**: Tensile = 236, Yield = 214, EL = 15%, RA = 25%, HRC = 43

The system extracted the "After Heat Treat" values (236, 214, etc.), which are **capabilities** (what the material can achieve after customer heat treatment), not the current certified condition. The actual as-shipped tensile is only 192 KSI.

For spring wire, the post-heat-treat properties are arguably what matters for validation against ES-M0009B (the spec expects heat-treated properties). But the distinction between "capabilities" and "certified test results" is important for traceability.

### 8. MISSED: SK908 RA inconsistency between Files 7 and 8

Both files are the same document (same heat SK908, same cert). Yet:
- Record 7 (1874): RA = 34.0 (from tensile test section)
- Record 8 (1875): RA = 20.0 (from wrap test line: "REDUCTION OF AREA c/k: 20")

The pipeline extracted RA from different locations on two runs of the same document. This is a **non-deterministic extraction** issue — Claude picked different values on different runs.

### 9. MISSED: 472110 Charpy values are specimen-set averages, not individuals

The system stored `values_ft_lb: [44.8, 45.2]` for heat 472110. But 44.8 and 45.2 are the **averages of two specimen sets** (specimen 78492 avg=44.8, specimen 78493 avg=45.2), not individual impact values. The actual individual values would be 6 numbers (49.4, 46.5, 38.4 for set 1; 50.9, 45.7, 39.1 for set 2).

The Charpy validation (record 17) status was INCOMPLETE anyway ("Could not parse Charpy value: None"), so the validator never actually used these values.

### 10. MISSED: Approval workflow allows wrong-spec approvals

Record 15 shows SK908-1874 was **approved by Hunter against ES-M2201C (PEEK plastic spec)** with override reason "It picked up the comma as a decimal." A nickel superalloy was signed off against a PEEK polymer spec. The system has no guardrail preventing metal-vs-polymer spec mismatches.

Record 11 shows heat 79017611 (4140/42 steel) was re-validated against ES-M2201C and approved with tensile override "in tolerance" — again, metal approved against PEEK spec.

---

## Confirmed Findings (verified by re-reading actual PDFs)

### SK908-1874/1875 (Files 7, 8) — CONFIRMED with nuance

Verified by rendering the actual Gibbs Wire cert:

**Element mapping shift — CONFIRMED:**
- Document: Cb = 0.89__ (in Cb column), Ta = 0.0100 (in Ta column), V = blank
- System: Ta = 0.89, V = 0.01, no Cb/Nb
- The pipeline read Cb's value as Ta, Ta's value as V, and ignored the blank V

**Mechanical averaging — CONFIRMED:**
- TS: (212,000 + 260,000) / 2 = 236,000 → 236 ksi ✓
- HRC: (44 + 51) / 2 = 47.5 ✓
- YS: System = 192. Consistent with (184,000 + 200,000) / 2 = 192,000. The pre-heat yield reads as either 184 or 194 (scan quality ambiguous), but 192 only works with 184.
- Root cause: Prompt says "For multiple specimens/tests, use averages" — Claude averaged across test conditions

**B4535 correctly maps Nb=0.89** from a Central Wire cert that labels it "Nb". Gibbs Wire uses "Cb" (old notation) which the pipeline doesn't recognize.

### 472110 (File 9) — CONFIRMED

Verified by rendering the DEW cert:

**Chemistry Nb/V confusion — CONFIRMED:** Page 2 column headers clearly show Ti and Nb as the last two chemistry columns. No V column exists. The system extracted V=0.028 which is actually the Nb value.

**Charpy temperature — CONFIRMED:** Page 3 shows "-40" in the impact test temperature field. System stored +10°C — a 50-degree error plus wrong sign.

**Temper temperature — CONFIRMED:** Page 1 heat treatment block: "970°C 1HR Polymer + 225°C 2HR + 715°C 2HR". The 715°C is clearly the tempering step. System reported null.

### A0959X (File 6) — CONFIRMED with severity adjustment

Verified by rendering the Tata Steel cert page 3:

**S/Sn swap — CONFIRMED** but validation-neutral. Both values pass spec limits regardless of which is which.

**Temper = 680°C — CONFIRMED.** Clearly printed: "Temper at 680°C for 01:30; Air Cooled."

### Temper temperature unit issue (Files 5, 6, 9) — CONFIRMED as schema gap

The extraction schema has no `temper_temperature_unit` field. The normalizer (`extractor.py` line 192-199) strips unit suffixes. The validator (`validator.py` line 401-422) compares raw numbers against spec limits defined in °F. This is confirmed by reading all three code files.

---

## Revised Systemic Issues (corrected priority)

| # | Issue | Root Cause | Files | Severity |
|---|-------|-----------|-------|----------|
| 1 | **Prompt instructs averaging across test conditions** | `claude_parser.py:28` says "use averages for mechanical properties" — too broad | 7, 8 | **P1 - CRITICAL** |
| 2 | **No temper_temperature_unit in extraction schema** | Prompt has no unit field; normalizer strips units; validator assumes °F | 5, 6, 9 | **P1 - HIGH** |
| 3 | **Cb element name not normalized to Nb** | Pipeline doesn't map old American "Cb" → modern "Nb" | 7, 8 | **P1 - HIGH** |
| 4 | **Element grid parsing shifts values** | Claude reads adjacent cells when a cell is blank, shifting the grid | 7, 8, 9 | **P1 - HIGH** |
| 5 | **Multi-document PDF confusion** | No guidance on which document is authoritative when multiple certs bundled | 4 | **P2 - MEDIUM** |
| 6 | **Charpy temperature sign/value error** | Bilingual OCR text confuses negative temperatures | 9 | **P2 - MEDIUM** |
| 7 | **Heat treatment block not parsed** | Multi-step treatment descriptions not recognized | 9 | **P2 - MEDIUM** |
| 8 | **Non-deterministic extraction (RA source)** | Same document produces different values on different runs | 7, 8 | **P2 - MEDIUM** |
| 9 | **Wrong-spec approval without guardrails** | Override workflow allows metal approval against polymer spec | 7, 11 | **P2 - MEDIUM** |
| 10 | **S/Sn swap** | OCR/Claude confusion between Sulfur and Tin | 6 | **P3 - LOW** |
| 11 | **Less-than qualifier lost** | `<0.002` stored as `0.002` | 10 | **P3 - LOW** |
| 12 | **Spec auto-detect fails for non-4140 grades** | Matcher only works for 4140/42 UNS; 9Cr/Inconel/L-80/420 fall through | 6/8 heats | **P2 - MEDIUM** |
| 13 | **Polymer/assembly/brass MTR support** | Architecture gaps | 2, 11, 12 | **P3 - FEATURE** |

---

## Key Takeaway

The single most impactful root cause is the **extraction prompt instruction** (line 28):
```
For multiple specimens/tests, use averages for mechanical properties.
```
This instruction is correct for multiple specimens from the same test, but causes Claude to average across fundamentally different conditions (pre/post heat treat). Combined with the missing Cb→Nb normalization and the missing temper unit field, the prompt itself is the source of most extraction errors. **Fixing the prompt is the highest-ROI change.**
