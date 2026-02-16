# Fix Recommendations — February 13, 2026

> Based on the MTR scan investigation of 12 files. See [mtr-scan-investigation-2026-02-13.md](./mtr-scan-investigation-2026-02-13.md) for the full findings.

---

## 1. Claude Extraction Prompt Improvements (`claude_parser.py`)

Highest ROI — most extraction errors trace back to the prompt not being specific enough.

### A. Element Normalization Instructions
- Tell Claude: "Cb" = "Nb" (Columbium is the old American name for Niobium). Always map to `Nb` in output.
- Tell Claude: never fabricate element values. If a cell is blank/empty, output `null` — do not use an adjacent cell's value.
- List canonical element names expected in the output schema.
- **Fixes**: Files 7, 8, 9 (Cb→Ta misattribution, Nb→V confusion, V fabricated from blank)

### B. Pre-Heat vs Post-Heat Column Selection
- Add instruction: "If the document has multiple mechanical test columns (e.g., Before Heat Treat / After Heat Treat), always use the **final condition** (After Heat Treat, As Shipped, Final) values. Never average columns."
- **Fixes**: Files 7, 8 (mechanicals averaged across pre/post heat treat columns)

### C. Temperature Unit Reporting
- Have Claude return `temper_temperature_unit: "C"` or `"F"` alongside the value. Currently returns a bare number with no unit context.
- Same for Charpy test temperature — return the value AND the unit.
- **Fixes**: Files 5, 6, 9 (temper °C stored as raw number, compared against °F spec limits)

### D. Heat Treatment Block Parsing
- Add instruction: "Heat treatment may be described as a multi-step sequence (e.g., '970°C 1HR + 225°C 2HR + 715°C 2HR'). Extract the **tempering** step specifically. Look for keywords: temper, tempering, anlassen, revenu."
- **Fixes**: File 9 (temper 715°C marked "not stated" despite being clearly present)

### E. Multi-Document Awareness
- Add instruction: "This PDF may contain multiple documents from different companies (packing slips, distributor certs, mill certs). Always prefer the **original mill test report** as the authoritative source for chemistry and mechanical properties. If different pages show different chemistry, use the mill's values."
- **Fixes**: File 4 (chemistry garbled from mixing two different certs)

### F. Negative Temperature Handling
- Add instruction: "Charpy impact test temperatures may be negative (e.g., -40°C, -20°F). Preserve the negative sign. Report the exact value and unit as printed."
- **Fixes**: File 9 (Charpy temp -40°C extracted as +10°C)

### G. Less-Than Qualifiers
- Return a `qualifiers` dict alongside chemistry, e.g., `{"Ta": "<"}` when the document says `<0.01`.
- Store the numeric value but flag the qualifier separately.
- **Fixes**: Files 7, 8, 10 (Ta <0.01 stored as 0.01, losing the "<" meaning)

---

## 2. Validator / Converter Code Fixes

### A. Temper Temperature C-to-F Conversion (`validator.py` + `converters.py`)
- When Claude reports `temper_temperature_unit == "C"`, auto-convert to °F before comparing against spec limits.
- Formula: `°F = °C × 9/5 + 32`
- Example: 720°C → 1328°F (passes ≥1200°F spec). Without conversion, 720 vs 1200 = false FAIL.
- **Effort**: Low — one conversion call in the temper validation path.
- **Fixes**: Files 5, 6, 9

### B. Element Name Normalization (`extractor.py` normalize step)
- Add a canonical mapping dict:
  ```python
  ELEMENT_ALIASES = {
      "Cb": "Nb", "Columbium": "Nb", "Niobium": "Nb",
      "cb": "Nb", "nb": "Nb",
  }
  ```
- Run on all extracted chemistry keys before validation.
- **Effort**: Low — small mapping + loop in normalization.
- **Fixes**: Files 7, 8 (Cb not recognized as Nb)

### C. S/Sn Sanity Check (`sanity.py`)
- If S > 0.05% for a steel, flag as suspicious (normal steels have S < 0.05%).
- If Sn > S for a steel, flag as possible swap.
- Cross-reference: if extracted S equals a known Sn-range value (or vice versa), emit a warning.
- **Effort**: Low — add to existing sanity check framework.
- **Fixes**: File 6 (S and Sn values swapped)

---

## 3. Pipeline Architecture Improvements

### A. Error Audit Trail (`history.py` + `pipeline.py`)
- When a file fails to produce a validation (exception, null result, unparseable JSON), write a `status: "ERROR"` record to history with the error message and file path.
- Currently: failed files are marked as processed in the watcher's in-memory set but leave no trace in history.
- Every file that enters the pipeline should get a history entry regardless of outcome.
- **Effort**: Low — add error-case write in pipeline's exception handler.
- **Fixes**: Files 11, 12 (and any future silent failures)

### B. Multi-Page Document Handling (`pipeline.py` or `claude_parser.py`)
Three options in order of complexity:

1. **Simple (prompt-only)**: Send all pages to Claude with stronger guidance about preferring mill certs over distributor certs. Rely on Claude's judgment.
2. **Medium (page classification)**: Pre-classify pages (detect which are mill certs vs packing slips vs BOLs by keyword heuristics) and only send relevant pages to the extraction prompt.
3. **Robust (page-by-page)**: Extract data page-by-page, then consolidate — merge chemistry from the mill cert page with mechanicals from the correct testing page.

- **Effort**: Low / Medium / High respectively.
- **Fixes**: File 4 (chemistry from Benteler mixed with missing mechanicals from Tejas on page 6)

### C. Spec Auto-Detection Guard (`matcher.py`)
- 8 of 10 first-attempt validations defaulted to ES-M2201C (PEEK plastic spec) for metal MTRs. The matcher is falling through to a bad default.
- Add a "no confident match" threshold — if no spec scores above 0.5 confidence, return `None` and prompt the user instead of guessing.
- Add material-type gating: if extracted chemistry has Cr > 5% or Fe > 50%, exclude polymer specs from candidates. If chemistry has Cu > 50%, exclude steel specs.
- **Effort**: Medium — requires refining the matching logic and adding confidence thresholds.
- **Fixes**: The 8/10 wrong-spec-first-attempt pattern

---

## 4. Longer-Term Features (P3)

### A. Assembly MTR Splitting
- **Detection**: Page count > 15, multiple heat numbers in OCR text, cover page listing multiple line items.
- **Splitting**: Identify page boundaries between different MTRs by heat number / material grade changes.
- **Processing**: Process each sub-document independently through the full pipeline.
- **Linking**: Store results under a parent assembly record (new field in history: `assembly_id` or `parent_po`).
- **Effort**: Very High — fundamental architecture change.
- **Fixes**: File 11 (30-page assembly MTR with 6 heats, 9 components)

### B. Polymer MTR Support
- **New extraction prompt**: Polymer-specific property names (melt viscosity, flexural modulus, HDT, Izod impact, mould shrinkage, etc.)
- **New spec schema**: Fields for polymer tests alongside existing metal tests.
- **Material-type routing**: Detect polymer vs metal early (by grade name, spec reference, or property types) and route to the correct extraction path.
- **Effort**: High — new prompt, schema additions, routing logic.
- **Fixes**: File 2 (PEEK 450G with 25 properties missed)

### C. Brass / Non-Ferrous Spec Support
- Create spec YAML files for common non-ferrous materials (C36000 brass, aluminum alloys, etc.).
- Extend matcher to handle non-ferrous UNS prefixes (C-series for copper alloys, A-series for aluminum).
- **Effort**: Medium — primarily spec authoring + matcher extension.
- **Fixes**: File 12 (C36000 brass with no matching spec)

---

## Suggested Implementation Order

| Phase | Items | Effort | Files Fixed |
|-------|-------|--------|-------------|
| **Phase 1** | Prompt improvements (1A-1F) | 1-2 hours | 5, 6, 7, 8, 9, 4 |
| **Phase 2** | C-to-F conversion (2A) + Element normalization (2B) | 1 hour | 5, 6, 7, 8, 9 |
| **Phase 3** | Error audit trail (3A) + S/Sn sanity (2C) | 1 hour | 6, 11, 12 |
| **Phase 4** | Spec auto-detection guard (3C) | 2 hours | All first-attempt failures |
| **Phase 5** | Multi-page doc handling (3B) | 4-8 hours | 4 |
| **Phase 6** | Assembly MTR (4A) + Polymer (4B) | Days | 2, 11 |

Phases 1-3 would resolve the majority of extraction errors with minimal code changes. Phase 4 prevents the wrong-spec-default problem. Phases 5-6 are larger architectural efforts.
