"""
Clinical Decision Support (CDS) — evidence-based interventions.

Assembles patient context from:
  - Problem List (KNHTS / ICD-11)
  - HPT Registry–coded medications & allergens
  - Allergy List
  - Demographics (age, sex)
  - Lab results
  - Vital signs (triage)

Returns structured alerts for chart display and prescribe-time checks.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from django.utils import timezone

from .knhts_conditions import ACTIVE_CLINICAL_STATUSES


SEVERITY_CRITICAL = 'critical'
SEVERITY_HIGH = 'high'
SEVERITY_MODERATE = 'moderate'
SEVERITY_LOW = 'low'
SEVERITY_INFO = 'info'

SOURCE_PROBLEM = 'problem_list'
SOURCE_HPT = 'hpt_registry'
SOURCE_ALLERGY = 'allergy_list'
SOURCE_DEMOGRAPHICS = 'demographics'
SOURCE_LAB = 'lab_results'
SOURCE_VITALS = 'vital_signs'
SOURCE_EVIDENCE = 'evidence_based'


@dataclass
class CdsAlert:
    id: str
    severity: str
    title: str
    message: str
    intervention: str
    sources: list[str] = field(default_factory=list)
    evidence: str = ''
    related_codes: list[str] = field(default_factory=list)
    blocking: bool = False  # hard-stop at prescribe if True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(value) -> float | None:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text_has(*needles: str, haystack: str) -> bool:
    lower = (haystack or '').lower()
    return any(n.lower() in lower for n in needles)


def _problem_blob(problems) -> str:
    parts = []
    for p in problems:
        parts.append(f"{p.icd11_code or ''} {p.display or ''}")
    return ' '.join(parts).lower()


def _allergy_tokens(allergy) -> set[str]:
    tokens = set()
    for raw in (
        allergy.hpt_code,
        allergy.allergen_name,
        allergy.hpt_display,
    ):
        text = (raw or '').strip().lower()
        if not text:
            continue
        tokens.add(text)
        # Split multi-word allergen names for fuzzy contain checks
        for part in re.split(r'[\s,/+\-]+', text):
            if len(part) >= 3:
                tokens.add(part)
    return tokens


def _med_tokens(name='', ge_code='', ge_display='', ph_code='') -> set[str]:
    tokens = set()
    for raw in (name, ge_code, ge_display, ph_code):
        text = (raw or '').strip().lower()
        if text:
            tokens.add(text)
            for part in re.split(r'[\s,/+\-]+', text):
                if len(part) >= 3:
                    tokens.add(part)
    return tokens


def collect_patient_context(patient, *, visit=None) -> dict[str, Any]:
    """Load CDS inputs for a patient (and optional encounter)."""
    from lab.models import LabResult
    from .models import (
        PatientAllergy,
        PatientMedication,
        Problem,
        TriageEntry,
    )

    problems = list(
        Problem.objects.filter(patient=patient)
        .exclude(verification_status='entered-in-error')
        .filter(clinical_status__in=ACTIVE_CLINICAL_STATUSES)
        .select_related('icd11_entry')[:50]
    )
    allergies = list(
        PatientAllergy.objects.filter(patient=patient, clinical_status='active')[:50]
    )
    medications = list(
        PatientMedication.objects.filter(patient=patient, status='active')[:50]
    )

    triage_qs = TriageEntry.objects.filter(visit__patient=patient).order_by('-entry_date')
    if visit:
        visit_triage = TriageEntry.objects.filter(visit=visit).order_by('-entry_date').first()
        latest_triage = visit_triage or triage_qs.first()
    else:
        latest_triage = triage_qs.first()

    labs = list(
        LabResult.objects.filter(patient=patient, status='Completed')
        .select_related('service')
        .prefetch_related('parameters')
        .order_by('-completed_at', '-requested_at')[:25]
    )

    # Active pregnancy (demographics / maternal CDS)
    pregnancy = None
    try:
        from maternity.models import Pregnancy
        pregnancy = (
            Pregnancy.objects.filter(patient=patient, status='Active')
            .order_by('-created_at')
            .first()
        )
    except Exception:  # noqa: BLE001 — maternity app optional at import time
        pregnancy = None

    return {
        'patient': patient,
        'visit': visit,
        'age': getattr(patient, 'age', None),
        'gender': (patient.gender or '').lower(),
        'problems': problems,
        'allergies': allergies,
        'medications': medications,
        'triage': latest_triage,
        'labs': labs,
        'pregnancy': pregnancy,
    }


def evaluate_cds(
    patient,
    *,
    visit=None,
    proposed_medications: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Run evidence-based CDS rules.

    proposed_medications: optional list of dicts with keys
      name, generic_concept_code, generic_concept_display, actual_product_code
    used for prescribe-time allergy / HPT checks.
    """
    ctx = collect_patient_context(patient, visit=visit)
    alerts: list[CdsAlert] = []

    alerts.extend(_rules_demographics(ctx))
    alerts.extend(_rules_vitals(ctx))
    alerts.extend(_rules_labs(ctx))
    alerts.extend(_rules_problems(ctx))
    alerts.extend(_rules_allergy_vs_meds(ctx, proposed_medications or []))
    alerts.extend(_rules_hpt_quality(ctx, proposed_medications or []))
    alerts.extend(_rules_evidence_interventions(ctx))

    # Severity sort
    order = {
        SEVERITY_CRITICAL: 0,
        SEVERITY_HIGH: 1,
        SEVERITY_MODERATE: 2,
        SEVERITY_LOW: 3,
        SEVERITY_INFO: 4,
    }
    alerts.sort(key=lambda a: order.get(a.severity, 9))

    # Dedupe by id
    seen = set()
    unique = []
    for a in alerts:
        if a.id in seen:
            continue
        seen.add(a.id)
        unique.append(a)

    return {
        'success': True,
        'patient_id': patient.pk,
        'visit_id': visit.pk if visit else None,
        'generated_at': timezone.now().isoformat(),
        'inputs_used': {
            'problem_list': len(ctx['problems']),
            'allergy_list': len(ctx['allergies']),
            'hpt_medications': sum(1 for m in ctx['medications'] if m.generic_concept_code),
            'demographics': True,
            'lab_results': len(ctx['labs']),
            'vital_signs': bool(ctx['triage']),
            'proposed_medications': len(proposed_medications or []),
        },
        'summary': {
            'total': len(unique),
            'critical': sum(1 for a in unique if a.severity == SEVERITY_CRITICAL),
            'high': sum(1 for a in unique if a.severity == SEVERITY_HIGH),
            'moderate': sum(1 for a in unique if a.severity == SEVERITY_MODERATE),
            'blocking': sum(1 for a in unique if a.blocking),
        },
        'alerts': [a.to_dict() for a in unique],
    }


def check_medication_against_allergies(
    patient,
    *,
    name='',
    generic_concept_code='',
    generic_concept_display='',
    actual_product_code='',
) -> list[dict[str, Any]]:
    """Prescribe-time allergy check for a single medication candidate."""
    result = evaluate_cds(
        patient,
        proposed_medications=[{
            'name': name,
            'generic_concept_code': generic_concept_code,
            'generic_concept_display': generic_concept_display,
            'actual_product_code': actual_product_code,
        }],
    )
    return [
        a for a in result['alerts']
        if SOURCE_ALLERGY in a.get('sources', []) or a.get('blocking')
    ]


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _rules_demographics(ctx) -> list[CdsAlert]:
    alerts = []
    age = ctx.get('age')
    gender = ctx.get('gender') or ''
    pregnancy = ctx.get('pregnancy')

    if age is not None and age < 5:
        alerts.append(CdsAlert(
            id='demo-pediatric-under5',
            severity=SEVERITY_MODERATE,
            title='Pediatric patient (under 5 years)',
            message=f'Patient is {age} years old. Use pediatric dosing and formulations.',
            intervention='Verify weight-based dosing; prefer pediatric-strength products from HPT registry.',
            sources=[SOURCE_DEMOGRAPHICS, SOURCE_EVIDENCE],
            evidence='WHO / MoH Kenya pediatric formulary — weight-based dosing for under-fives.',
        ))
    elif age is not None and age < 12:
        alerts.append(CdsAlert(
            id='demo-pediatric',
            severity=SEVERITY_LOW,
            title='Pediatric patient',
            message=f'Patient is {age} years old. Confirm age-appropriate dosing.',
            intervention='Cross-check dose against pediatric guidelines before prescribing.',
            sources=[SOURCE_DEMOGRAPHICS, SOURCE_EVIDENCE],
            evidence='Age-adjusted dosing reduces adverse drug events in children.',
        ))

    if age is not None and age >= 65:
        alerts.append(CdsAlert(
            id='demo-geriatric',
            severity=SEVERITY_MODERATE,
            title='Geriatric patient (≥65 years)',
            message='Increased risk of adverse drug reactions and polypharmacy.',
            intervention='Review Beers-type cautions; start low, go slow; check renal function.',
            sources=[SOURCE_DEMOGRAPHICS, SOURCE_EVIDENCE],
            evidence='Older adults have higher ADR risk; adjust for renal clearance.',
        ))

    if pregnancy:
        ga = getattr(pregnancy, 'gestational_age_weeks', None) or ''
        alerts.append(CdsAlert(
            id='demo-pregnancy',
            severity=SEVERITY_HIGH,
            title='Active pregnancy',
            message=f'Active pregnancy on record{f" (GA ~{ga} weeks)" if ga else ""}.',
            intervention='Avoid teratogenic agents; prefer pregnancy-safe alternatives from HPT.',
            sources=[SOURCE_DEMOGRAPHICS, SOURCE_EVIDENCE],
            evidence='MoH Kenya ANC guidelines — medication safety in pregnancy.',
            blocking=False,
        ))
    elif gender in ('female', 'f') and age is not None and 12 <= age <= 49:
        # Soft reminder only — not a diagnosis
        alerts.append(CdsAlert(
            id='demo-childbearing',
            severity=SEVERITY_INFO,
            title='Childbearing-age female',
            message='Consider pregnancy status before prescribing potentially teratogenic medicines.',
            intervention='Ask LMP / pregnancy status when relevant; check maternity record.',
            sources=[SOURCE_DEMOGRAPHICS, SOURCE_EVIDENCE],
            evidence='Reproductive-age females: screen for pregnancy before certain drug classes.',
        ))

    return alerts


def _rules_vitals(ctx) -> list[CdsAlert]:
    alerts = []
    t = ctx.get('triage')
    if not t:
        alerts.append(CdsAlert(
            id='vitals-missing',
            severity=SEVERITY_INFO,
            title='No recent vital signs',
            message='No triage vitals found for decision support.',
            intervention='Record triage vitals (BP, SpO₂, temp, HR, glucose) for safer prescribing.',
            sources=[SOURCE_VITALS],
            evidence='Vital signs are required inputs for many evidence-based CDS rules.',
        ))
        return alerts

    temp = _num(t.temperature)
    sbp = _num(t.blood_pressure_systolic)
    dbp = _num(t.blood_pressure_diastolic)
    hr = _num(t.heart_rate)
    spo2 = _num(t.oxygen_saturation)
    rr = _num(t.respiratory_rate)
    glucose = _num(t.blood_glucose)

    if temp is not None and temp >= 38.0:
        alerts.append(CdsAlert(
            id='vitals-fever',
            severity=SEVERITY_HIGH if temp >= 39.0 else SEVERITY_MODERATE,
            title=f'Fever ({temp}°C)',
            message='Elevated temperature on latest triage.',
            intervention='Evaluate infection (malaria, pneumonia, UTI); consider antipyretic and diagnostics.',
            sources=[SOURCE_VITALS, SOURCE_EVIDENCE],
            evidence='Fever ≥38°C warrants clinical evaluation per Kenyan IMCI / adult protocols.',
        ))

    if spo2 is not None and spo2 < 92:
        alerts.append(CdsAlert(
            id='vitals-hypoxia',
            severity=SEVERITY_CRITICAL,
            title=f'Hypoxemia (SpO₂ {int(spo2)}%)',
            message='Oxygen saturation below 92%.',
            intervention='Start oxygen per protocol; urgent clinical review; consider pneumonia/asthma/COVID pathways.',
            sources=[SOURCE_VITALS, SOURCE_EVIDENCE],
            evidence='SpO₂ <92% is a critical threshold for oxygen therapy in most MoH protocols.',
            blocking=False,
        ))
    elif spo2 is not None and spo2 < 94:
        alerts.append(CdsAlert(
            id='vitals-low-spo2',
            severity=SEVERITY_HIGH,
            title=f'Low SpO₂ ({int(spo2)}%)',
            message='Borderline oxygen saturation.',
            intervention='Reassess airway/breathing; monitor closely; investigate respiratory causes.',
            sources=[SOURCE_VITALS, SOURCE_EVIDENCE],
            evidence='SpO₂ 92–94% requires close monitoring and clinical correlation.',
        ))

    if sbp is not None and dbp is not None:
        if sbp >= 180 or dbp >= 120:
            alerts.append(CdsAlert(
                id='vitals-hypertensive-urgency',
                severity=SEVERITY_CRITICAL,
                title=f'Severe hypertension ({int(sbp)}/{int(dbp)} mmHg)',
                message='BP in severe range on triage.',
                intervention='Urgent assessment for hypertensive emergency; avoid abrupt aggressive outpatient titration without review.',
                sources=[SOURCE_VITALS, SOURCE_EVIDENCE],
                evidence='SBP ≥180 or DBP ≥120 requires urgent evaluation (MoH / AHA thresholds).',
            ))
        elif sbp >= 140 or dbp >= 90:
            alerts.append(CdsAlert(
                id='vitals-hypertension',
                severity=SEVERITY_MODERATE,
                title=f'Elevated BP ({int(sbp)}/{int(dbp)} mmHg)',
                message='Blood pressure above treatment threshold.',
                intervention='Confirm with repeat reading; link to hypertension on Problem List; lifestyle + pharmacotherapy per guideline.',
                sources=[SOURCE_VITALS, SOURCE_EVIDENCE],
                evidence='BP ≥140/90 mmHg defines hypertension for treatment decisions in adults.',
            ))
        if sbp < 90:
            alerts.append(CdsAlert(
                id='vitals-hypotension',
                severity=SEVERITY_CRITICAL,
                title=f'Hypotension (SBP {int(sbp)} mmHg)',
                message='Low systolic blood pressure.',
                intervention='Assess shock; fluid resuscitation pathway; urgent clinician review.',
                sources=[SOURCE_VITALS, SOURCE_EVIDENCE],
                evidence='SBP <90 mmHg is a shock/hypotension red flag.',
            ))

    if hr is not None:
        if hr >= 120:
            alerts.append(CdsAlert(
                id='vitals-tachycardia',
                severity=SEVERITY_HIGH,
                title=f'Tachycardia (HR {int(hr)})',
                message='Heart rate markedly elevated.',
                intervention='Evaluate fever, dehydration, anemia, arrhythmia, pain; treat underlying cause.',
                sources=[SOURCE_VITALS, SOURCE_EVIDENCE],
                evidence='HR ≥120 bpm in adults warrants urgent clinical correlation.',
            ))
        elif hr < 50:
            alerts.append(CdsAlert(
                id='vitals-bradycardia',
                severity=SEVERITY_HIGH,
                title=f'Bradycardia (HR {int(hr)})',
                message='Heart rate low.',
                intervention='Review cardiac meds (beta-blockers); assess perfusion and ECG if available.',
                sources=[SOURCE_VITALS, SOURCE_EVIDENCE, SOURCE_HPT],
                evidence='HR <50 bpm — consider drug effects and conduction disease.',
            ))

    if rr is not None and rr >= 24:
        alerts.append(CdsAlert(
            id='vitals-tachypnea',
            severity=SEVERITY_HIGH,
            title=f'Tachypnea (RR {int(rr)})',
            message='Elevated respiratory rate.',
            intervention='Assess for pneumonia, asthma, metabolic acidosis; check SpO₂.',
            sources=[SOURCE_VITALS, SOURCE_EVIDENCE],
            evidence='RR ≥24 in adults is a severity marker (e.g. CURB / sepsis screens).',
        ))

    if glucose is not None:
        if glucose < 3.9 or glucose < 70:  # support mmol/L or mg/dL heuristically
            # If value looks like mg/dL (>30), use 70; if mmol use 3.9
            is_mgdl = glucose > 30
            hypo = (glucose < 70) if is_mgdl else (glucose < 3.9)
            if hypo:
                alerts.append(CdsAlert(
                    id='vitals-hypoglycemia',
                    severity=SEVERITY_CRITICAL,
                    title=f'Hypoglycemia (glucose {glucose})',
                    message='Low blood glucose on triage.',
                    intervention='Treat hypoglycemia immediately; review insulin/sulfonylurea on Active Medications.',
                    sources=[SOURCE_VITALS, SOURCE_HPT, SOURCE_EVIDENCE],
                    evidence='Prompt glucose treatment prevents neurological injury.',
                ))
        else:
            is_mgdl = glucose > 30
            hyper = (glucose >= 200) if is_mgdl else (glucose >= 11.1)
            if hyper:
                alerts.append(CdsAlert(
                    id='vitals-hyperglycemia',
                    severity=SEVERITY_HIGH,
                    title=f'Hyperglycemia (glucose {glucose})',
                    message='Elevated blood glucose on triage.',
                    intervention='Assess diabetes / DKA risk; update Problem List; adjust antihyperglycemics.',
                    sources=[SOURCE_VITALS, SOURCE_PROBLEM, SOURCE_EVIDENCE],
                    evidence='Random glucose ≥11.1 mmol/L (≈200 mg/dL) suggests diabetes evaluation.',
                ))

    return alerts


def _rules_labs(ctx) -> list[CdsAlert]:
    alerts = []
    labs = ctx.get('labs') or []
    if not labs:
        return alerts

    # Look at recent completed labs (7 days preferred, else latest batch)
    cutoff = timezone.now() - timedelta(days=14)
    recent = [
        lab for lab in labs
        if (lab.completed_at or lab.requested_at) and (lab.completed_at or lab.requested_at) >= cutoff
    ] or labs[:5]

    for lab in recent:
        service_name = (lab.service.name if lab.service_id else '') or ''
        blob = ' '.join([
            service_name,
            lab.results or '',
            lab.interpretation or '',
        ]).lower()
        interp = (lab.interpretation or '').lower()

        # Parameter-level values
        for param in lab.parameters.all() if hasattr(lab, 'parameters') else []:
            pname = (param.name or '').lower()
            pval = _num(param.value)
            if pval is None:
                continue
            if _text_has('haemoglobin', 'hemoglobin', 'hb', haystack=pname):
                # Hb g/dL typically 4–20
                if pval < 7:
                    alerts.append(CdsAlert(
                        id=f'lab-severe-anemia-{lab.pk}',
                        severity=SEVERITY_CRITICAL,
                        title=f'Severe anemia (Hb {pval})',
                        message=f'{service_name}: haemoglobin critically low.',
                        intervention='Urgent review; consider transfusion pathway; investigate cause; caution with NSAIDs.',
                        sources=[SOURCE_LAB, SOURCE_EVIDENCE],
                        evidence='Hb <7 g/dL often triggers transfusion consideration in symptomatic patients.',
                    ))
                elif pval < 10:
                    alerts.append(CdsAlert(
                        id=f'lab-anemia-{lab.pk}',
                        severity=SEVERITY_MODERATE,
                        title=f'Anemia (Hb {pval})',
                        message=f'{service_name}: low haemoglobin.',
                        intervention='Investigate iron deficiency / chronic disease; update Problem List if confirmed.',
                        sources=[SOURCE_LAB, SOURCE_PROBLEM, SOURCE_EVIDENCE],
                        evidence='WHO anemia cut-offs; treat underlying cause.',
                    ))
            if _text_has('creatinine', 'creat', haystack=pname) and pval > 0:
                # µmol/L often >100 elevated; mg/dL >1.2
                elevated = (pval > 1.5 and pval < 30) or pval >= 110
                if elevated:
                    alerts.append(CdsAlert(
                        id=f'lab-creatinine-{lab.pk}',
                        severity=SEVERITY_HIGH,
                        title=f'Elevated creatinine ({pval})',
                        message=f'{service_name}: renal function may be impaired.',
                        intervention='Adjust renally cleared drugs; avoid nephrotoxins (NSAIDs, aminoglycosides) where possible.',
                        sources=[SOURCE_LAB, SOURCE_HPT, SOURCE_EVIDENCE],
                        evidence='Dose-adjust for reduced GFR; nephrotoxin stewardship.',
                    ))
            if _text_has('glucose', 'rbs', 'fbs', 'hba1c', haystack=pname):
                if 'hba1c' in pname and pval >= 7:
                    alerts.append(CdsAlert(
                        id=f'lab-hba1c-{lab.pk}',
                        severity=SEVERITY_MODERATE,
                        title=f'Elevated HbA1c ({pval})',
                        message='Glycemic control above target.',
                        intervention='Intensify diabetes management; ensure diabetes on Problem List.',
                        sources=[SOURCE_LAB, SOURCE_PROBLEM, SOURCE_EVIDENCE],
                        evidence='HbA1c ≥7% generally indicates need to intensify therapy (individualize).',
                    ))

        if _text_has('abnormal', 'positive', 'high', 'low', 'critical', haystack=interp):
            alerts.append(CdsAlert(
                id=f'lab-interp-{lab.pk}',
                severity=SEVERITY_MODERATE,
                title=f'Lab flagged: {service_name or "Result"}',
                message=(lab.interpretation or lab.results or 'Abnormal interpretation recorded')[:240],
                intervention='Review full lab report and correlate with Problem List and vitals.',
                sources=[SOURCE_LAB, SOURCE_EVIDENCE],
                evidence='Clinician-reviewed abnormal labs should drive care plan updates.',
            ))

        if _text_has('malaria', haystack=service_name + ' ' + blob) and _text_has(
            'positive', '+', 'p.f', 'plasmodium', haystack=blob
        ):
            alerts.append(CdsAlert(
                id=f'lab-malaria-{lab.pk}',
                severity=SEVERITY_HIGH,
                title='Malaria test positive',
                message=f'{service_name} indicates malaria.',
                intervention='Start MoH malaria treatment pathway; add malaria to Problem List if not present.',
                sources=[SOURCE_LAB, SOURCE_PROBLEM, SOURCE_EVIDENCE],
                evidence='Kenya National Malaria Guidelines — treat confirmed cases promptly.',
            ))

    return alerts


def _rules_problems(ctx) -> list[CdsAlert]:
    alerts = []
    problems = ctx.get('problems') or []
    blob = _problem_blob(problems)
    triage = ctx.get('triage')
    meds = ctx.get('medications') or []
    med_blob = ' '.join(
        f"{m.display_name} {m.generic_concept_code} {m.generic_concept_display}"
        for m in meds
    ).lower()

    if not problems:
        alerts.append(CdsAlert(
            id='problem-list-empty',
            severity=SEVERITY_INFO,
            title='Problem List empty',
            message='No active problems coded on the Problem List.',
            intervention='Record confirmed diagnoses on the Problem List (ICD-11 / KNHTS) for CDS and continuity.',
            sources=[SOURCE_PROBLEM, SOURCE_EVIDENCE],
            evidence='Problem lists improve continuity and enable condition-specific CDS.',
        ))
        return alerts

    # Hypertension + elevated BP
    if _text_has('hypertens', 'i10', 'ba00', haystack=blob):
        sbp = _num(getattr(triage, 'blood_pressure_systolic', None)) if triage else None
        if sbp and sbp >= 140:
            alerts.append(CdsAlert(
                id='problem-htn-uncontrolled',
                severity=SEVERITY_HIGH,
                title='Hypertension with elevated BP',
                message='Problem List includes hypertension and latest BP is elevated.',
                intervention='Intensify BP management; review adherence and HPT-coded antihypertensives.',
                sources=[SOURCE_PROBLEM, SOURCE_VITALS, SOURCE_HPT, SOURCE_EVIDENCE],
                evidence='Uncontrolled BP on treatment warrants regimen/adherence review.',
                related_codes=[p.icd11_code for p in problems if p.icd11_code][:5],
            ))
        if not _text_has(
            'amlodipine', 'enalapril', 'losartan', 'nifedipine', 'hydrochlorothiazide',
            'atenolol', 'bisoprolol', 'telmisartan', 'captopril',
            haystack=med_blob,
        ):
            alerts.append(CdsAlert(
                id='problem-htn-no-rx',
                severity=SEVERITY_MODERATE,
                title='Hypertension without clear antihypertensive on list',
                message='Hypertension on Problem List but no common antihypertensive detected on Active Medications.',
                intervention='Confirm therapy; prescribe from HPT-mapped antihypertensives if indicated.',
                sources=[SOURCE_PROBLEM, SOURCE_HPT, SOURCE_EVIDENCE],
                evidence='Adults with confirmed HTN generally require pharmacologic therapy when lifestyle alone insufficient.',
            ))

    # Diabetes
    if _text_has('diabet', '5a1', '5a11', '5a10', haystack=blob):
        if not _text_has(
            'metformin', 'insulin', 'glibenclamide', 'gliclazide', 'empagliflozin',
            'sitagliptin', 'glimepiride',
            haystack=med_blob,
        ):
            alerts.append(CdsAlert(
                id='problem-dm-no-rx',
                severity=SEVERITY_MODERATE,
                title='Diabetes without clear antihyperglycemic on list',
                message='Diabetes on Problem List; review Active Medications / HPT codes.',
                intervention='Confirm diabetes therapy; metformin first-line for type 2 when not contraindicated.',
                sources=[SOURCE_PROBLEM, SOURCE_HPT, SOURCE_EVIDENCE],
                evidence='Kenya / WHO diabetes guidance — metformin cornerstone for T2DM if tolerated.',
            ))

    # Asthma / COPD + hypoxia
    if _text_has('asthma', 'copd', 'ca23', 'ca22', haystack=blob):
        spo2 = _num(getattr(triage, 'oxygen_saturation', None)) if triage else None
        if spo2 is not None and spo2 < 94:
            alerts.append(CdsAlert(
                id='problem-asthma-hypoxia',
                severity=SEVERITY_CRITICAL,
                title='Chronic lung disease with low SpO₂',
                message='Respiratory problem on list with reduced oxygen saturation.',
                intervention='Acute exacerbation pathway; bronchodilators / steroids per protocol; oxygen.',
                sources=[SOURCE_PROBLEM, SOURCE_VITALS, SOURCE_EVIDENCE],
                evidence='Low SpO₂ in asthma/COPD indicates severe exacerbation risk.',
            ))

    # HIV — remind cotrimoxazole / ART continuity (soft)
    if _text_has('hiv', '1c62', 'human immunodeficiency', haystack=blob):
        alerts.append(CdsAlert(
            id='problem-hiv',
            severity=SEVERITY_MODERATE,
            title='HIV on Problem List',
            message='Ensure ART continuity and opportunistic infection prophylaxis as indicated.',
            intervention='Confirm ART regimen on Active Medications (HPT-coded); review VL/CD4 labs.',
            sources=[SOURCE_PROBLEM, SOURCE_HPT, SOURCE_LAB, SOURCE_EVIDENCE],
            evidence='Kenya HIV guidelines — uninterrupted ART and OI prophylaxis.',
        ))

    # TB
    if _text_has('tubercul', '1b10', '1b11', '1b12', haystack=blob):
        alerts.append(CdsAlert(
            id='problem-tb',
            severity=SEVERITY_HIGH,
            title='Tuberculosis on Problem List',
            message='TB-related problem coded.',
            intervention='Ensure anti-TB regimen continuity; check drug interactions with Active Medications.',
            sources=[SOURCE_PROBLEM, SOURCE_HPT, SOURCE_EVIDENCE],
            evidence='NTP Kenya — complete TB treatment; watch hepatotoxic / interaction risks.',
        ))

    return alerts


def _rules_allergy_vs_meds(ctx, proposed: list[dict]) -> list[CdsAlert]:
    alerts = []
    allergies = ctx.get('allergies') or []
    medications = ctx.get('medications') or []

    if not allergies:
        alerts.append(CdsAlert(
            id='allergy-list-empty',
            severity=SEVERITY_INFO,
            title='No active allergies recorded',
            message='Allergy List is empty — confirm NKDA vs not documented.',
            intervention='Document allergies (HPT AC*/GE* for drugs) or explicitly record “No known drug allergy”.',
            sources=[SOURCE_ALLERGY, SOURCE_EVIDENCE],
            evidence='Allergy documentation prevents preventable ADRs at prescribe time.',
        ))

    candidates = []
    for m in medications:
        candidates.append({
            'label': m.display_name,
            'tokens': _med_tokens(
                m.display_name,
                m.generic_concept_code,
                m.generic_concept_display,
                m.actual_product_code,
            ),
            'kind': 'active_medication',
        })
    for m in proposed:
        candidates.append({
            'label': m.get('name') or m.get('generic_concept_display') or m.get('generic_concept_code') or 'medication',
            'tokens': _med_tokens(
                m.get('name', ''),
                m.get('generic_concept_code', ''),
                m.get('generic_concept_display', ''),
                m.get('actual_product_code', ''),
            ),
            'kind': 'proposed',
        })

    for allergy in allergies:
        a_tokens = _allergy_tokens(allergy)
        if not a_tokens:
            continue
        for cand in candidates:
            overlap = a_tokens & cand['tokens']
            # Also substring match for multi-word allergens
            fuzzy = False
            if not overlap:
                for at in a_tokens:
                    for ct in cand['tokens']:
                        if len(at) >= 4 and (at in ct or ct in at):
                            fuzzy = True
                            overlap = {at, ct}
                            break
                    if fuzzy:
                        break
            if not overlap and not fuzzy:
                continue

            critical = (allergy.criticality == 'high') or (
                (allergy.severity or '').lower() == 'severe'
            ) or _text_has('anaphylaxis', 'anaphyla', haystack=allergy.reaction or '')
            is_proposed = cand['kind'] == 'proposed'
            alerts.append(CdsAlert(
                id=f"allergy-hit-{allergy.pk}-{abs(hash(cand['label'])) % 10_000}",
                severity=SEVERITY_CRITICAL if critical or is_proposed else SEVERITY_HIGH,
                title='Allergy conflict detected',
                message=(
                    f"Patient allergic to “{allergy.allergen_name}”"
                    f"{f' (HPT {allergy.hpt_code})' if allergy.hpt_code else ''}; "
                    f"conflicts with {cand['kind'].replace('_', ' ')} “{cand['label']}”."
                ),
                intervention=(
                    'Do not prescribe this agent. Choose a non-cross-reactive alternative from the HPT registry.'
                    if is_proposed else
                    'Review Active Medications; stop/substitute conflicting therapy; document rationale.'
                ),
                sources=[SOURCE_ALLERGY, SOURCE_HPT, SOURCE_EVIDENCE],
                evidence='Drug–allergy checking is a core CDS safety control (HPT-coded allergen preferred).',
                related_codes=[c for c in [allergy.hpt_code] if c],
                blocking=bool(is_proposed and (critical or allergy.category == 'medication')),
            ))

    return alerts


def _rules_hpt_quality(ctx, proposed: list[dict]) -> list[CdsAlert]:
    alerts = []
    medications = ctx.get('medications') or []
    uncoded = [m for m in medications if not (m.generic_concept_code or '').strip()]
    if uncoded:
        alerts.append(CdsAlert(
            id='hpt-uncoded-meds',
            severity=SEVERITY_LOW,
            title='Active medications missing HPT codes',
            message=f'{len(uncoded)} active medication(s) lack GE* HPT generic concept codes.',
            intervention='Map medications to DHA HPT registry for eRx, allergy matching, and claims.',
            sources=[SOURCE_HPT, SOURCE_EVIDENCE],
            evidence='HPT coding enables interoperable medication and allergen decision support.',
        ))

    uncoded_proposed = [
        m for m in proposed
        if not (m.get('generic_concept_code') or '').strip() and (m.get('name') or m.get('generic_concept_display'))
    ]
    if uncoded_proposed:
        alerts.append(CdsAlert(
            id='hpt-uncoded-proposed',
            severity=SEVERITY_MODERATE,
            title='Proposed medication not HPT-coded',
            message='One or more drugs being prescribed lack HPT generic concept codes.',
            intervention='Select DHA HPT suggestion (GE*) before saving the prescription.',
            sources=[SOURCE_HPT, SOURCE_EVIDENCE],
            evidence='SHA/DHA eRx and CDS allergy checks rely on HPT concept codes.',
        ))

    return alerts


def _rules_evidence_interventions(ctx) -> list[CdsAlert]:
    """Cross-cutting evidence-based care gaps."""
    alerts = []
    problems = ctx.get('problems') or []
    labs = ctx.get('labs') or []
    triage = ctx.get('triage')
    blob = _problem_blob(problems)
    age = ctx.get('age')

    # Diabetes without recent glucose lab
    if _text_has('diabet', haystack=blob):
        has_glucose_lab = any(
            _text_has('glucose', 'hba1c', 'rbs', 'fbs', 'sugar', haystack=(lab.service.name if lab.service_id else '') + ' ' + (lab.results or ''))
            for lab in labs[:10]
        )
        if not has_glucose_lab:
            alerts.append(CdsAlert(
                id='evidence-dm-monitor',
                severity=SEVERITY_MODERATE,
                title='Diabetes — no recent glucose/HbA1c lab',
                message='Diabetes on Problem List without recent completed glucose-related lab in CDS window.',
                intervention='Order RBS/FBS/HbA1c as appropriate; review glycemic control.',
                sources=[SOURCE_PROBLEM, SOURCE_LAB, SOURCE_EVIDENCE],
                evidence='Regular glycemic monitoring is standard in diabetes care pathways.',
            ))

    # Fever without malaria consideration in endemic context
    temp = _num(getattr(triage, 'temperature', None)) if triage else None
    if temp is not None and temp >= 38.0:
        has_malaria_test = any(
            _text_has('malaria', 'mRDT', 'mrdt', haystack=(lab.service.name if lab.service_id else ''))
            for lab in labs[:10]
        )
        if not has_malaria_test and not _text_has('malaria', haystack=blob):
            alerts.append(CdsAlert(
                id='evidence-fever-malaria',
                severity=SEVERITY_MODERATE,
                title='Fever — consider malaria testing',
                message='Fever present without recent malaria test in available labs.',
                intervention='Order malaria RDT/microscopy per MoH fever algorithm when clinically indicated.',
                sources=[SOURCE_VITALS, SOURCE_LAB, SOURCE_EVIDENCE],
                evidence='Kenya National Malaria Guidelines — test before treat for suspected malaria.',
            ))

    # Elderly + polypharmacy
    if age is not None and age >= 65:
        med_count = len(ctx.get('medications') or [])
        if med_count >= 5:
            alerts.append(CdsAlert(
                id='evidence-polypharmacy',
                severity=SEVERITY_MODERATE,
                title=f'Polypharmacy ({med_count} active medicines)',
                message='Older adult with five or more active medications.',
                intervention='Medication review; deprescribe where possible; check HPT duplicates and interactions clinically.',
                sources=[SOURCE_DEMOGRAPHICS, SOURCE_HPT, SOURCE_EVIDENCE],
                evidence='Polypharmacy (≥5 drugs) increases ADR risk in older adults.',
            ))

    return alerts
