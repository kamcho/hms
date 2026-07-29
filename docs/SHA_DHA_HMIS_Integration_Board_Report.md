# BOARD BRIEFING REPORT

## Integration of the Hospital Management Information System (HMIS)  
### with the Digital Health Agency (DHA) / Social Health Authority (SHA)  
### Health Information Exchange (HIE)

| | |
|---|---|
| **Document Type** | Board Briefing / Strategic Technical Assessment |
| **Prepared For** | Hospital Board of Management |
| **Subject** | Mandatory HMIS–SHA Digital Integration Requirements |
| **Classification** | Internal — Board Circulation |
| **Status** | For Decision / Noting |

---

## 1. Executive Summary

The Social Health Authority (SHA), working with the Digital Health Agency (DHA), has made **accredited, digitally connected Health Management Information Systems (HMIS) mandatory** for continued participation in SHA-funded schemes, including the forthcoming contracting cycle.

Facilities that fail to integrate with the national Health Information Exchange (HIE) risk:

- Ineligibility for **contract renewal** or continued SHA participation  
- Delayed or refused **claims reimbursement**  
- Operational disruption where **manual / paper-based** claims processes are phased out  

This report outlines:

1. The **mandatory technical architecture** (AfyaLink API Gateway and seven core API categories)  
2. What each integration area requires of our HMIS  
3. An assessment of **our current system readiness**  
4. Which hospital modules will be **affected, updated, or overhauled**  
5. Recommended **next steps** for Board consideration  

**Bottom line:** Integration is not a minor enhancement. It is a **facility-wide clinical, billing, and compliance programme** requiring new national registries connectivity, automated pre-authorisation and electronic claims, and significant changes to registration, inpatient, maternity, laboratory, pharmacy, and finance workflows.

---

## 2. Purpose of This Report

To enable the Board to:

- Understand **what GOK / SHA / DHA require** of our HMIS  
- Appreciate the **scope and risk** of non-compliance  
- Approve direction for **implementation planning, budgeting, and timelines**

---

## 3. Policy & Contracting Context

Healthcare providers are required to remain electronically connected to SHA’s centralised digital platform to support:

- Real-time **service verification**  
- Electronic **claims processing**  
- Secure **health information exchange**  

HMIS platforms must:

- Meet **national digital health standards**  
- Integrate with Kenya’s comprehensive health information systems  
- Comply with the **Data Protection Act**  
- Prefer **direct HMIS-to-HIE integration** (not unofficial middleware)  

Official developer onboarding and credentials are issued through the DHA portal (**AfyaLink / developer.dha.go.ke**), after organisation registration and verification.

---

## 4. Technical Architecture Overview

| Element | Description |
|---------|-------------|
| **Gateway** | AfyaLink API Gateway |
| **Pattern** | RESTful microservices |
| **Data format** | JSON |
| **Clinical / claims standard** | HL7 FHIR (R4) |
| **Security** | Facility-scoped Bearer tokens (OAuth-style) |
| **Environments** | Sandbox / UAT for development; Production for live claims |

Every transaction follows a controlled sequence: **authenticate → verify patient & eligibility → confirm practitioner / facility → resolve tariff / benefits → (where required) pre-authorise → deliver care → submit claim → sync shared encounter record**.

---

## 5. Mandatory Integration: Seven Core API Categories

To connect our HMIS to the DHA / SHA HIE, **seven core API categories (microservices)** must be implemented. These are grouped across functional national registries and claims workflows, as follows.

### 5.1 Authentication & Security  
**(1 endpoint)**

Every transaction requires a secure connection. The HMIS must first call the security endpoint to obtain a **Bearer Token** that scopes API access to our facility.

| Method | Endpoint (illustrative) | Purpose |
|--------|-------------------------|---------|
| `POST` | `/v1/auth/token` (or equivalent OAuth gateway) | Authenticate the facility using keys issued from the DHA Developer Portal |

**Board implication:** Credential governance, secret management, and audited facility identity become a permanent ICT / compliance responsibility.

---

### 5.2 Client Registry / Patient Verification  
**(2 endpoints)**

Before check-in, the HMIS must query the central **DHA Client Registry** to obtain the patient’s unique national identifier and verify eligibility.

| Method | Endpoint (illustrative) | Purpose |
|--------|-------------------------|---------|
| `GET` | `/api/v1/client-registry/verify` | Live verification via National ID, Passport, or biometrics |
| `POST` | `/api/v1/client-registry/validate-biometrics` | Real-time biometric verification at reception |

**Board implication:** Reception / registration ceases to be “local demographics only.” Care pathways for SHA patients start with **central identity and eligibility** confirmation.

---

### 5.3 Practitioner & Facility Registries  
**(2 endpoints)**

SHA requires tracking of attending clinical staff and confirmation of facility routing parameters.

| Method | Endpoint (illustrative) | Purpose |
|--------|-------------------------|---------|
| `GET` | `/api/v1/registries/health-worker` | Validate the attending doctor’s professional licence and registration number |
| `GET` | `/api/v1/registries/facility` | Verify facility MFL (KMHFL) code and scope configurations |

**Board implication:** Claims and care attribution will depend on correctly linked **facility and clinician** master data—not only local staff lists.

---

### 5.4 Tariff & Benefit Resolution  
**(2 endpoints)**

Billing must automatically determine what SHA will pay for a procedure or treatment plan under the **Taifa Care** scheme.

| Method | Endpoint (illustrative) | Purpose |
|--------|-------------------------|---------|
| `POST` | `/api/v1/benefits/pomsf-rates` | Evaluate treatment costs against the medical worker’s registry specialty |
| `POST` | `/api/v1/benefits/pmf-tariffs/resolve` | Resolve bundled package rates for requested interventions |

**Board implication:** Hardcoded local SHA rates must be replaced or subordinated to **official benefit / package resolution**. Finance visibility of expected reimbursement will improve if implemented correctly.

---

### 5.5 Pre-Authorisation & ICD-11 Mapping  
**(2 endpoints)**

For surgical, specialised, or critical chronic care, the system must submit automated pre-authorisation requests and use standardised diagnosis coding.

| Method | Endpoint (illustrative) | Purpose |
|--------|-------------------------|---------|
| `POST` | `/v1/shr-med/bundle` | Submit a clinical pre-authorisation package (FHIR bundle) to the central HIE |
| `GET` | `/api/v1/clinical/icd11` | Map / validate standard medical diagnosis codes (ICD-11) |

**Board implication:** Clinical documentation quality (ICD-11) and pre-authorisation discipline become **billing prerequisites**, not optional administrative extras.

---

### 5.6 Claims Management  
**(2 endpoints)**

After treatment, claims move electronically—reducing dependence on paper submissions.

| Method | Endpoint (illustrative) | Purpose |
|--------|-------------------------|---------|
| `POST` | `/v1/shr-med/claim/submit` | Transmit the final billing and clinical package to the SHA clearinghouse |
| `GET` | `/v1/shr-med/claim-status?claim_id={id}` | Track whether a claim is approved, flagged, or rejected in real time |

**Board implication:** The Insurance / Claims desk shifts from “record a local insurance payment” to **electronic submission, status monitoring, rejection handling, and remittance reconciliation**.

---

### 5.7 Shared Health Record / Shared Encounter  
**(1 endpoint)**

To complete integration, the system must stream minimal encounter summaries to the HIE to support continuity of care.

| Method | Endpoint (illustrative) | Purpose |
|--------|-------------------------|---------|
| `POST` | `/api/v1/encounter/sync` | Send basic treatment, lab references, and medication notes to the Shared Health Record repository |

**Board implication:** Selected clinical encounter data becomes part of the **national continuity-of-care layer**, subject to privacy, consent, and Data Protection Act controls.

---

### 5.8 Endpoint Summary (12 interfaces across 7 categories)

| # | Category | Endpoints | Role in workflow |
|---|----------|-----------|------------------|
| 1 | Authentication & Security | 1 | Secure facility access |
| 2 | Client Registry / Patient Verification | 2 | Identity & eligibility before care |
| 3 | Practitioner & Facility Registries | 2 | Clinician & facility validation |
| 4 | Tariff & Benefit Resolution | 2 | Automatic SHA payable amounts |
| 5 | Pre-Authorisation & ICD-11 | 2 | Controlled / specialised care approvals |
| 6 | Claims Management | 2 | Electronic claim & status tracking |
| 7 | Shared Encounter / SHR | 1 | Continuity of care to HIE |

---

## 6. Assessment of Our Current HMIS Readiness

Our current Hospital Management Information System supports **facility-local SHA operations**, not full national HIE integration.

### What is already in place (useful foundation)

- Visit-level classification of patients as **SHA** vs **Cash**  
- An **Insurance Manager** workspace for outstanding SHA-related invoices  
- Manual recording of insurance settlement / claim references  
- Local outpatient and inpatient SHA tariff assumptions used in billing  
- Role-based access for finance / SHA coordination staff  

### Critical gaps against the DHA / SHA integration checklist

| Required capability | Current status |
|---------------------|----------------|
| Facility authentication to AfyaLink / DHA APIs | **Not implemented** |
| Client Registry verification & biometrics | **Not implemented** |
| Health Worker & Facility Registry checks | **Not implemented** |
| Dynamic Taifa Care tariff / benefit resolution | **Not implemented** (local fixed rates only) |
| FHIR pre-authorisation (`shr-med/bundle`) | **Not implemented** |
| ICD-11 mapped clinical data for claims | **Not implemented** as a structured claims engine |
| Electronic claim submit & live status | **Not implemented** (manual / local “claim” payments only) |
| Shared encounter sync to HIE | **Not implemented** |
| Direct HMIS integration layer (no unofficial middleware) | **Not implemented** |

**Conclusion:** We have a workable **internal billing and claims desk**. We do **not** yet have a **GOK-compliant SHA / DHA HIE integration**. Bridging that gap is the substance of this programme.

---

## 7. Hospital Modules Affected

The integration will cut across clinical, administrative, and financial systems. Impact is classified as **Complete overhaul / major redesign**, **Significant update**, or **New capability**.

### 7.1 Complete overhaul / major redesign

| Module / Function | Why it is heavily affected |
|-------------------|----------------------------|
| **Claims & Insurance Management (Accounts / Finance)** | Must evolve from local “Insurance payment” recording into a full electronic claim lifecycle (draft → pre-auth → submit → status → remittance / rejection handling). |
| **Patient Registration & Coverage (Reception / OPD)** | Must integrate Client Registry verification, eligibility, and storage of national / SHA identifiers before (or at) visit opening. |
| **Tariff & Billing Engine** | Local hardcoded SHA amounts must give way to benefit / package resolution (POMSF / PMF) linked to specialty and intervention codes. |
| **New Integration Layer (ICT)** | New secure microservice client for AfyaLink (auth, retry, logging, audit, UAT vs production configs). This layer does not exist today. |

### 7.2 Significant updates

| Module / Function | Expected change |
|-------------------|-----------------|
| **Inpatient** | Pre-authorisation for admissions / packages; clinician registry linkage; claim closure aligned with discharge. |
| **Maternity** | Package-rate mapping; SHA eligibility at pathway start (not only after-the-fact tagging). |
| **Laboratory & Radiology** | Service coding, eligibility / benefit checks, and claim-supporting result references. |
| **Clinical documentation (Doctors / ICD-11)** | Structured diagnosis coding required for pre-auth and claims. |
| **Human Resources / Practitioner Master** | Link attending clinicians to Health Worker Registry licence / registration numbers. |
| **Facility Master Data / Admin** | Maintain verified MFL / facility scope against Facility Registry. |
| **Users & Roles** | Clearer duties for registration, clinical coding, claims officers, and API credential custodianship. |
| **Management Reports** | Claim aging, approval/rejection rates, and SHA utilisation reporting for Board and finance oversight. |

### 7.3 Major new work where capability is currently thin

| Module / Function | Expected change |
|-------------------|-----------------|
| **Pharmacy / Inventory** | Formulary alignment, covered medicines, and medication claim / shared-record contribution. High impact relative to current SHA coverage in this area. |
| **Shared Encounter Sync** | Controlled export of minimised encounter summaries (treatment, labs, medications) to the HIE. |

### 7.4 Lower near-term impact (unless Board expands scope)

| Area | Note |
|------|------|
| Mortuary | Limited current linkage to SHA claims pathways |
| Pure MoH statistical returns (e.g. programme registers) | Remain separate national reporting streams; must not be confused with SHA claims, but can coexist in the same HMIS |

---

## 8. End-to-End Operational Workflow (Post-Integration)

1. **Authenticate** facility session with DHA / AfyaLink  
2. **Verify patient** via Client Registry (ID / passport / biometrics) and confirm eligibility  
3. **Validate** facility MFL and attending health worker credentials  
4. **Resolve** SHA payable tariffs / packages for planned interventions  
5. Where required, **submit pre-authorisation** (FHIR bundle) and confirm ICD-11 coding  
6. Deliver care within authorised / covered scope  
7. **Submit electronic claim** and monitor **claim status**  
8. **Sync** shared encounter summary to the HIE  
9. Reconcile remittance against local invoices and patient balances  

This replaces fragmented paper claim cycles with a **controlled digital continuum** from reception to reimbursement.

---

## 9. Risks of Delayed or Incomplete Integration

| Risk | Potential impact |
|------|------------------|
| Contracting / scheme exclusion | Loss of SHA patients and revenue |
| Cash-flow disruption | Delayed or rejected reimbursements |
| Operational failure at reception | Inability to verify eligibility at point of care |
| Claim rejection / write-offs | Incomplete coding, missing pre-auth, or mismatched tariffs |
| Regulatory / data protection non-compliance | Improper handling of national health identifiers and shared records |
| Dual systems burden | Staff forced into parallel paper and digital processes |

---

## 10. Strategic Recommendations to the Board

**It is recommended that the Board:**

1. **Note** that SHA / DHA HMIS accreditation and HIE connectivity are **mandatory** for continued SHA participation.  
2. **Endorse** implementation of the **seven core API categories** (approximately **twelve endpoints**) described in Section 5 as the formal technical scope of the programme.  
3. **Authorise** management to:  
   - Complete DHA Developer Portal / AfyaLink registration and sandbox access  
   - Commission a detailed implementation plan, budget, and timeline  
   - Prioritise modules in this order: **(i)** Authentication & Client Registry, **(ii)** Facility / Practitioner registries, **(iii)** Benefits & tariffs, **(iv)** Pre-authorisation & ICD-11, **(v)** Claims submit/status, **(vi)** Shared encounter sync, **(vii)** Pharmacy formulary alignment  
4. **Require** a privacy and Data Protection Act compliance review before production go-live.  
5. **Request** monthly progress reporting to the Board (or delegated ICT / Finance Committee) covering sandbox certification, module readiness, staff training, and production cut-over risks.  
6. **Preserve** the current Insurance Manager as a **local financial reconciliation layer**, while shifting national claim submission onto the SHA clearinghouse APIs—so cash control and SHA compliance are not conflated.

---

## 11. Proposed Decision for the Board

> **RESOLVED**, that the Board notes the mandatory DHA / SHA Health Information Exchange integration requirements for the Hospital Management Information System; approves in principle the implementation of the seven core AfyaLink API categories outlined in this report; and directs Management to present a detailed project plan, resource requirement, and risk register within **[insert timeline, e.g. 30 days]** for final budgetary approval.

---

## 12. Closing Statement

SHA integration is both a **regulatory survival requirement** and an opportunity to professionalise reimbursement, reduce paper friction, and improve continuity of care. With Board sponsorship, phased delivery against the seven API categories, and disciplined change management across reception, clinical, pharmacy, and finance teams, the hospital can meet national obligations while strengthening financial sustainability under Taifa Care / SHA.

---

### Document control

| Prepared by | ______________________________ |
| Reviewed by (ICT / Finance) | ______________________________ |
| Recommended by (CEO / Medical Director) | ______________________________ |
| Board decision | ☐ Approved &nbsp;&nbsp; ☐ Approved with amendments &nbsp;&nbsp; ☐ Deferred |

---

*This briefing is prepared for Board-level decision-making. Endpoint paths are stated as published integration categories under the AfyaLink / DHA HIE architecture and should be confirmed against the facility’s live developer credentials and official API documentation at implementation time.*
