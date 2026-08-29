# SHA / DHA eClaims: Intervention Combination Rule Book

**Document Version:** 1.0  
**Authority:** Social Health Authority (SHA) / Digital Health Agency (DHA) Kenya  
**References:** 
- [DHA SHA Combination Rules](https://hie-docs.dha.go.ke/docs/claims/guides/sha-combination-rules)
- [DHA Special Benefit Rules](https://hie-docs.dha.go.ke/docs/claims/guides/benefit-rules)
- [DHA Benefit & Intervention Codes](https://hie-docs.dha.go.ke/docs/claims/guides/benefit-intervention-codes)
- [DHA Interventions API](https://hie-docs.dha.go.ke/eclaims/interventions)

---

## 1. Core Architectural Principles

### 1.1. The Hierarchy
1. **Benefit Package (`SHA-XX` or `PMF-XX`)**: Broad category of healthcare services (e.g., `SHA-07` Inpatient Services, `SHA-12` Outpatient Services).
2. **Intervention Code (`SHA-XX-YYY`)**: Granular, billable clinical service package (e.g., `SHA-12-001` Outpatient Consultation, `SHA-04-002` Appendectomy).
3. **Billable Line Items**: The individual medicines, lab tests, consumable supplies, and doctor fees billed under an active intervention.

### 1.2. The Primary Intervention Model
- The **first intervention** attached to a claim (via `POST /claims/visit` during check-in/consent) sets the **Primary Context** for the entire visit.
- Any additional intervention added subsequently (via `POST /claims/interventions`) is evaluated against the combination rules of that primary code.

---

## 2. Standard SHA Covers Combination Matrix

*Applicable to standard SHIF and Emergency/Critical Care (ECCIF) covers.*

| Primary Code | Package Name | Allowed Secondary Combinations on Same Claim | Forbidden Combinations (Rejection Rules) |
| :--- | :--- | :--- | :--- |
| **`SHA-01`** | **Ambulance & Emergency** | **None** | Cannot combine with any code. Standalone emergency transfer/resuscitation. |
| **`SHA-03`** | **Critical Care (ICU/HDU)** | `SHA-07`, `SHA-06`, `SHA-16`, `SHA-09`, `SHA-13`, `SHA-08`, `SHA-19` *(subject to surgical rules)* | Cannot combine with `SHA-12` (Outpatient), `SHA-05` (Optical), `SHA-18` (NCD Labs), `SHA-10` (Mental). |
| **`SHA-05`** | **Optical Health** | **ALONE** (No other interventions allowed) | Cannot combine with any other package. |
| **`SHA-06`** | **Haematology & Oncology** | **ALONE** (No other interventions allowed) | Standalone chemotherapy / oncology therapy encounter. |
| **`SHA-07`** | **Inpatient Services** | `SHA-03`, `SHA-06`, `SHA-09`, `SHA-19`, `SHA-16` *(sub-codes: `001, 002, 004, 007, 008, 011`)* | Cannot combine with `SHA-12` (Outpatient), `SHA-05` (Optical), `SHA-18` (NCD Labs), `SHA-10` (Mental). |
| **`SHA-08`** | **Maternity & Child Health** | `SHA-03`, `SHA-09`, `SHA-07-005`, `SHA-07-006` *(only after lapse of maternity global period)* | Cannot combine with routine outpatient, standalone NCD labs, or elective surgeries. |
| **`SHA-09`** | **Medical Imaging** | **ALONE** | Standalone imaging referrals. *(If imaging is done during admission, it is added under `SHA-07` or `SHA-03`).* |
| **`SHA-10`** | **Mental Wellness** | **ALONE** | Standalone mental health encounter. |
| **`SHA-12`** | **Outpatient Services** | **ALONE** | Cannot combine with Inpatient (`SHA-07`), Surgical (`SHA-19`), Critical Care, or other standalone packages. |
| **`SHA-13`** | **Palliative Care** | `SHA-03`, `SHA-06`, `SHA-07`, `SHA-09`, `SHA-16`, `SHA-19` | Cannot combine with `SHA-12` (Outpatient), `SHA-05` (Optical), `SHA-18` (NCD Labs). |
| **`SHA-16`** | **Renal Care** | **Standalone only:** `SHA-16-001`, `002`, `004`<br>**Combinable (`SHA-03` & `SHA-07`):** `SHA-16-003`, `005`, `006`, `007`, `009` | Cannot combine standalone dialysis sessions with outpatient visits. |
| **`SHA-18`** | **NCD Diagnostic Labs** | **ALONE** | Cannot combine with any other package. Standalone chronic lab panel. |
| **`SHA-19`** | **Surgical Services** | `SHA-07-002`, `SHA-09`, `SHA-03` & `SHA-13` *(only after lapse of surgical global period)* | Cannot combine with routine outpatient consultation. |

---

## 3. Public Officers Medical Scheme Fund (POMSF) Matrix

*Applicable when a visit is billed under a POMSF cover (`PMF-` namespace).*

| Primary Code | Package Name | Allowed Secondary Combinations on Same Claim | Rule on "ALONE" Packages |
| :--- | :--- | :--- | :--- |
| **`PMF-03`** | **Critical Care** | `SHA-06`, `SHA-09`, `PMF-07`, `PMF-10`, `PMF-13`, `SHA-16`, `SHA-19`, `SHA-08` | Combinable |
| **`SHA-05`** | **Optical Health** | **ALONE** | Close `SHA-05` visit and start a new visit for other care. |
| **`SHA-06`** | **Haemato-Oncology** | **ALONE** | Close `SHA-06` visit and start a new visit for other care. |
| **`SHA-08`** | **Maternity & Child Health** | `PMF-07`, `SHA-19`, `SHA-16`, `PMF-03`, `SHA-06`, `SHA-09` | Broader combination than standard SHA. |
| **`SHA-09`** | **Medical Imaging** | **ALONE** | Close `SHA-09` visit and start a new visit for other care. |
| **`SHA-11`** | **Oral Health (Dental)** | **ALONE** | Close `SHA-11` visit and start a new visit for other care. |
| **`PMF-07` / `PMF-10`** | **Inpatient Services** | `PMF-03`, `SHA-06`, `SHA-09`, `PMF-13`, `SHA-15`, `SHA-16`, `SHA-19`, `SHA-08` | Combinable |
| **`PMF-12`** | **Outpatient Services** | **None** | Close `PMF-12` visit and start a new visit for other care. |
| **`PMF-13`** | **Palliative Care** | `PMF-03`, `SHA-06`, `SHA-09`, `SHA-16`, `SHA-19`, `SHA-08` | Combinable |
| **`SHA-16`** | **Renal Care** | **Standalone:** `SHA-16-001, 002, 004`<br>**Combinable (`PMF-03` & `PMF-07`):** `SHA-16-003, 005, 006, 007, 009` | Standalone codes must be closed before starting other visits. |
| **`SHA-19`** | **Surgical Services** | `PMF-07`, `SHA-09`, `SHA-16`, `PMF-03` & `PMF-13` *(after global period)* | Combinable with POMSF inpatient & critical care. |

---

## 4. Special Benefit & Global Period Rules

### 4.1. Surgical Global Periods (`SHA-19`)
- Surgical intervention packages include bundled pre-operative, intra-operative, and post-operative ward care for a predefined window (typically **14 to 30 days** depending on minor vs. major surgery).
- **Rule:** You **cannot** bill general inpatient daily per-diem (`SHA-07`) during the surgical global period, as accommodation is already bundled into the surgery tariff.
- Inpatient bed codes can only be added if hospitalization extends **past** the surgical global period.

### 4.2. Maternity Global Periods (`SHA-08`)
- Delivery packages cover normal delivery / C-section and the standard immediate postpartum stay.
- Extended inpatient codes (`SHA-07-005` or `SHA-07-006`) can only be attached if maternal medical complications prolong admission beyond the standard delivery global period.

### 4.3. Dual Per-Diem Prohibition
- A patient **cannot** have two active per-diem bed packages on the same calendar day (e.g., General Ward `SHA-07-001` and ICU Bed `SHA-03-001`).
- **Required Action:** When a patient is transferred (e.g., Ward $\rightarrow$ ICU), use **Switch Intervention** rather than adding a second bed code.

---

## 5. API Operations Reference for Interventions

| Operation | Endpoint | When to Use | Payload Parameters |
| :--- | :--- | :--- | :--- |
| **Add Intervention** | `POST /claims/interventions` | Add a new eligible package to an active authorized claim (e.g., adding Surgery during Inpatient admission). | `consent_token`, `intervention_code` |
| **Switch Intervention** | `POST /claims/interventions/switch` | Replace an existing intervention with a new one (e.g., transferring patient from General Ward to ICU). | `consent_token`, `from_intervention_code`, `to_intervention_code` |
| **Retire Intervention** | `POST /claims/interventions/retire` | Deactivate a planned service that was not rendered before billing. | `consent_token`, `intervention_code` |
| **Restore Intervention** | `POST /claims/interventions/restore` | Re-activate a previously retired intervention. | `consent_token`, `intervention_code` |

---

## 6. Practical Rules of Thumb for Hospital Staff

1. **Outpatient Consultation (`SHA-12`)**:
   - Routine laboratory tests and prescribed medicines are billed as **Line Items** on the `SHA-12` claim.
   - Do **NOT** attempt to add separate intervention packages for routine outpatient labs.
2. **Outpatient to Inpatient Escalation**:
   - If an outpatient needs admission, **close the `SHA-12` outpatient claim** and **open a new `SHA-07` inpatient visit** with new admission consent.
3. **Standalone Packages ("ALONE")**:
   - Optical (`SHA-05`), Mental Wellness (`SHA-10`), NCD Diagnostic Lab Listing (`SHA-18`), and routine Outpatient (`SHA-12`) must always remain standalone claims.
