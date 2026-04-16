# Assembly MTR Validation Plan

## Summary

Add assembly MTR support: detect assembly packets (COC cover sheet + individual component MTRs), extract the component/heat table from the COC, cross-reference each listed heat number against MTRs found in the packet, and produce a traceability pass/fail result. TIFF saved as `<PO>_<CustomerPartNumber>.tiff`. Missing heats warn but allow override. No per-component spec validation (heat traceability only).

## Requirements

1. **Assembly Detection**: Auto-detect assembly packets by analyzing page 1 for COC characteristics (component table with heat numbers). Also provide a manual "Assembly" toggle in the GUI.
2. **COC Parsing**: Extract from cover sheet: PO number, customer part number, and a table of components with (part description, part number, heat number).
3. **Heat Traceability**: For each component MTR in the packet (pages 2+), extract the heat number. Cross-reference against the COC table. Report which heats are found, which are missing.
4. **Shared Heats**: Multiple components can share a heat number. One MTR satisfies all components referencing that heat.
5. **Validation Result**: PASS if all COC-listed heat numbers have at least one matching MTR. WARN (with list of missing heats) if some are missing — user can still approve with override.
6. **Manual Heat Addition**: If a heat is missing from the packet, user can manually attach/reference it (mark as "externally verified").
7. **TIFF Naming**: `<PO>_<CustomerPartNumber>.tiff` for assemblies. If either is missing, prompt user before approval.
8. **Single TIFF**: Entire assembly packet saved as one TIFF file (no splitting).

## Acceptance Criteria

- [ ] Assembly packet auto-detected when page 1 contains COC with component table
- [ ] GUI toggle allows manual assembly mode selection
- [ ] COC table parsed: PO, customer part number, and component list with heat numbers extracted
- [ ] Each subsequent MTR page has its heat number extracted
- [ ] Cross-reference produces traceability matrix (COC heat → found/missing)
- [ ] PASS when all heats accounted for; WARN when heats missing
- [ ] User can override missing heats and still approve
- [ ] TIFF saved as `PO_CustomerPartNumber.tiff`
- [ ] Missing PO or customer part number prompts user input before approval
- [ ] Existing single-part MTR workflow unchanged (no regressions)

## Architecture

### New Module: `src/lib/assembly.py`

Central module for all assembly logic. No changes to existing validation pipeline for single-part MTRs.

```python
@dataclass
class AssemblyComponent:
    part_description: str
    part_number: str
    heat_number: str
    found_on_page: Optional[int] = None  # page where matching MTR was found
    status: str = 'MISSING'  # 'FOUND', 'MISSING', 'MANUAL'

@dataclass
class AssemblyResult:
    is_assembly: bool = False
    po_number: str = ''
    customer_part_number: str = ''
    invoice_number: str = ''
    components: List[AssemblyComponent] = field(default_factory=list)
    mtr_heats: Dict[int, str] = field(default_factory=dict)  # page -> heat
    overall_status: str = 'UNKNOWN'  # 'PASS', 'WARN', 'FAIL'
    warnings: List[str] = field(default_factory=list)
```

**Key functions:**

1. `detect_assembly(ocr_text: str, image_paths: list, api_key: str) -> bool`
   - Send page 1 image to Claude Haiku with a targeted prompt: "Is this a Certificate of Compliance listing multiple components with heat numbers? YES/NO"
   - Cost: ~$0.002, ~2s (same pattern as `_haiku_mtr_check`)
   - Fallback: regex scan of OCR text for "certificate of compliance" + table patterns

2. `parse_coc_cover_sheet(ocr_text: str, image_paths: list, api_key: str) -> AssemblyResult`
   - Send page 1 image to Claude Sonnet with structured prompt to extract:
     - PO number, customer part number, invoice number
     - Component table: [{part_description, part_number, heat_number}, ...]
   - Returns partially-filled `AssemblyResult` with components list

3. `extract_mtr_heats(ocr_text: str, image_paths: list, api_key: str) -> Dict[int, str]`
   - For pages 2+, extract just the heat number from each page
   - Use Claude Haiku with vision on each page (or batch of 2-3 pages): "What is the heat number on this document? Return ONLY the heat number."
   - Group consecutive pages that belong to the same MTR (same heat = same document)
   - Returns {page_number: heat_number}

4. `cross_reference(assembly: AssemblyResult) -> AssemblyResult`
   - Match each component's COC heat number against `mtr_heats` values
   - Mark components as FOUND (with page number) or MISSING
   - Handle shared heats: one MTR page satisfies all components with that heat
   - Set overall_status: PASS (all found), WARN (some missing)

### Pipeline Integration: `src/lib/pipeline.py`

Add assembly branch after pre_extract, before the existing Claude parse step:

```
pre_extract() → detect_assembly()
  ├─ YES → parse_coc_cover_sheet() → extract_mtr_heats() → cross_reference()
  │         → AssemblyResult (traceability only, no spec validation)
  └─ NO  → existing pipeline (Claude parse → normalize → validate → etc.)
```

New parameter on `process_document()`:
- `force_assembly: Optional[bool] = None` — `True` = force assembly mode, `False` = force single-part, `None` = auto-detect

New field on `PipelineResult`:
- `assembly_result: Optional[AssemblyResult] = None`

### GUI Changes: `src/gui/app.py`

1. **Assembly toggle** in controls row (next to PO field):
   - `self.assembly_var = ctk.StringVar(value='Auto')`
   - Dropdown: `['Auto', 'Assembly', 'Single Part']`
   - Passed as `force_assembly` to pipeline

2. **Assembly results display** in the Validation Result card:
   - Show traceability matrix: component → heat → FOUND/MISSING
   - Color-coded: green for found, orange for missing
   - Overall status badge: PASS / WARN

3. **Missing heat override**:
   - When assembly has WARN status, show "Add Missing Heat" button
   - Opens dialog where user can mark a heat as "externally verified" with a note
   - Updates component status to MANUAL, recalculates overall

4. **Approval flow changes**:
   - Assembly PASS → approve normally
   - Assembly WARN with all missing heats manually resolved → approve
   - TIFF naming uses `PO_CustomerPartNumber.tiff` instead of `HeatNumber-PO.tiff`
   - If PO or customer part number missing from COC extraction, prompt user

5. **Customer Part Number field**:
   - New entry field (like PO field) that appears when assembly mode is active
   - Pre-filled from COC extraction, editable by user

### TIFF Naming: `src/gui/tiff_export.py`

Add `generate_assembly_archive_filename(po_number, customer_part_number)`:
```python
def generate_assembly_archive_filename(po_number: str, customer_part_number: str) -> str:
    po = sanitize_filename(po_number or 'UNKNOWN-PO')
    part = sanitize_filename(customer_part_number or 'UNKNOWN-PART')
    return f"{po}_{part}.tiff"
```

## Implementation Steps

### Step 1: Assembly data structures and detection (`src/lib/assembly.py`) — NEW FILE
- Create `AssemblyComponent`, `AssemblyResult` dataclasses
- Implement `detect_assembly()` using Haiku vision on page 1
- Implement `parse_coc_cover_sheet()` using Sonnet vision on page 1
- Implement `extract_mtr_heats()` using Haiku vision on pages 2+
- Implement `cross_reference()` matching logic
- Handle shared heats (multiple components → same heat number)
- Unit tests: `tests/test_assembly.py`

### Step 2: Pipeline integration (`src/lib/pipeline.py`)
- Add `force_assembly` parameter to `process_document()`
- Add `assembly_result` field to `PipelineResult`
- After `pre_extract()`, call `detect_assembly()` (or check `force_assembly`)
- If assembly: run assembly pipeline, skip spec validation, return `AssemblyResult`
- If single-part: existing pipeline unchanged

### Step 3: TIFF naming for assemblies (`src/gui/tiff_export.py`)
- Add `generate_assembly_archive_filename(po, customer_part_number)`
- Modify `_approve()` to use assembly naming when `assembly_result` is present

### Step 4: GUI — Assembly toggle and display (`src/gui/app.py`)
- Add Assembly mode dropdown in controls row
- Add Customer Part Number entry field (shown for assembly mode)
- Update results display for assembly traceability matrix
- Add "Add Missing Heat" button and dialog for manual override
- Update `_approve()` for assembly-specific flow (naming, validation gating)

### Step 5: Integration testing with real assembly packet
- Process `2026.02.ASSEMBLEYMTR.PO1628.pdf` end-to-end
- Verify COC parsing extracts all 10 components with correct heat numbers
- Verify MTR heat extraction finds matching heats on pages 2-30
- Verify traceability cross-reference produces correct PASS/WARN
- Verify TIFF saved as `001628_451-118-00-A2000-R0.tiff`

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| COC formats vary between vendors | Use Claude vision (not rigid regex) for COC parsing — adapts to different layouts |
| Multi-page MTRs (one component spans 2-3 pages) | Group consecutive pages with same heat number as one MTR document |
| Heat number format mismatches (COC says "D1914127", MTR says "D-1914127") | Normalize heat numbers: strip hyphens, spaces, leading zeros before comparison |
| Claude costs for per-page heat extraction on 30-page packets | Use Haiku ($0.001/page) and batch pages where possible; ~$0.03 total for 30 pages |
| Some MTR pages may have no heat number (e.g., heat treatment certs reference a different ID) | Fall back to matching any identifier on the page against COC heats |

## Cost Estimate (per assembly packet)

| Step | Model | Cost |
|------|-------|------|
| Assembly detection | Haiku (1 image) | ~$0.002 |
| COC parsing | Sonnet (1 image) | ~$0.01 |
| MTR heat extraction | Haiku (~15 unique pages) | ~$0.03 |
| **Total** | | **~$0.04** |

Compared to current single-part pipeline (~$0.05-0.15 with Sonnet vision), assembly validation is cheaper since we only extract heat numbers, not full chemistry/mechanical data.
