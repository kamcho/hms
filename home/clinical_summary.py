"""
Clinical Summary Generation — human-readable + Kenya HIE (FHIR R4 / KPS-aligned).

Aggregates biodata, clinical information, medications, prescriptions, and care plan
into a printable narrative and an exchangeable FHIR document Bundle (Composition).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone


ICD11_SYSTEM = "http://id.who.int/icd/release/11/mms"
HPT_SYSTEM = "https://ocl.kenya-hie.health/orgs/MOH-PPB/sources/HPT"
ICHI_SYSTEM = "http://id.who.int/icd/release/11/ichi"
CR_PATIENT_SYSTEM = "https://cr.kenya-hie.health/api/v4/Patient"
FR_ORG_SYSTEM = "https://fr.kenya-hie.health/api/v4/Organization"
HWR_SYSTEM = "https://hwr.kenya-hie.health/api/v4/Practitioner"
LOINC = "http://loinc.org"


def _iso(dt) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt.isoformat()
    if isinstance(dt, date):
        return dt.isoformat()
    return str(dt)


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4()}" if prefix else str(uuid.uuid4())


def _facility_meta() -> dict[str, str]:
    return {
        "fr_code": (getattr(settings, "SHA_HIE_FACILITY_FR_CODE", "") or "").strip(),
        "name": (getattr(settings, "SHA_HIE_FACILITY_NAME", "") or "").strip()
        or "Health Facility",
    }


def _narrative_div(text: str) -> dict[str, str]:
    safe = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    paragraphs = "".join(f"<p>{line}</p>" for line in safe.splitlines() if line.strip()) or "<p>—</p>"
    return {"status": "generated", "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{paragraphs}</div>'}


def collect_summary_data(visit, *, care_plan: str = "", author=None) -> dict[str, Any]:
    """Gather all clinical summary sections for a visit."""
    from .knhts_conditions import ACTIVE_CLINICAL_STATUSES
    from .models import (
        ConsultationNotes,
        Diagnosis,
        Impression,
        PatientAllergy,
        PatientMedication,
        Prescription,
        Symptoms,
    )

    patient = visit.patient
    facility = _facility_meta()

    biodata = {
        "full_name": patient.full_name,
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "cr_id": (patient.cr_id or "").strip(),
        "id_type": patient.id_type or "",
        "id_type_display": patient.get_id_type_display() if patient.id_type else "",
        "id_number": patient.id_number or "",
        "gender": patient.gender or "unknown",
        "gender_display": patient.get_gender_display() if patient.gender else "",
        "date_of_birth": _iso(patient.date_of_birth),
        "age": patient.age,
        "phone": patient.phone or "",
        "email": patient.email or "",
        "county": patient.county or "",
        "sub_county": patient.sub_county or "",
        "ward": patient.ward or "",
        "village": patient.village or "",
        "location": patient.location or "",
        "insurance_number": patient.insurance_number or "",
        "postal_address": patient.postal_address or "",
    }

    problems = list(
        patient.problems.exclude(verification_status="entered-in-error")
        .filter(clinical_status__in=ACTIVE_CLINICAL_STATUSES)
        .order_by("-updated_at")[:50]
    )
    diagnoses = list(
        Diagnosis.objects.filter(visit=visit).select_related("icd11_entry").order_by("-created_at")[:30]
    )
    symptoms = list(Symptoms.objects.filter(visit=visit).order_by("-created_at")[:20])
    impressions = list(Impression.objects.filter(visit=visit).order_by("-created_at")[:20])
    notes = list(
        ConsultationNotes.objects.filter(consultation__visit=visit)
        .select_related("created_by")
        .order_by("-created_at")[:30]
    )
    triage = visit.triage_entries.order_by("-entry_date").first()

    clinical = {
        "problems": [
            {
                "display": p.display,
                "icd11_code": p.icd11_code or "",
                "clinical_status": p.clinical_status,
                "severity": p.severity or "",
            }
            for p in problems
        ],
        "diagnoses": [
            {
                "display": d.data or "",
                "icd11_code": getattr(d, "icd11_code", "") or "",
            }
            for d in diagnoses
        ],
        "symptoms": [s.data for s in symptoms if s.data],
        "impressions": [i.data for i in impressions if i.data],
        "notes": [
            {
                "text": n.notes or "",
                "by": (n.created_by.get_full_name() if n.created_by else "") or "",
                "at": _iso(n.created_at),
            }
            for n in notes
            if n.notes
        ],
        "triage": None,
    }
    if triage:
        clinical["triage"] = {
            "priority": triage.priority,
            "category": triage.category,
            "temperature": str(triage.temperature or ""),
            "pulse": str(triage.heart_rate or ""),
            "blood_pressure": triage.get_blood_pressure(),
            "respiratory_rate": str(triage.respiratory_rate or ""),
            "spo2": str(triage.oxygen_saturation or ""),
            "weight": str(triage.weight or ""),
            "notes": triage.triage_notes or "",
        }

    allergies = list(
        PatientAllergy.objects.filter(patient=patient, clinical_status="active")
        .exclude(clinical_status="entered-in-error")
        .order_by("-updated_at")[:40]
    )
    clinical["allergies"] = [
        {
            "allergen_name": a.allergen_name,
            "hpt_code": a.hpt_code or "",
            "severity": a.severity or "",
            "reaction": a.reaction or "",
            "category": a.category,
        }
        for a in allergies
    ]

    active_meds = list(
        PatientMedication.objects.filter(patient=patient, status="active")
        .exclude(status="entered-in-error")
        .order_by("-updated_at")[:50]
    )
    medications = [
        {
            "display_name": m.display_name,
            "generic_concept_code": m.generic_concept_code or "",
            "generic_concept_display": m.generic_concept_display or "",
            "dose_text": m.dose_text or "",
            "frequency": m.frequency or "",
            "route": m.route or "",
            "instructions": m.instructions or "",
            "status": m.status,
            "source": m.source,
        }
        for m in active_meds
    ]

    prescriptions_qs = (
        Prescription.objects.filter(visit=visit)
        .exclude(status="Cancelled")
        .prefetch_related("items__medication")
        .order_by("-prescribed_at")
    )
    prescriptions = []
    for rx in prescriptions_qs:
        items = []
        for item in rx.items.all():
            items.append({
                "name": item.medication.name if item.medication_id else "",
                "generic_concept_code": item.generic_concept_code or "",
                "generic_concept_display": item.generic_concept_display or "",
                "actual_product_code": item.actual_product_code or "",
                "dose_count": str(item.dose_count) if item.dose_count is not None else "",
                "dose_unit": item.dose_unit or "",
                "frequency": item.frequency or "",
                "number_of_days": item.number_of_days,
                "quantity": item.quantity,
                "instructions": item.instructions or "",
                "dispensed": bool(item.dispensed),
            })
        prescriptions.append({
            "id": rx.pk,
            "status": rx.status,
            "diagnosis": rx.diagnosis or "",
            "notes": rx.notes or "",
            "prescribed_at": _iso(rx.prescribed_at),
            "prescribed_by": (
                rx.prescribed_by.get_full_name() if rx.prescribed_by_id else ""
            ),
            "items": items,
        })

    # Labs / procedures from visit invoice — bind LOINC / ICHI when catalogued
    labs: list[dict[str, Any]] = []
    procedures: list[dict[str, Any]] = []
    try:
        from accounts.models import InvoiceItem
        from lab.models import LabResult

        lab_filter = {"patient": patient}
        invoice = getattr(visit, "invoice", None)
        if invoice is not None:
            lab_filter["invoice"] = invoice
        lab_qs = (
            LabResult.objects.filter(**lab_filter)
            .select_related("service")
            .order_by("-requested_at")[:40]
        )
        for lab in lab_qs:
            svc = lab.service
            labs.append({
                "name": svc.name if svc else "",
                "status": lab.status,
                "loinc_code": (getattr(svc, "loinc_code", None) or "") if svc else "",
                "loinc_display": (getattr(svc, "loinc_display", None) or "") if svc else "",
                "results": lab.results or "",
                "requested_at": _iso(lab.requested_at),
            })

        if invoice is not None:
            items = (
                InvoiceItem.objects.filter(invoice=invoice)
                .select_related("service")
                .order_by("created_at")
            )
            for item in items:
                svc = item.service
                if not svc:
                    continue
                if getattr(svc, "ichi_code", None):
                    procedures.append({
                        "name": svc.name,
                        "ichi_code": svc.ichi_code or "",
                        "ichi_display": svc.ichi_display or "",
                        "amount": str(item.amount),
                    })
                elif getattr(svc, "loinc_code", None) and not any(
                    L.get("loinc_code") == svc.loinc_code for L in labs
                ):
                    labs.append({
                        "name": svc.name,
                        "status": "Ordered",
                        "loinc_code": svc.loinc_code or "",
                        "loinc_display": svc.loinc_display or "",
                        "results": "",
                        "requested_at": _iso(item.created_at),
                    })
    except Exception:
        pass

    # Care plan: explicit override → IPD discharge → blank
    care_plan_text = (care_plan or "").strip()
    if not care_plan_text:
        try:
            from inpatient.models import Admission, InpatientDischarge

            adm = Admission.objects.filter(patient=patient, status="Admitted").first()
            if not adm:
                adm = (
                    Admission.objects.filter(patient=patient)
                    .order_by("-admission_date")
                    .first()
                )
            if adm:
                discharge = (
                    InpatientDischarge.objects.filter(admission=adm)
                    .order_by("-id")
                    .first()
                )
                if discharge and discharge.discharge_care_plan:
                    care_plan_text = discharge.discharge_care_plan.strip()
        except Exception:
            pass

    author_name = ""
    author_licence = ""
    if author is not None:
        author_name = author.get_full_name() or getattr(author, "username", "") or ""
        author_licence = getattr(author, "practitioner_licence_number", "") or ""

    return {
        "facility": facility,
        "visit": {
            "id": visit.pk,
            "visit_type": visit.visit_type,
            "visit_mode": visit.visit_mode,
            "visit_date": _iso(visit.visit_date),
            "payment_method": visit.payment_method,
            "is_active": visit.is_active,
        },
        "biodata": biodata,
        "clinical": clinical,
        "medications": medications,
        "prescriptions": prescriptions,
        "labs": labs,
        "procedures": procedures,
        "care_plan": care_plan_text,
        "author": {
            "name": author_name,
            "licence": author_licence,
        },
        "generated_at": _iso(timezone.now()),
    }


def build_human_readable_text(data: dict[str, Any]) -> str:
    """Plain-text human-readable clinical summary."""
    lines: list[str] = []
    fac = data.get("facility") or {}
    bio = data.get("biodata") or {}
    visit = data.get("visit") or {}
    clinical = data.get("clinical") or {}

    lines.append(f"{fac.get('name') or 'Health Facility'}")
    lines.append("CLINICAL SUMMARY (Kenya HIE / KPS-aligned)")
    lines.append("=" * 56)
    lines.append("")
    lines.append("1. BIODATA")
    lines.append(f"  Name: {bio.get('full_name')}")
    lines.append(f"  Sex: {bio.get('gender_display') or bio.get('gender')}")
    lines.append(f"  DOB: {bio.get('date_of_birth')} (Age {bio.get('age')})")
    lines.append(f"  ID: {bio.get('id_type_display')} {bio.get('id_number')}")
    if bio.get("cr_id"):
        lines.append(f"  CR ID: {bio.get('cr_id')}")
    lines.append(f"  Phone: {bio.get('phone') or '—'}")
    loc_bits = [bio.get("village"), bio.get("ward"), bio.get("sub_county"), bio.get("county")]
    lines.append(f"  Residence: {', '.join([b for b in loc_bits if b]) or bio.get('location') or '—'}")
    if bio.get("insurance_number"):
        lines.append(f"  Insurance: {bio.get('insurance_number')}")
    lines.append("")
    lines.append("2. VISIT")
    lines.append(f"  Visit #{visit.get('id')} · {visit.get('visit_type')} · {visit.get('visit_date')}")
    lines.append(f"  Payment: {visit.get('payment_method')}")
    lines.append("")

    lines.append("3. CLINICAL INFORMATION")
    allergies = clinical.get("allergies") or []
    if allergies:
        lines.append("  Allergies:")
        for a in allergies:
            bit = a.get("allergen_name") or ""
            if a.get("hpt_code"):
                bit += f" [{a['hpt_code']}]"
            if a.get("reaction"):
                bit += f" — {a['reaction']}"
            lines.append(f"    - {bit}")
    else:
        lines.append("  Allergies: None recorded")

    if clinical.get("triage"):
        t = clinical["triage"]
        lines.append(
            f"  Triage: {t.get('priority')} / {t.get('category')} "
            f"BP {t.get('blood_pressure') or '—'} HR {t.get('pulse') or '—'} "
            f"Temp {t.get('temperature') or '—'} SpO2 {t.get('spo2') or '—'}"
        )

    for label, key in (("Symptoms", "symptoms"), ("Impressions", "impressions")):
        vals = clinical.get(key) or []
        if vals:
            lines.append(f"  {label}:")
            for v in vals:
                lines.append(f"    - {v}")

    diags = clinical.get("diagnoses") or []
    if diags:
        lines.append("  Diagnoses:")
        for d in diags:
            code = f" ({d['icd11_code']})" if d.get("icd11_code") else ""
            lines.append(f"    - {d.get('display')}{code}")

    probs = clinical.get("problems") or []
    if probs:
        lines.append("  Problem List (active):")
        for p in probs:
            code = f" [{p['icd11_code']}]" if p.get("icd11_code") else ""
            lines.append(f"    - {p.get('display')}{code} ({p.get('clinical_status')})")

    for n in clinical.get("notes") or []:
        lines.append(f"  Note ({n.get('at')} {n.get('by')}): {n.get('text')}")

    lines.append("")
    lines.append("4. MEDICATIONS (Active Medication List)")
    meds = data.get("medications") or []
    if meds:
        for m in meds:
            code = f" [{m['generic_concept_code']}]" if m.get("generic_concept_code") else ""
            dose = " ".join(x for x in [m.get("dose_text"), m.get("frequency"), m.get("route")] if x)
            lines.append(f"  - {m.get('display_name')}{code}{(' — ' + dose) if dose else ''}")
    else:
        lines.append("  None on active list")

    lines.append("")
    lines.append("5. PRESCRIPTIONS (this visit)")
    rxs = data.get("prescriptions") or []
    if rxs:
        for rx in rxs:
            lines.append(
                f"  Rx #{rx.get('id')} ({rx.get('status')}) "
                f"{rx.get('prescribed_at')} by {rx.get('prescribed_by') or '—'}"
            )
            if rx.get("diagnosis"):
                lines.append(f"    Diagnosis: {rx.get('diagnosis')}")
            for it in rx.get("items") or []:
                code = f" [{it['generic_concept_code']}]" if it.get("generic_concept_code") else ""
                lines.append(
                    f"    - {it.get('name')}{code} "
                    f"{it.get('dose_count')} {it.get('dose_unit')} {it.get('frequency')} "
                    f"x{it.get('quantity')} {'(dispensed)' if it.get('dispensed') else ''}"
                )
    else:
        lines.append("  No prescriptions for this visit")

    lines.append("")
    lines.append("6. LABORATORY (LOINC)")
    labs = data.get("labs") or []
    if labs:
        for lab in labs:
            code = f" [LOINC {lab['loinc_code']}]" if lab.get("loinc_code") else ""
            lines.append(f"  - {lab.get('name')}{code} ({lab.get('status')})")
            if lab.get("results"):
                lines.append(f"    Result: {lab.get('results')}")
    else:
        lines.append("  None recorded")

    lines.append("")
    lines.append("7. PROCEDURES (ICHI)")
    procs = data.get("procedures") or []
    if procs:
        for proc in procs:
            code = f" [ICHI {proc['ichi_code']}]" if proc.get("ichi_code") else ""
            lines.append(f"  - {proc.get('name')}{code}")
    else:
        lines.append("  None recorded")

    lines.append("")
    lines.append("8. CARE PLAN")
    plan = (data.get("care_plan") or "").strip()
    lines.append(f"  {plan if plan else 'Not documented'}")
    lines.append("")
    author = data.get("author") or {}
    lines.append(f"Generated: {data.get('generated_at')}")
    if author.get("name"):
        lines.append(f"Author: {author.get('name')}" + (f" (Licence {author['licence']})" if author.get("licence") else ""))
    return "\n".join(lines)


def build_fhir_document_bundle(data: dict[str, Any], *, summary_id: str | None = None) -> dict[str, Any]:
    """
    Build a FHIR R4 document Bundle with Composition (Kenya Patient Summary / OP IG aligned).

    Sections: biodata (Patient), clinical (Condition/Allergy/Observation narrative),
    medications (MedicationStatement), prescriptions (MedicationRequest), care plan (CarePlan).
    """
    bio = data.get("biodata") or {}
    visit = data.get("visit") or {}
    clinical = data.get("clinical") or {}
    facility = data.get("facility") or {}
    author = data.get("author") or {}

    doc_id = summary_id or _uid()
    patient_id = f"Patient-{bio.get('cr_id') or bio.get('id_number') or 'local'}"
    encounter_id = f"Encounter-{visit.get('id')}"
    composition_id = f"Composition-{doc_id}"
    careplan_id = f"CarePlan-{doc_id}"

    cr_id = bio.get("cr_id") or ""
    patient_ref = f"Patient/{patient_id}"
    if cr_id:
        patient_subject = {
            "reference": f"{CR_PATIENT_SYSTEM}/{cr_id}",
            "identifier": {"system": CR_PATIENT_SYSTEM, "value": cr_id},
            "display": bio.get("full_name") or "",
        }
    else:
        patient_subject = {"reference": patient_ref, "display": bio.get("full_name") or ""}

    fr_code = facility.get("fr_code") or ""
    org_ref = {
        "display": facility.get("name") or "Health Facility",
    }
    if fr_code:
        org_ref["reference"] = f"{FR_ORG_SYSTEM}/{fr_code}"
        org_ref["identifier"] = {"system": FR_ORG_SYSTEM, "value": fr_code}

    gender_map = {
        "male": "male",
        "female": "female",
        "other": "other",
        "unknown": "unknown",
    }
    patient_resource = {
        "resourceType": "Patient",
        "id": patient_id,
        "identifier": [],
        "name": [{"use": "official", "family": bio.get("last_name") or "", "given": [bio.get("first_name") or ""]}],
        "gender": gender_map.get((bio.get("gender") or "unknown").lower(), "unknown"),
        "birthDate": bio.get("date_of_birth") or None,
        "telecom": [],
        "address": [{
            "use": "home",
            "country": "KE",
            "district": bio.get("county") or "",
            "city": bio.get("sub_county") or "",
            "line": [x for x in [bio.get("postal_address"), bio.get("village"), bio.get("ward")] if x],
            "text": bio.get("location") or "",
        }],
    }
    if cr_id:
        patient_resource["identifier"].append({"system": CR_PATIENT_SYSTEM, "value": cr_id})
    if bio.get("id_number"):
        patient_resource["identifier"].append({
            "type": {"text": bio.get("id_type") or "NATIONAL_ID"},
            "value": bio.get("id_number"),
        })
    if bio.get("phone"):
        patient_resource["telecom"].append({"system": "phone", "value": bio["phone"]})
    if bio.get("email"):
        patient_resource["telecom"].append({"system": "email", "value": bio["email"]})

    enc_class = "IMP" if (visit.get("visit_type") or "").upper().startswith("IN") else "AMB"
    encounter_resource = {
        "resourceType": "Encounter",
        "id": encounter_id,
        "status": "finished" if not visit.get("is_active") else "in-progress",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": enc_class,
            "display": "inpatient encounter" if enc_class == "IMP" else "ambulatory",
        },
        "subject": patient_subject,
        "period": {"start": visit.get("visit_date")},
        "serviceProvider": org_ref,
    }

    entries: list[dict[str, Any]] = []
    section_refs: list[dict[str, Any]] = []

    def add_resource(resource: dict[str, Any]) -> str:
        rid = resource["id"]
        rtype = resource["resourceType"]
        entries.append({
            "fullUrl": f"urn:uuid:{rid}",
            "resource": resource,
            "request": {"method": "POST", "url": rtype},
        })
        return f"{rtype}/{rid}"

    add_resource(patient_resource)
    add_resource(encounter_resource)

    # Conditions from diagnoses + problems
    for idx, d in enumerate(clinical.get("diagnoses") or []):
        cid = f"Condition-dx-{visit.get('id')}-{idx}"
        coding = []
        if d.get("icd11_code"):
            coding.append({"system": ICD11_SYSTEM, "code": d["icd11_code"], "display": d.get("display") or ""})
        cond = {
            "resourceType": "Condition",
            "id": cid,
            "clinicalStatus": {
                "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]
            },
            "code": {
                "coding": coding,
                "text": d.get("display") or "",
            },
            "subject": patient_subject,
            "encounter": {"reference": f"Encounter/{encounter_id}"},
        }
        ref = add_resource(cond)
        section_refs.append({"reference": ref, "display": d.get("display") or ""})

    for idx, p in enumerate(clinical.get("problems") or []):
        cid = f"Condition-pl-{visit.get('id')}-{idx}"
        coding = []
        if p.get("icd11_code"):
            coding.append({"system": ICD11_SYSTEM, "code": p["icd11_code"], "display": p.get("display") or ""})
        cond = {
            "resourceType": "Condition",
            "id": cid,
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": (p.get("clinical_status") or "active").split("-")[0] if p.get("clinical_status") else "active",
                }]
            },
            "category": [{
                "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "problem-list-item"}]
            }],
            "code": {"coding": coding, "text": p.get("display") or ""},
            "subject": patient_subject,
        }
        ref = add_resource(cond)
        section_refs.append({"reference": ref, "display": p.get("display") or ""})

    allergy_refs = []
    for idx, a in enumerate(clinical.get("allergies") or []):
        aid = f"Allergy-{visit.get('id')}-{idx}"
        coding = []
        if a.get("hpt_code"):
            coding.append({"system": HPT_SYSTEM, "code": a["hpt_code"], "display": a.get("allergen_name") or ""})
        allergy = {
            "resourceType": "AllergyIntolerance",
            "id": aid,
            "clinicalStatus": {
                "coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]
            },
            "type": "allergy",
            "category": [a.get("category") or "medication"],
            "code": {"coding": coding, "text": a.get("allergen_name") or ""},
            "patient": patient_subject,
            "reaction": [{"manifestation": [{"text": a.get("reaction") or "Unknown"}]}] if a.get("reaction") else [],
        }
        if a.get("severity"):
            allergy["criticality"] = "high" if a["severity"] == "severe" else "low"
        ref = add_resource(allergy)
        allergy_refs.append({"reference": ref, "display": a.get("allergen_name") or ""})

    med_refs = []
    for idx, m in enumerate(data.get("medications") or []):
        mid = f"MedStatement-{visit.get('id')}-{idx}"
        coding = []
        if m.get("generic_concept_code"):
            coding.append({
                "system": HPT_SYSTEM,
                "code": m["generic_concept_code"],
                "display": m.get("generic_concept_display") or m.get("display_name") or "",
            })
        stmt = {
            "resourceType": "MedicationStatement",
            "id": mid,
            "status": "active",
            "medicationCodeableConcept": {
                "coding": coding,
                "text": m.get("display_name") or "",
            },
            "subject": patient_subject,
            "dosage": [{
                "text": " ".join(
                    x for x in [m.get("dose_text"), m.get("frequency"), m.get("route"), m.get("instructions")] if x
                ),
            }],
        }
        ref = add_resource(stmt)
        med_refs.append({"reference": ref, "display": m.get("display_name") or ""})

    rx_refs = []
    for rx in data.get("prescriptions") or []:
        for idx, it in enumerate(rx.get("items") or []):
            rid = f"MedRequest-{rx.get('id')}-{idx}"
            coding = []
            if it.get("generic_concept_code"):
                coding.append({
                    "system": HPT_SYSTEM,
                    "code": it["generic_concept_code"],
                    "display": it.get("generic_concept_display") or it.get("name") or "",
                })
            req = {
                "resourceType": "MedicationRequest",
                "id": rid,
                "status": "completed" if it.get("dispensed") else "active",
                "intent": "order",
                "medicationCodeableConcept": {
                    "coding": coding,
                    "text": it.get("name") or "",
                },
                "subject": patient_subject,
                "encounter": {"reference": f"Encounter/{encounter_id}"},
                "authoredOn": (rx.get("prescribed_at") or "")[:10] or None,
                "dosageInstruction": [{
                    "text": " ".join(
                        x for x in [
                            f"{it.get('dose_count')} {it.get('dose_unit')}".strip(),
                            it.get("frequency"),
                            it.get("instructions"),
                        ] if x
                    ),
                    "patientInstruction": it.get("instructions") or "",
                }],
                "dispenseRequest": {
                    "quantity": {"value": it.get("quantity") or 0},
                },
            }
            ref = add_resource(req)
            rx_refs.append({"reference": ref, "display": it.get("name") or ""})

    lab_refs = []
    for idx, lab in enumerate(data.get("labs") or []):
        oid = f"Obs-lab-{visit.get('id')}-{idx}"
        coding = []
        if lab.get("loinc_code"):
            coding.append({
                "system": LOINC,
                "code": lab["loinc_code"],
                "display": lab.get("loinc_display") or lab.get("name") or "",
            })
        obs = {
            "resourceType": "Observation",
            "id": oid,
            "status": "final" if (lab.get("status") or "").lower() == "completed" else "registered",
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "laboratory",
                }]
            }],
            "code": {
                "coding": coding,
                "text": lab.get("loinc_display") or lab.get("name") or "",
            },
            "subject": patient_subject,
            "encounter": {"reference": f"Encounter/{encounter_id}"},
        }
        if lab.get("results"):
            obs["valueString"] = lab["results"]
        if lab.get("requested_at"):
            obs["effectiveDateTime"] = lab["requested_at"]
        ref = add_resource(obs)
        lab_refs.append({"reference": ref, "display": lab.get("name") or ""})

    proc_refs = []
    for idx, proc in enumerate(data.get("procedures") or []):
        pid = f"Procedure-{visit.get('id')}-{idx}"
        coding = []
        if proc.get("ichi_code"):
            coding.append({
                "system": ICHI_SYSTEM,
                "code": proc["ichi_code"],
                "display": proc.get("ichi_display") or proc.get("name") or "",
            })
        procedure = {
            "resourceType": "Procedure",
            "id": pid,
            "status": "completed",
            "code": {
                "coding": coding,
                "text": proc.get("ichi_display") or proc.get("name") or "",
            },
            "subject": patient_subject,
            "encounter": {"reference": f"Encounter/{encounter_id}"},
        }
        ref = add_resource(procedure)
        proc_refs.append({"reference": ref, "display": proc.get("name") or ""})

    care_text = (data.get("care_plan") or "").strip() or "Care plan not documented."
    careplan = {
        "resourceType": "CarePlan",
        "id": careplan_id,
        "status": "active",
        "intent": "plan",
        "title": "Encounter care plan",
        "description": care_text,
        "subject": patient_subject,
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "activity": [{
            "detail": {
                "status": "scheduled",
                "description": care_text,
            }
        }],
    }
    care_ref = add_resource(careplan)

    # Narrative section texts
    clinical_narrative = build_human_readable_text(data)
    biodata_text = "\n".join([
        f"Name: {bio.get('full_name')}",
        f"Sex: {bio.get('gender')}",
        f"DOB: {bio.get('date_of_birth')}",
        f"ID: {bio.get('id_number')}",
        f"CR: {bio.get('cr_id')}",
    ])
    meds_text = "\n".join(
        f"- {m.get('display_name')} [{m.get('generic_concept_code') or ''}]"
        for m in (data.get("medications") or [])
    ) or "None"
    rx_text = "\n".join(
        f"- {it.get('name')} [{it.get('generic_concept_code') or ''}]"
        for rx in (data.get("prescriptions") or [])
        for it in (rx.get("items") or [])
    ) or "None"

    composition = {
        "resourceType": "Composition",
        "id": composition_id,
        "status": "final",
        "type": {
            "coding": [{"system": LOINC, "code": "60591-5", "display": "Patient summary Document"}],
            "text": "Clinical Summary",
        },
        "category": [{
            "coding": [{"system": LOINC, "code": "11488-4", "display": "Consult note"}]
        }],
        "subject": patient_subject,
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "date": data.get("generated_at") or _iso(timezone.now()),
        "author": [{
            "display": author.get("name") or facility.get("name") or "Clinician",
        }],
        "title": f"Clinical Summary — Visit {visit.get('id')} — {bio.get('full_name')}",
        "custodian": org_ref,
        "section": [
            {
                "title": "Biodata",
                "code": {"coding": [{"system": LOINC, "code": "11369-6", "display": "History of Immunization Narrative"}], "text": "Patient biodata"},
                "text": _narrative_div(biodata_text),
                "entry": [{"reference": patient_ref}],
            },
            {
                "title": "Clinical Information",
                "code": {"coding": [{"system": LOINC, "code": "11535-2", "display": "Hospital discharge Dx"}], "text": "Clinical information"},
                "text": _narrative_div("\n".join([
                    "Diagnoses/problems and notes — see entries.",
                    *[f"Dx: {d.get('display')}" for d in (clinical.get("diagnoses") or [])],
                    *[f"Problem: {p.get('display')}" for p in (clinical.get("problems") or [])],
                ]) or clinical_narrative),
                "entry": section_refs + allergy_refs,
            },
            {
                "title": "Medications",
                "code": {"coding": [{"system": LOINC, "code": "10160-0", "display": "History of Medication use Narrative"}]},
                "text": _narrative_div(meds_text),
                "entry": med_refs,
            },
            {
                "title": "Prescriptions",
                "code": {"coding": [{"system": LOINC, "code": "57828-6", "display": "Prescription list"}]},
                "text": _narrative_div(rx_text),
                "entry": rx_refs,
            },
            {
                "title": "Laboratory",
                "code": {"coding": [{"system": LOINC, "code": "26436-6", "display": "Laboratory studies"}]},
                "text": _narrative_div(
                    "\n".join(
                        f"- {L.get('name')} [LOINC {L.get('loinc_code') or '—'}] ({L.get('status')})"
                        for L in (data.get("labs") or [])
                    ) or "None"
                ),
                "entry": lab_refs,
            },
            {
                "title": "Procedures",
                "code": {"coding": [{"system": LOINC, "code": "47519-4", "display": "History of Procedures Document"}]},
                "text": _narrative_div(
                    "\n".join(
                        f"- {P.get('name')} [ICHI {P.get('ichi_code') or '—'}]"
                        for P in (data.get("procedures") or [])
                    ) or "None"
                ),
                "entry": proc_refs,
            },
            {
                "title": "Care Plan",
                "code": {"coding": [{"system": LOINC, "code": "18776-5", "display": "Plan of care note"}]},
                "text": _narrative_div(care_text),
                "entry": [{"reference": care_ref}],
            },
        ],
    }
    if author.get("licence"):
        composition["author"][0]["identifier"] = {
            "system": HWR_SYSTEM,
            "value": author["licence"],
        }

    # Composition first in document bundle
    entries.insert(0, {
        "fullUrl": f"urn:uuid:{composition_id}",
        "resource": composition,
        "request": {"method": "POST", "url": "Composition"},
    })

    return {
        "resourceType": "Bundle",
        "id": f"Bundle-{doc_id}",
        "type": "document",
        "timestamp": data.get("generated_at") or _iso(timezone.now()),
        "identifier": {
            "system": f"urn:facility:{(facility.get('fr_code') or 'local')}",
            "value": f"clinical-summary-{doc_id}",
        },
        "entry": entries,
    }


def build_encounter_sync_payload(data: dict[str, Any], fhir_bundle: dict[str, Any]) -> dict[str, Any]:
    """Minimised shared-encounter payload for POST /api/v1/encounter/sync (board path)."""
    bio = data.get("biodata") or {}
    visit = data.get("visit") or {}
    clinical = data.get("clinical") or {}
    facility = data.get("facility") or {}
    return {
        "cr_id": bio.get("cr_id") or "",
        "patient_id_number": bio.get("id_number") or "",
        "facility_fr_code": facility.get("fr_code") or "",
        "visit_id": visit.get("id"),
        "visit_type": visit.get("visit_type"),
        "visit_date": visit.get("visit_date"),
        "diagnoses": clinical.get("diagnoses") or [],
        "problems": clinical.get("problems") or [],
        "allergies": clinical.get("allergies") or [],
        "medications": data.get("medications") or [],
        "prescriptions": data.get("prescriptions") or [],
        "labs": data.get("labs") or [],
        "procedures": data.get("procedures") or [],
        "care_plan": data.get("care_plan") or "",
        "treatment_notes": [
            n.get("text") for n in (clinical.get("notes") or []) if n.get("text")
        ],
        "fhir_bundle_id": fhir_bundle.get("id"),
        "fhir_bundle": fhir_bundle,
    }


@transaction.atomic
def generate_clinical_summary(visit, *, care_plan: str = "", author=None, persist: bool = True):
    """
    Generate (and optionally persist) a ClinicalSummary for the visit.
    Returns ClinicalSummary instance when persist=True, else dict with data/text/fhir.
    """
    from .models import ClinicalSummary

    data = collect_summary_data(visit, care_plan=care_plan, author=author)
    # Prefer care_plan arg over auto-filled when regenerating with explicit text
    if care_plan is not None and str(care_plan).strip():
        data["care_plan"] = str(care_plan).strip()

    narrative = build_human_readable_text(data)
    summary_uuid = str(uuid.uuid4())
    fhir = build_fhir_document_bundle(data, summary_id=summary_uuid)
    sync_payload = build_encounter_sync_payload(data, fhir)

    if not persist:
        return {
            "data": data,
            "narrative_text": narrative,
            "fhir_bundle": fhir,
            "sync_payload": sync_payload,
        }

    existing = (
        ClinicalSummary.objects.filter(visit=visit, status="draft")
        .order_by("-generated_at")
        .first()
    )
    if existing:
        summary = existing
    else:
        summary = ClinicalSummary(visit=visit, patient=visit.patient)

    summary.patient = visit.patient
    summary.care_plan = data.get("care_plan") or ""
    summary.narrative_text = narrative
    summary.summary_json = data
    summary.fhir_bundle = fhir
    summary.sync_payload = sync_payload
    summary.status = "generated"
    summary.hie_sync_status = "pending"
    summary.generated_by = author
    summary.generated_at = timezone.now()
    summary.includes_biodata = True
    summary.includes_clinical = True
    summary.includes_medications = bool(data.get("medications"))
    summary.includes_prescriptions = bool(data.get("prescriptions"))
    summary.includes_care_plan = bool((data.get("care_plan") or "").strip())
    summary.save()
    return summary


def sync_clinical_summary_to_hie(summary) -> dict[str, Any]:
    """Submit FHIR clinical document + shared encounter sync to Kenya HIE."""
    from accounts.sha_hie_service import ShaHieClient, ShaHieError

    client = ShaHieClient()
    result: dict[str, Any] = {"fhir": None, "encounter_sync": None, "errors": []}

    try:
        fhir_resp = client.submit_clinical_fhir_bundle(summary.fhir_bundle or {})
        result["fhir"] = fhir_resp
        summary.hie_document_id = str(
            (fhir_resp or {}).get("id")
            or (fhir_resp or {}).get("document_id")
            or (fhir_resp or {}).get("bundle_id")
            or ""
        )[:128]
    except ShaHieError as exc:
        result["errors"].append(f"FHIR bundle: {exc}")
    except Exception as exc:
        result["errors"].append(f"FHIR bundle: {exc}")

    try:
        sync_resp = client.sync_shared_encounter(summary.sync_payload or {})
        result["encounter_sync"] = sync_resp
    except ShaHieError as exc:
        result["errors"].append(f"Encounter sync: {exc}")
    except Exception as exc:
        result["errors"].append(f"Encounter sync: {exc}")

    summary.hie_sync_raw = result
    if result["errors"] and not (result["fhir"] or result["encounter_sync"]):
        summary.hie_sync_status = "error"
        summary.last_error = "; ".join(result["errors"])[:2000]
        summary.status = "error"
    elif result["errors"]:
        summary.hie_sync_status = "partial"
        summary.last_error = "; ".join(result["errors"])[:2000]
        summary.status = "synced"
        summary.synced_at = timezone.now()
    else:
        summary.hie_sync_status = "synced"
        summary.last_error = ""
        summary.status = "synced"
        summary.synced_at = timezone.now()
    summary.save(update_fields=[
        "hie_sync_status", "hie_sync_raw", "hie_document_id", "last_error",
        "status", "synced_at", "updated_at",
    ])
    return result
