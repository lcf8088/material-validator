# MTR Scan Investigation — February 13, 2026

> Investigation of 12 MTR scan files from `.MTR Validator Watch Folder Test/`
> Each PDF was read page-by-page and compared against system extraction records in `history/validations.jsonl`

---

## Summary Table

| # | File | Material | Heat | Pages | Extraction Quality | Critical Issues |
|---|------|----------|------|-------|--------------------|-----------------|
| 1 | PO1966Li3 | 4140/42 | 4000026033 | 7 | Good | Minor: mid-radius hardness variations not captured |
| 2 | PO1946 | PEEK 450G | (polymer) | 4 | Failed | 25 polymer properties completely missed |
| 3 | PO1918 | 4140/4142 | 79017611 | 10 | Mostly Good | Mid-radius hardness (304 BHN) missed; only surface (299) captured |
| 4 | PO1830 | L-80 | 312734 | 6 | Critical Failure | Chemistry garbled, mechanicals null despite existing on page 6 |
| 5 | 626119 | 9Cr 1Mo | 626119 | 4 | Good | Temper 720°C stored as 720.0 — needs C-to-F conversion for spec comparison |
| 6 | PO1783Li1.2 | 9Cr (A0959X) | A0959X | 14 | Partial | S/Sn swapped, Charpy mean off by 1, temper °C vs °F |
| 7 | SK908-1874 | Inconel X-750 | JT707 | 2 | Critical Failure | Cb→Ta misattribution, V fabricated, mechanicals averaged across columns |
| 8 | SK908-1875 | Inconel X-750 | JT707 | 2 | Critical Failure | Same errors as 1874, Nb marked MISSING |
| 9 | 472110 | German 420 | 472110 | 4 | Critical Failure | Nb→V confusion, Charpy temp -40°C read as +10°C, temper missed |
| 10 | B4535 | X-750 | B4535 | 1 | Mostly Good | Ta qualifier lost, heat treat context missing |
| 11 | ASSEMBLY PO1628 | Multi (6 heats) | Multiple | 30 | Never Processed | Assembly MTR — unsupported architecture |
| 12 | P406278 | C36000 Brass | P406278 | 2 | Never Processed | No brass spec, possible watcher path mismatch |

---

## Detailed File-by-File Analysis

### File 1: `2026.02.Packing Slip.PO1966Li3.pdf` (4140/42, Heat 4000026033)

**Document**: 7-page multi-document package (Packing Slip + EMJ Certificate of Conformance + Nucor Mill Cert)

**Extraction Accuracy**:
- Heat: 4000026033 — CORRECT
- Grade: 4140/42 — CORRECT
- Supplier: NUCOR MEMPHIS — CORRECT
- All 18 chemistry elements match exactly (C=0.42, Mn=0.95, P=0.009, S=0.012, Si=0.259, Cu=0.23, Ni=0.21, Cr=1.06, Mo=0.22, V=0.023, Al=0.026, B=0.0004, Sn=0.007, Ti=0.002, Nb=0.004, Ca=0.0005, As=0.004, Sb=0.003)
- Yield=130 ksi, Tensile=148 ksi, Elongation=19%, RA=53% — ALL CORRECT
- Temper=1241°F — CORRECT
- Grain Size=5 — CORRECT

**Minor Issues**:
- Hardness: Extracted 311 HBW (one mid-radius reading). PDF has 7 readings: Surface 308/310/313, Mid-radius 311/313/316/320
- Charpy averages: 14°F avg extracted as 35.3 (CoC value), mill cert says 35.0. -20°F avg extracted as 25.7 (CoC), mill cert says 26.0. Extracted values are arithmetically more accurate.
- Missing: Pb=0.000, Bi=0.000, Te=0.000, N=57 PPM, H=1 PPM, DI=7.10, E45A cleanliness, E381 macroetch

**Verdict**: Clean extraction. No validation impact.

---

### File 2: `2026.02.Packing List.PO1946.pdf` (PEEK 450G Polymer)

**Document**: 4-page package (Packing List + Purchase Order + Victrex Certificate of Analysis)

**Extraction Accuracy**:
- System reported null for all mechanical properties
- Document has 25 test properties on pages 3-4 including: Melt Viscosity, Tensile Strength, Tensile Modulus, Flexural Strength, Flexural Modulus, Compressive Strength, Notched Izod Impact, Unnotched Charpy Impact, HDT, Mould Shrinkage, etc.

**Root Cause**: Pipeline doesn't understand polymer/plastic material properties. The extraction prompt and spec schema are designed for metals (chemistry as element %, mechanical as yield/tensile/elongation). PEEK uses completely different property names, units, and test methods.

**Spec Issue**: Validated against ES-M2201C (PEEK spec) but mechanical extraction failed completely.

**Verdict**: Fundamental architecture gap — polymer MTR support needed.

---

### File 3: `2026.02.DOCS.PO1918.pdf` (4140/4142, Heat 79017611)

**Document**: 10-page package (B&T Certificate of Compliance + EMJ Certificate of Conformance + Gerdau Mill MTR + Magellan Packing List)

**Extraction Accuracy**:
- Heat: 79017611 — CORRECT
- Grade: 4140/4142 — CORRECT
- All 11 chemistry elements match exactly
- Yield=137 ksi (0.2% offset) — CORRECT (0.6% EUL value of 138 ksi also exists but not standard)
- Tensile=151 ksi, Elongation=28%, RA=50% — ALL CORRECT
- Temper=1410°F — CORRECT
- Grain Size=5-8 — CORRECT

**Issues**:
- **Hardness**: Extracted 299 HBW (surface). **Missed mid-radius hardness of 304 BHN**. Depending on spec, mid-radius may be the controlling value.
- **Hydrogen**: 1.70 PPM present on document but not extracted
- **Charpy 14°F avg**: Gerdau MTR page 7 has erroneous `F_AVG_LONG_@_14F = 70.0` when individual values are 59,59,59 (avg=59.0). System correctly used 59.0 from the Jorgensen cert.

**Verdict**: Good extraction. Mid-radius hardness gap is the only meaningful issue.

---

### File 4: `2026.02.DOCS.PO1830.pdf` (L-80, Heat 312734)

**Document**: 6-page package (DDIC Receiving Report + Pup Joint Bill of Lading + Pup Joint CoC + Benteler Inspection Certificate + Tejas Tubular MTR)

**Extraction Accuracy — CRITICAL FAILURES**:

**Chemistry completely garbled**: System extracted C=0.29, Mn=1.21, Si=0.19, Cr=0.18, Ni=0.08, Mo=0.08 — these match NO source in the document.
- Benteler cert (page 4): C=0.160, Si=0.240, Mn=0.70, Cr=1.00
- Tejas cert (page 6): C=0.420, Mn=0.980, Ni=1.000, Cr=0.180
- Extracted values appear to be garbled averages or misreads from multiple pages

**Mechanicals null**: System reported yield=null, tensile=null. **But page 6 (Tejas Tubular) has full data**:
- Yield: 91,516 psi (91.5 ksi) and 91,748 psi (91.7 ksi)
- Tensile: 111,741 psi (111.7 ksi) and 110,553 psi (110.6 ksi)
- Elongation: 28.5% and 28.0%
- Hardness: ~20 HRC (well under 23 max)
- Charpy: 88.0 ft-lbs avg at -32°F
- Temper: 1340°F

**Root Cause**: Multi-document PDF confusion. Benteler cert has chemistry but no tensile data. Tejas cert on page 6 has both chemistry and full mechanicals. The pipeline mixed data from different pages/certs and missed the Tejas page entirely for mechanicals. Page 6 may also be rotated/landscape.

**Verdict**: Critical extraction failure. Multi-page document handling needs major improvement.

---

### File 5: `626119-3409-01-1783.pdf` (9Cr 1Mo, Heat 626119)

**Document**: 4-page package (Gerdau Mill Test Certificate + Bill of Lading)

**Extraction Accuracy**:
- Heat: 626119 — CORRECT
- All 12 chemistry elements match exactly (C=0.103, Mn=0.425, Si=0.642, P=0.013, S=0.004, Cr=8.650, Ni=0.123, Mo=0.992, Cu=0.151, Ti=0.0010, B=0.0001, Nb=0.0010)
- Yield=83 ksi, Tensile=110 ksi, Elongation=23%, RA=67%, Hardness=235 HBW — ALL CORRECT
- Charpy: 103,104,106 avg 104.33 ft-lbs at 14°F — CORRECT
- NACE: MR0175/ISO 15156 referenced — CORRECT
- Grain Size=7 — CORRECT

**Issue**:
- **Temper temperature**: 720°C stored as 720.0. Document explicitly says "Tempering 720 degrees C". The ES-M0004A spec defines temper min as 1200°F. The validator compared 720.0 against 1200°F — a unit mismatch. 720°C = 1328°F, which PASSES (>1200°F), but the system flagged it as FAIL because it compared raw numbers without converting.

**Verdict**: All extraction correct. **C-to-F conversion bug** is the only issue.

---

### File 6: `2026.02.DOCS.PO1783Li1.2.pdf` (9Cr A0959X, Heat A0959X)

**Document**: 14-page package (DDIC Receiving Report + Ship List + Tata Steel Inspection Certificate + Howco Delivery Note + AAA Cooper BOL + EMPCO CoC + Engineering Drawings + Inspection Reports + Work Order)

**Extraction Accuracy**:
- Heat: A0959X — CORRECT
- Chemistry mostly correct BUT:

**S and Sn swapped**:
- Document: S=0.0020, Sn=0.005
- System extracted: S=0.005, Sn=0.002
- The pipeline confused Sulfur with Tin

**Charpy values**:
- Document: individuals 105, 103, 105 ft-lbs, mean=104
- System: reported as "104, 105, 103 mean 105" — mean is wrong (104 not 105), individual order garbled

**Temper temperature**: 680°C explicitly on document ("Temper at 680 deg C"). Same C-to-F issue as 626119. 680°C = 1256°F.

**NACE**: Document does NOT explicitly state NACE compliance. Hardness 232 HBW suggests compliance but certificate doesn't claim it.

**Additional**: Surface hardness 223/229 HBW also reported but not captured. Grain size 6-8 (McQuaid-Ehn method).

**Verdict**: S/Sn swap is a data corruption bug. Temper C-to-F conversion needed.

---

### File 7: `SK908-13628-1874.pdf` (Inconel X-750, Heat JT707)

**Document**: 2-page Gibbs Wire & Steel Certificate of Analysis

**Extraction Accuracy — CRITICAL FAILURES**:

**Element mapping errors**:
- **Cb(=Nb)=0.89 misattributed to Ta**: Document lists "Cb" (Columbium) = 0.89. System put this under Tantalum (Ta). Cb is the old American name for Niobium (Nb).
- **V=0.01 fabricated**: Document shows V as blank. The 0.01 value is actually Ta (Tantalum). System shifted elements in the grid.
- **Ta=<0.01 lost**: The less-than qualifier was dropped

**Mechanical values completely wrong**:
- Document has TWO columns: "Before Heat Treat" and "After Heat Treat"
  - Pre-heat: TS=212,000 psi, YS=184,000 psi, EL=14-18%, HRC=44-48
  - Post-heat: TS=260,000 psi, YS=200,000 psi, EL=20%, HRC=51
- System extracted averages: TS=236,000 (avg of 212+260), YS=192,000 (avg of 184+200), HRC=47.5 (avg of 44+51)
- **The system averaged pre-heat and post-heat columns instead of picking post-heat values**

**RA error**: System extracted RA=20%, but 20% comes from the wrap test row, not the tensile test. Actual RA from tensile = 34%.

**Verdict**: Critical multi-column confusion. Pipeline cannot distinguish before/after heat treatment columns.

---

### File 8: `SK908-13628-1875.pdf` (Inconel X-750, Heat JT707)

**Document**: Same 2-page Gibbs Wire cert as File 7 (identical document, different part number)

**Same extraction errors as File 7** plus:
- When validated against ES-M0009B spec, **Nb was marked MISSING** because the system stored Cb under Ta instead of Nb
- The spec requires Nb (0.70-1.00), and the actual value Cb=0.89 would PASS, but it was never mapped correctly

**Verdict**: Same critical issues as File 7. Cb→Nb mapping fix would resolve.

---

### File 9: `472110-1975.pdf` (German 420 Modified, Heat 472110)

**Document**: 4-page Deutsche Edelstahlwerke (DEW) Inspection Certificate — bilingual German/English

**Extraction Accuracy — CRITICAL FAILURES**:

**Nb misidentified as V**:
- Document chemistry columns: C, Si, Mn, P, S, Cr, Mo, Ni, Cu, **Ti**, **Nb**
- Ti=≤0.002, **Nb=0.028**
- System extracted **V=0.028** — there is NO vanadium column on this cert
- The pipeline confused Nb with V

**Charpy temperature completely wrong**:
- Document: test temperature = **-40°C**
- System extracted: **+10°C**
- A 50-degree error in the wrong direction

**Temper temperature marked "not stated" but clearly present**:
- Page 1 heat treatment block: "970°C 1HR Polymer + 225°C 2HR oil/Air + **715°C 2HR oil/Air**"
- The tempering temperature is 715°C (= 1319°F)
- System failed to parse the heat treatment description

**Mechanical values**: Document has dual columns (MPa and ksi) for two specimens:
- Specimen 78492: YS=591 MPa / 86 ksi, TS=767 MPa / 111 ksi
- Specimen 78493: YS=593 MPa / 86 ksi, TS=771 MPa / 112 ksi
- System extracted single values (likely averaged or picked one specimen)

**Additional**: NACE MR0175/ISO 15156:2020 explicitly listed. Grain size 7-8. Extensive hardness data (HRC quadrant + HBW traverse).

**Verdict**: Multiple critical extraction errors. Element mapping, temperature parsing, and heat treatment block parsing all need fixes.

---

### File 10: `B4535-1831.pdf` (Inconel X-750, Heat B4535)

**Document**: 1-page single MTR

**Extraction Accuracy**:
- Heat, grade, chemistry mostly correct
- Mechanicals mostly correct

**Issues**:
- **Ta less-than qualifier lost**: Document says Ta <0.01, system stored as Ta=0.01 (loses the "<" meaning)
- **Heat treatment context not preserved**: Document specifies "After Heat Treat" column — system extracted values without noting this context
- Units confirmed as KSI on document

**Verdict**: Mostly good. Minor qualifier handling issue.

---

### File 11: `2026.02.ASSEMBLEYMTR.PO1628.pdf` (Assembly — 6 heats, 9 components)

**Document**: 30-page assembly MTR compilation from B&T Oilfield Products for a 1-3/16" SM Pulling Tool Assembly

**Never Processed** — no validation record exists.

**Document contains**:
- Cover page (B&T Certificate of Compliance listing 9 line items)
- 6 distinct heats across 4+ material grades:
  - Heat D1914127 — 4140/42 (Core Nut, Core, Dog Washer)
  - Heat JT707 — Inconel X-750 (Core Spring, Dog Spring)
  - Heat 5393602 — 4140 (Fishneck)
  - Heat 79018550 — 4130 (Tool Dog)
  - Heat 20785750 — 4130 (Tool Skirt)
  - Heat K31C — 303 Stainless (Shear Pin Cover)
- Individual mill certs from: Asil Celik (Turkey), Gibbs Wire, HA Industries/Republic Steel, Gerdau, Charter Steel, North American Stainless
- Heat treatment cert from Bodycote
- Engineering drawings and inspection reports from DDIC

**Root Cause**: Pipeline architecture assumes one PDF = one heat = one spec. Cannot handle:
- Document splitting (identify page boundaries between different MTRs)
- Multiple heats per document
- Multiple material grades per document
- Assembly-level traceability

**Verdict**: Fundamental architecture limitation. Requires document splitter + multi-heat processing.

---

### File 12: `P406278-1953.pdf` (C36000 Brass, Heat P406278)

**Document**: 2-page package (EMJ Certificate of Conformance + Mueller Brass Certificate of Conformance)

**Never Processed** — no validation record exists.

**Document contains**:
- Material: C36000 Free-Cutting Brass, 1/2 Hard, ASTM B16
- Chemistry: Cu=61.40%, Pb=3.10%, Fe=0.15%, Zn=remainder
- Both pages are scanned images with zero embedded text (Canon copier scan)

**Root Causes for non-processing**:
1. **Watch folder path mismatch**: config.json points to `Z:/.MTR Validator Watch Folder Test` but file is in local repo path
2. **No brass spec**: No ES-M#### spec exists for C36000 brass
3. **Pure image scan**: No text layer — relies entirely on PaddleOCR

**Verdict**: Would need brass spec YAML + correct watch folder path.

---

## Systemic Issues Identified

### 1. Temperature Unit Conversion (C-to-F)
**Affects**: Files 5, 6, 9
**Problem**: European mills report temper temperature in °C. Specs define limits in °F. System compares raw numbers (e.g., 720 vs 1200) without converting.
**Fix**: Detect °C in extracted data, convert to °F before spec comparison.

### 2. Element Mapping (Cb/Nb/Ta/V Confusion)
**Affects**: Files 7, 8, 9
**Problem**:
- Cb (Columbium) = Nb (Niobium) — old American vs modern name
- Pipeline shifts elements in grids, confusing Nb↔V↔Ta
- Cb from Gibbs Wire certs mapped to Ta instead of Nb
**Fix**: Normalize "Cb" → "Nb" in extraction. Improve grid parsing to handle blank cells.

### 3. Pre-Heat / Post-Heat Column Detection
**Affects**: Files 7, 8
**Problem**: Gibbs Wire certs have "Before Heat Treat" and "After Heat Treat" columns. Pipeline averages both instead of selecting post-heat values (which are the final certified properties).
**Fix**: Claude prompt needs instruction to prefer "After Heat Treat" / "Final" / "As Shipped" column values.

### 4. S/Sn Element Swap
**Affects**: File 6
**Problem**: Sulfur (S) and Tin (Sn) values swapped during extraction.
**Fix**: Improve element identification in Claude prompt or add validation that S is typically <0.05% and Sn is typically <0.05%.

### 5. Multi-Page Document Handling
**Affects**: File 4
**Problem**: Multi-document PDFs (different certs from different companies bundled together) confuse the pipeline. Chemistry from one cert mixed with mechanicals from another. Later pages with critical data (Tejas cert on page 6) missed entirely.
**Fix**: Improve Claude prompt to handle multi-page documents. Consider page-by-page extraction with consolidation.

### 6. Charpy Temperature Extraction
**Affects**: File 9
**Problem**: Test temperature -40°C extracted as +10°C (50-degree error in wrong direction).
**Fix**: Improve parsing of negative temperatures and bilingual (German/English) certificate formats.

### 7. Heat Treatment Block Parsing
**Affects**: File 9
**Problem**: Temper temperature embedded in a multi-step heat treatment description ("970°C 1HR + 225°C 2HR + 715°C 2HR") not parsed. System reported "not stated."
**Fix**: Improve Claude prompt to recognize heat treatment description formats and extract the tempering step.

### 8. Polymer MTR Support
**Affects**: File 2
**Problem**: PEEK and other polymers use completely different property names (melt viscosity, flexural modulus, HDT, etc.) and test methods. Current schema only supports metal MTR properties.
**Fix**: Major feature — needs polymer-specific extraction prompt and spec schema.

### 9. Assembly MTR Support
**Affects**: File 11
**Problem**: Assembly MTRs bundle 5-30+ pages with multiple heats, grades, and specs. Pipeline assumes one-heat-per-PDF.
**Fix**: Major feature — needs document splitter, multi-heat processing, and assembly-level traceability.

### 10. Error Audit Trail
**Affects**: Files 11, 12 (and potentially others)
**Problem**: Files that fail to process leave no trace in history. `_auto_process_watched_file` marks file as processed in watcher memory but writes nothing to history if validation is None.
**Fix**: Log failed attempts to history with error details.

### 11. Less-Than Qualifier Handling
**Affects**: Files 7, 8, 10
**Problem**: Values like "Ta <0.01" stored as numeric 0.01, losing the "<" qualifier. This matters for spec compliance — "<0.01" means the actual value could be anywhere from 0 to 0.0099.
**Fix**: Store qualifier separately or treat as upper bound for validation.

---

## Priority Matrix

| Priority | Issue | Impact | Effort |
|----------|-------|--------|--------|
| **P1** | C-to-F temperature conversion | 3 files affected, causes FAIL on passing material | Low |
| **P1** | Cb/Nb/Ta/V element mapping | 3 files affected, causes MISSING/wrong element | Medium |
| **P1** | Pre-heat/post-heat column detection | 2 files affected, all mechanicals wrong | Medium |
| **P2** | Multi-page document handling | 1 file critical failure | High |
| **P2** | S/Sn element swap | 1 file affected | Low |
| **P2** | Charpy temperature extraction | 1 file affected, -40°C vs +10°C | Medium |
| **P2** | Heat treatment block parsing | 1 file affected, temper missed | Medium |
| **P2** | Error audit trail | Silent failures | Low |
| **P3** | Less-than qualifier handling | Minor data fidelity | Low |
| **P3** | Polymer MTR support | 1 file, new feature | High |
| **P3** | Assembly MTR support | 1 file, architectural change | Very High |

---

## Validation History Summary

From `history/validations.jsonl` — 18 records across 9 unique heats:

| Heat | Spec Used | Result | Notes |
|------|-----------|--------|-------|
| 4000026033 | ES-M2201C → ES-M0001G | FAIL → PASS | Wrong spec first, re-validated correctly |
| 79017611 | ES-M2201C → ES-M0001G | FAIL → PASS | Same pattern |
| 312734 | ES-M2201C → ES-M0001G | FAIL → INCOMPLETE | Chemistry garbled, mechanicals null |
| 626119 | ES-M2201C → ES-M0004A | FAIL → FAIL | Temper °C vs °F caused false FAIL |
| A0959X | ES-M2201C → ES-M0004A | FAIL → FAIL | S/Sn swap + temper °C/°F |
| JT707 (1874) | ES-M2201C → ES-M0009B | FAIL → INCOMPLETE | Cb→Nb mapping failure |
| JT707 (1875) | ES-M0009B | INCOMPLETE | Same heat, same errors |
| 472110 | ES-M2201C → ES-M0003E | FAIL → FAIL | Nb→V, Charpy temp wrong, temper missed |
| B4535 | ES-M2201C → ES-M0009B | FAIL → FAIL | Initially wrong spec |

**Pattern**: 8 of 10 first-attempt validations used ES-M2201C (PEEK plastic spec) as the default, then were re-validated with correct metal specs. The spec auto-detection was not working or defaulting to the wrong spec.
