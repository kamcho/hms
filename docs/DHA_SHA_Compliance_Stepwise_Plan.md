# DHA / SHA HIE Compliance — Stepwise Work Plan

**Purpose:** Track what is already in place and what remains for Digital Health Agency (DHA) / Social Health Authority (SHA) Health Information Exchange (HIE) compliance.  
**Use:** Work through steps in order later; tick items as done.  
**Related:** `docs/SHA_DHA_HMIS_Integration_Board_Report.md` (board briefing — partly outdated on “not implemented” items).  
**Official refs:** [AfyaLink HMIS–HIE guide](https://afyalink.dha.go.ke/hmis-sha-integration-guide) · [Claims](https://afyalink.dha.go.ke/claim-integration) · [Preauth](https://afyalink.dha.go.ke/sha-portal-api-integration) · Developer portal: https://developer.dha.go.ke  

**Last updated:** 2026-07-29  

---

## Status legend

- `[ ]` Not started  
- `[~]` In progress / partial  
- `[x]` Done  

---

## Already in place (foundation — do not re-do)

Keep these; improve only if UAT/production fails.

| Capability | Notes |
|------------|--------|
| Facility auth (`/v1/hie-auth`) | `ShaHieClient` + `.env` credentials |
| Eligibility + client registry | UI + `get_patient_by_id_number` / `fetch_client_registry` |
| Facility registry search | Facility search screen |
| ICD-11 search | Local DB + optional DHA validate |
| HPT med / allergy coding | Partial; mapping command exists |
| Claims desk | OTP → virtual claim → eRx → preauth → submit/status |
| Clinical summary FHIR + encounter sync | Hooks / configurable paths |
| Practitioner licence fields on users | Local fields; not live HWR yet |

---

## Step 1 — Wire SHA verification into intake (highest priority)

**Goal:** SHA visits cannot proceed without eligibility / national ID verification at reception (or equivalent gate).

- [ ] Decide gate point: reception visit open vs OPD check-in  
- [ ] Call eligibility (and CR fetch where required) from that flow  
- [ ] Persist SHA / CR identifiers on the patient (and visit if needed)  
- [ ] Block or hard-warn when payment method is SHA/Insurance and lookup fails  
- [ ] Show scheme coverage clearly (SHIF / ECCIF / PCIF / POMF / ECDF as returned)  
- [ ] UAT: end-to-end check-in with a known test national ID  

**Acceptance:** A SHA visit cannot be opened (or billed as SHA) without a successful eligibility result stored on the record.

---

## Step 2 — Map all billable services to SHA intervention codes

**Goal:** Every claimable service uses a real SHA/PFMS intervention code—not only defaults.

- [ ] Inventory active services (OPD, IPD, maternity packages, lab, imaging, pharmacy-related)  
- [ ] Map each to SHA code (e.g. `SHA-18-005`) in the service / tariff master  
- [ ] Flag services that require pre-authorisation  
- [ ] Store reimbursement tariff / package amount where SHA defines it  
- [ ] Replace reliance on `SHA_HIE_DEFAULT_INTERVENTION_OPD` / `_IPD` for production claims  
- [ ] UAT: claim with mapped intervention codes only  

**Acceptance:** Claim sessions pull intervention codes from mapped services; defaults are fallback only for unmapped legacy rows.

---

## Step 3 — Enforce ICD-11 + practitioner on SHA claims

**Goal:** No SHA claim submit without validated ICD-11 diagnosis and attending practitioner registry data.

- [ ] Require ICD-11 on diagnosis/problem for SHA visits before claim submit  
- [ ] Turn on stricter validation for SHA path (`ICD11_DHA_VALIDATE_STRICT` or equivalent gate)  
- [ ] Require practitioner identification type / number / regulation body on claim session  
- [ ] Prefer live Health Worker Registry check when API is available (see Step 6)  
- [ ] UAT: rejected claim if diagnosis or practitioner missing  

**Acceptance:** Claims desk / auto-submit refuse submit when ICD-11 or practitioner fields are incomplete.

---

## Step 4 — Embed claims lifecycle in clinical workflow (not only Claims Desk)

**Goal:** OTP → consent → (preauth) → care → submit becomes the normal SHA path.

- [ ] From visit: start virtual claim / OTP / consent without leaving clinical screens where possible  
- [ ] Auto-create or attach claim session when SHA visit starts  
- [ ] Trigger preauth when a mapped service requires it (before specialised / package care)  
- [ ] Transmit eRx only after consent token exists (already partly gated)  
- [ ] Close virtual claim on discharge / visit complete  
- [ ] Document staff SOP for Claims Desk vs clinician duties  

**Acceptance:** A typical OPD SHA visit can be completed without using Claims Desk as a separate silo (desk remains for exceptions / finance).

---

## Step 5 — Claim status, remittance, and rejection handling

**Goal:** Finance can reconcile SHA remittances and rejections against local invoices.

- [ ] Poll / refresh claim status from HIE on a schedule or button  
- [ ] Map statuses to local invoice / Insurance Manager states  
- [ ] Capture rejection reasons for clinical / coding fix and resubmit  
- [ ] Remittance posting against patient balances and SHA outstanding  
- [ ] Board/finance report: claim aging, approval vs rejection rates  

**Acceptance:** Every submitted claim has a visible status trail and a reconciliation path into local billing.

---

## Step 6 — Health Worker Registry + facility master alignment

**Goal:** Avoid common HIE rejections (wrong facility level, unknown practitioner).

- [ ] Confirm `SHA_HIE_FACILITY_FR_CODE`, facility name, and level match Facility Registry exactly  
- [ ] Contracted service scope matches what you bill  
- [ ] Add live practitioner / HWR lookup (when endpoint + credentials confirmed)  
- [ ] Admin screen to verify facility + sample practitioner before go-live  
- [ ] UAT: intentional mismatch test documents expected error messages  

**Acceptance:** Preauth/claim org and practitioner identifiers match HIE; facility level mismatches are fixed before production.

---

## Step 7 — Dynamic tariff / benefit package resolution

**Goal:** Payable amounts come from SHA benefit packages (POMSF / PMF / Taifa Care), not hardcoded local SHA assumptions alone.

- [ ] Confirm official tariff / benefit APIs available on facility credentials  
- [ ] Resolve package/intervention amount before billing / claim  
- [ ] Align maternity and IPD packages to SHA package rates  
- [ ] Keep local cash tariffs separate from SHA payable amounts  

**Acceptance:** SHA invoice lines show SHA-resolved (or package) amounts; cash tariffs remain independent.

---

## Step 8 — Pharmacy / HPT / eRx production readiness

**Goal:** Medications on SHA visits use HPT codes and electronic prescribing where required.

- [ ] Complete HPT GE* mapping for formulary (`map_medications_to_dha`)  
- [ ] Decide policy: require HPT code on SHA prescriptions (`HPT_DHA_REQUIRE_CODE`)  
- [ ] Ensure dispense path posts eRx dispense after pharmacy issue  
- [ ] Allergy list checked before prescribe (already prompted; enforce for SHA)  
- [ ] UAT: prescribe → transmit → dispense for a SHA visit  

**Acceptance:** SHA prescriptions carry HPT codes and have a successful eRx transmit/dispense trail in UAT.

---

## Step 9 — Shared encounter / clinical summary production proof

**Goal:** Minimised encounter summaries sync to HIE as required for continuity of care.

- [ ] Confirm production paths for clinical FHIR bundle + encounter sync  
- [ ] Generate clinical summary on closed SHA visits (SOP)  
- [ ] Verify HIE sync status on `ClinicalSummary` after submit  
- [ ] Handle sync failures with retry + audit log  
- [ ] UAT: one full visit with successful SHR / encounter sync  

**Acceptance:** At least one UAT visit shows successful clinical bundle + encounter sync with stored response.

---

## Step 10 — Certification & legal pack (parallel track)

**Goal:** DHA HMIS certification + Data Protection Act readiness (non-code, mandatory).

- [ ] ODPC registration as data controller / processor  
- [ ] Formal DPIA by a qualified assessor  
- [ ] Security, privacy & confidentiality policy (documented + enforceable)  
- [ ] Backup & recovery policy with **tested** RTO/RPO evidence  
- [ ] Form **HMIS 4** self-attestation / gap analysis vs Certification Framework  
- [ ] Clarify with DHA: ILM middleware for terminology vs “direct HMIS, no middleware” rule  
- [ ] Sandbox → production credentials after UAT sign-off  
- [ ] Target awareness: certified HMIS + SHA claims often cited by **~1 Sep 2026**  

**Acceptance:** Certification pack submitted (or ready to submit) with technical UAT evidence attached.

---

## Suggested order for “later today” sessions

| Session | Focus | Steps |
|---------|--------|-------|
| A | Intake gate | Step 1 |
| B | Service ↔ SHA codes | Step 2 |
| C | Claim hard rules | Step 3 (+ start Step 4) |
| D | Finance loop | Step 5 |
| E | Facility / practitioners | Step 6 |
| F | Tariffs & pharmacy | Steps 7–8 |
| G | SHR + certification | Steps 9–10 |

---

## Environment checklist (before each UAT session)

- [ ] `SHA_HIE_BASE_URL` (UAT vs prod)  
- [ ] `SHA_HIE_USERNAME` / `PASSWORD` / `AGENT_ID` / consumer key+secret  
- [ ] `SHA_HIE_FACILITY_FR_CODE` / `SHA_HIE_FACILITY_NAME`  
- [ ] Default interventions only as temporary fallback  
- [ ] SSL verify on for non-local testing  
- [ ] Run `diagnose_sha_hie` (or equivalent) and keep output with the session notes  

---

## Notes log (append as you go)

| Date | Step | What was done | Result / blocker |
|------|------|---------------|------------------|
| 2026-07-29 | — | Work plan created from gap review | Ready to execute |
|  |  |  |  |

---

*When picking up later: start at the first unchecked Step, update the Notes log, and tick Acceptance when met.*
