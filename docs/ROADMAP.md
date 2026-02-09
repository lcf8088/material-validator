# Material Cert Validator - Roadmap to Production

## Current State Assessment

**What Works:**
- ✅ CLI validates MTR JSON against YAML specs
- ✅ 4 specs loaded with chemistry + mechanical + special requirements
- ✅ Auto-detection by UNS/grade/yield strength
- ✅ Vision extraction tested (manual workflow)
- ✅ Unit conversions (ksi↔MPa, HRc↔HBW)
- ✅ Color-coded pass/fail output

**What's Missing:**
- ❌ End-to-end automation (still requires manual steps)
- ✅ Validation history / audit trail
- ❌ Batch processing
- ✅ Sanity checks and borderline warnings for extracted data
- ❌ Spec revision management

---

## Gap Analysis by Category

### 1. WORKFLOW & USABILITY

**Current Pain Points:**
- Must convert PDF → images → copy JSON → run CLI
- Technical barrier: requires command line knowledge
- No feedback loop for extraction errors
- Results disappear after viewing

**Needed Improvements:**

| Priority | Feature | Description |
|----------|---------|-------------|
| P0 | **One-Command Validation** | `validate mtr.pdf` does everything |
| P1 | **Extraction Review** | Show extracted data for approval before validation |
| P1 | **Result Storage** | Save all validations to searchable history |
| P2 | **Batch Mode** | Validate folder of MTRs, generate summary report |
| P2 | **Quick Re-validate** | Re-run validation when spec changes |

**Ideal Workflow:**
```
Lance drops MTR PDF into desktop app
  ↓
App extracts data via vision LLM
  ↓
App shows extracted values: "Found Heat# X, Grade Y. Confirm?"
  ↓
Lance confirms (or corrects)
  ↓
App validates against auto-detected spec
  ↓
App reports: "PASS - Heat# X validates against ES-M0001G"
  ↓
Result saved to validation history
```

---

### 2. DATA QUALITY & RELIABILITY

**Current Risks:**
- Vision extraction can misread values (OCR errors)
- No confidence scoring
- No way to flag suspicious values
- Chemistry values could be swapped (Cr vs Ni column)

**Needed Improvements:**

| Priority | Feature | Description |
|----------|---------|-------------|
| P0 | **Extraction Confidence** | Flag low-confidence extractions for review |
| P0 | **Range Sanity Checks** | Alert if C% > 1 or YS > 300 (obviously wrong) |
| P1 | **Dual Extraction** | Extract twice, compare results |
| P1 | **Human Review Queue** | Flag certs that need manual verification |
| P2 | **Learning from Corrections** | Track which mill formats cause errors |

**Sanity Check Rules:**
```yaml
sanity_checks:
  chemistry:
    C:  { max: 2.0, alert: "Carbon > 2% is unusual" }
    Cr: { max: 30.0, alert: "Chromium > 30% - verify" }
    Ni: { max: 80.0, alert: "Nickel > 80% - verify" }
  mechanical:
    yield_strength: { max: 300, alert: "YS > 300 ksi - verify" }
    elongation: { max: 80, alert: "Elongation > 80% - verify" }
    hardness_hrc: { max: 70, alert: "HRc > 70 - verify" }
```

---

### 3. COMPLIANCE & AUDIT

**Requirements (from specs):**
- 10-year document retention (section 4.3 of ES-M0003A)
- Traceability: who validated, when, against which spec revision
- Sign-off capability for critical applications

**Needed Improvements:**

| Priority | Feature | Description |
|----------|---------|-------------|
| P0 | **Validation Log** | JSON log of all validations with timestamps |
| P1 | **Spec Version Tracking** | Record which spec revision was used |
| P1 | **Original Document Archive** | Store source PDF with validation |
| P2 | **Digital Signature** | Hash of MTR + spec + result for integrity |
| P3 | **Expiration Alerts** | Notify when material certs are aging out |

**Validation Record Schema:**
```json
{
  "validation_id": "uuid",
  "timestamp": "2026-02-06T19:30:00Z",
  "validated_by": "Cipher",
  "heat_number": "D2213660",
  "material_grade": "4140/42",
  "spec_id": "ES-M0001G",
  "spec_revision": "0",
  "result": "PASS",
  "pass_count": 13,
  "fail_count": 0,
  "source_document": "path/to/original.pdf",
  "extracted_data": { ... },
  "validation_details": { ... }
}
```

---

### 4. EDGE CASES & ROBUSTNESS

**Known Edge Cases:**

| Case | Current Handling | Needed |
|------|------------------|--------|
| Multi-page MTR | Manual stitch | Auto-merge pages |
| Multiple heats on one cert | Not handled | Parse each heat separately |
| Supplemental heat treat cert | Not handled | Link to original mill cert |
| Non-standard units | Partial (ksi/MPa) | Add N/mm², kg/mm², etc. |
| Hardness in HRB | Conversion exists | Verify accuracy for soft materials |
| Spec not found | Error message | Suggest closest match |
| Borderline values | Binary pass/fail | Flag "within 5% of limit" |

**Borderline Alert Example:**
```
Yield Strength: 111.2 ksi (min: 110)
⚠️ Within 2% of minimum - verify measurement
```

---

### 5. INTEGRATION POINTS

**Current:**
- Standalone CLI
- Desktop GUI (drag-and-drop)

**Needed:**

| Integration | Purpose | Priority |
|-------------|---------|----------|
| **File Storage** | Archive MTRs and results | P1 |
| **Desktop Notification** | Alert on failures | P1 |
| **Calendar** | Track cert expiration dates | P3 |
| **Inventory** | Link certs to material in stock | P3 |

---

### 6. SPEC MANAGEMENT

**Current Issues:**
- Specs are static YAML files
- No revision history
- No way to see what changed between revisions
- No alerts when using outdated spec

**Needed:**

| Feature | Description | Priority |
|---------|-------------|----------|
| **Revision History** | Track changes between spec versions | P1 |
| **Deprecation Warnings** | Alert when using old revision | P1 |
| **Spec Comparison** | Diff two spec versions | P2 |
| **Import from PDF** | Extract spec from engineering document | P3 |

---

## Implementation Phases

### Phase 1: Data Quality (Next)
- [x] Add sanity checks for extracted values
- [ ] Confidence scoring on extraction
- [x] Borderline value warnings
- [ ] Human review queue for failures

### Phase 2: Compliance
- [x] Structured validation log (JSON)
- [ ] Archive original documents
- [ ] Spec revision tracking
- [ ] Export validation reports

### Phase 3: Polish
- [ ] Batch processing
- [ ] Summary reports
- [ ] Spec comparison tools
- [ ] Performance optimization

---

## Quick Wins (Can Do Now)

1. **Add validation history file** - Simple JSON append log
2. **Sanity checks** - Basic range validation before spec check
3. **Borderline warnings** - Flag values within 5% of limits
4. **Better error messages** - Suggest corrections for common issues
5. **Better CLI UX** - `validate mtr.pdf` does everything in one command

---

## Questions for Lance

1. **Volume**: How many MTRs per week/month need validation?
2. **Urgency**: Real-time validation needed, or batch overnight OK?
3. **Sign-off**: Do validated certs need formal approval workflow?
4. **Archive**: Where should original PDFs be stored long-term?
5. **Access**: Who else besides you might validate certs?
6. **Failures**: What happens when a cert fails? Reject shipment? Request retest?
