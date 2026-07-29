"""Orchestrate DHA eClaims / eRx workflow against a local Visit."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import Invoice, ShaClaimSession
from accounts.sha_hie_service import ShaHieClient, ShaHieError
from home.models import Prescription, PrescriptionItem, Visit


FREQ_TO_PER_DAY = {
    'Once Daily': 1,
    'Twice Daily': 2,
    'Thrice Daily': 3,
    'Four Times Daily': 4,
    'Every 6 Hours': 4,
    'Every 8 Hours': 3,
    'Every 12 Hours': 2,
    'Every 24 Hours': 1,
    'As Needed': 1,
}


def _default_intervention(visit: Visit) -> str:
    if visit.visit_type == 'IN-PATIENT':
        return getattr(settings, 'SHA_HIE_DEFAULT_INTERVENTION_IPD', 'SHA-11-001')
    return getattr(settings, 'SHA_HIE_DEFAULT_INTERVENTION_OPD', 'SHA-18-005')


def _service_type(visit: Visit) -> str:
    if visit.visit_type == 'IN-PATIENT':
        return 'INPATIENT'
    return 'OUTPATIENT'


def get_or_create_claim_session(visit: Visit, user=None) -> ShaClaimSession:
    session, created = ShaClaimSession.objects.get_or_create(
        visit=visit,
        defaults={
            'service_type': _service_type(visit),
            'intervention_codes': [_default_intervention(visit)],
            'patient_cr_id': (visit.patient.cr_id or '').strip(),
            'patient_id_number': (visit.patient.id_number or '').strip(),
            'created_by': user,
        },
    )
    if not created and user and not session.created_by_id:
        session.created_by = user
        session.save(update_fields=['created_by'])
    return session


def refresh_eligibility(session: ShaClaimSession) -> ShaClaimSession:
    client = ShaHieClient()
    id_number = session.patient_id_number or (session.visit.patient.id_number or '')
    if not id_number:
        raise ValueError('Patient national ID is required for eligibility.')
    result = client.get_patient_by_id_number(id_number)
    session.eligibility_raw = result.raw if isinstance(result.raw, dict) else {'value': result.raw}
    session.eligible = bool(result.found)
    # Prefer CR id from eligibility / patient
    cr = session.visit.patient.cr_id or ''
    raw = session.eligibility_raw
    for key in ('cr_id', 'patient_id', 'clientRegistryId', 'beneficiary_id'):
        if isinstance(raw, dict) and raw.get(key):
            cr = str(raw.get(key))
            break
    # Nested common shapes
    if isinstance(raw, dict):
        for nest in ('patient', 'data', 'beneficiary', 'result'):
            node = raw.get(nest)
            if isinstance(node, dict):
                for key in ('cr_id', 'id', 'patient_id', 'clientRegistryId'):
                    if node.get(key):
                        cr = str(node.get(key))
                        break
    session.patient_cr_id = (cr or session.patient_cr_id or '').strip()
    session.status = 'eligible' if session.eligible else 'error'
    if not session.eligible:
        session.last_error = 'Patient not found / not eligible on SHA eligibility API.'
    else:
        session.last_error = ''
    session.save()
    return session


def start_visit_with_otp(
    session: ShaClaimSession,
    *,
    otp: str,
    practitioner: Any = None,
) -> ShaClaimSession:
    patient_id = (session.patient_cr_id or '').strip()
    if not patient_id:
        raise ValueError('Client Registry ID (cr_id) is required to start a SHA visit.')
    codes = session.intervention_codes or [_default_intervention(session.visit)]
    id_type = session.practitioner_identification_type or 'registration_number'
    id_number = session.practitioner_identification_number
    reg_body = session.practitioner_regulation_body or 'KMPDC'
    if practitioner is not None:
        id_type = getattr(practitioner, 'practitioner_identification_type', None) or id_type
        id_number = getattr(practitioner, 'practitioner_licence_number', None) or id_number
        reg_body = getattr(practitioner, 'practitioner_regulation_body', None) or reg_body
        # Fallback: national ID of user
        if not id_number:
            id_number = getattr(practitioner, 'id_number', '') or ''
            id_type = 'National ID'

    client = ShaHieClient()
    try:
        raw = client.create_virtual_claim(
            patient_id=patient_id,
            service_type=session.service_type or _service_type(session.visit),
            intervention_codes=codes,
            otp=otp,
            practitioner_identification_type=id_type or None,
            practitioner_identification_number=id_number or None,
            practitioner_regulation_body=reg_body or None,
        )
    except ShaHieError as exc:
        session.status = 'error'
        session.last_error = str(exc)
        session.save(update_fields=['status', 'last_error', 'updated_at'])
        raise

    session.consent_token = str(
        raw.get('authorization_code') or raw.get('consent_token') or session.consent_token or ''
    )
    session.authorization_guid = str(raw.get('authorization_guid') or '')
    session.claim_id = str(raw.get('claim_id') or raw.get('id') or '')
    session.edi_claim_guid = str(raw.get('edi_claim_guid') or '')
    session.workflow_state = str(raw.get('workflow_state') or '')
    session.practitioner_identification_type = id_type or ''
    session.practitioner_identification_number = id_number or ''
    session.practitioner_regulation_body = reg_body or ''
    session.submit_raw = {'start_visit': raw}
    session.status = 'started'
    session.last_error = ''
    session.save()
    return session


def build_erx_items(visit: Visit) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    qs = PrescriptionItem.objects.filter(
        prescription__visit=visit,
    ).select_related('medication', 'medication__medication', 'prescription')
    today = timezone.localdate()
    for row in qs:
        code = (row.generic_concept_code or '').strip()
        if not code and getattr(row.medication, 'medication', None):
            code = (row.medication.medication.generic_concept_code or '').strip()
        if not code:
            continue
        days = int(row.number_of_days or 5)
        freq = FREQ_TO_PER_DAY.get(row.frequency, 1)
        end = today + timedelta(days=max(days - 1, 0))
        instruction = (row.instructions or '')[:500]
        # Prefixed ICD reasons from Rx diagnosis / problem snapshot when present
        rx = row.prescription
        reasons = []
        if rx and rx.icd11_code:
            reasons.append(rx.icd11_code)
        for p in (rx.problem_list_snapshot or [])[:3] if rx else []:
            if p.get('icd11_code'):
                reasons.append(p['icd11_code'])
        if reasons and instruction:
            instruction = f"[{', '.join(dict.fromkeys(reasons))}] {instruction}"
        elif reasons:
            instruction = f"Indication: {', '.join(dict.fromkeys(reasons))}"
        items.append({
            'generic_concept_code': code,
            'dose_quantity': float(row.dose_count or 1),
            'dose_unit': (row.dose_unit or row.medication.dispensing_unit or 'tablet'),
            'duration': days,
            'duration_unit': 'day',
            'frequency': freq,
            'period_unit': 'day',
            'start_date': today.isoformat(),
            'end_date': end.isoformat(),
            'patient_instruction': instruction[:500],
            'needs_refill': False,
            'refill_count': 0,
        })
    return items


def build_erx_transmission_package(visit: Visit) -> dict[str, Any]:
    """
    Full electronic prescribing package: drug items (API) + clinical context
    (problem list, medication list, diagnostic tests) for audit / SHR sync.
    """
    from home.electronic_prescribing import build_erx_clinical_context

    items = build_erx_items(visit)
    # Prefer latest prescription snapshot when available
    rx = (
        Prescription.objects.filter(visit=visit)
        .exclude(status='Cancelled')
        .order_by('-prescribed_at')
        .first()
    )
    if rx and rx.erx_clinical_context:
        context = rx.erx_clinical_context
    else:
        context = build_erx_clinical_context(visit, include_medication_list=True)

    return {
        'items': items,
        'clinical_context': context,
        'includes': {
            'can_create_prescriptions': bool(items),
            'electronic_transmission': True,
            'diagnostic_tests': bool((context or {}).get('diagnostic_tests')),
            'problem_list': bool((context or {}).get('problem_list')),
            'medication_lists': bool((context or {}).get('medication_list')),
        },
    }


def submit_erx_for_visit(session: ShaClaimSession, *, practitioner: Any = None) -> ShaClaimSession:
    if not session.consent_token:
        raise ValueError('Start the SHA visit first (consent_token missing).')
    package = build_erx_transmission_package(session.visit)
    items = package['items']
    if not items:
        raise ValueError(
            'No prescription lines with DHA generic_concept_code (GE*). '
            'Map medications before eRx submit.'
        )
    intervention = (session.intervention_codes or [_default_intervention(session.visit)])[0]
    id_type = session.practitioner_identification_type or 'registration_number'
    id_number = session.practitioner_identification_number
    reg_body = session.practitioner_regulation_body or 'KMPDC'
    if practitioner is not None:
        id_number = getattr(practitioner, 'practitioner_licence_number', None) or id_number
        id_type = getattr(practitioner, 'practitioner_identification_type', None) or id_type
        reg_body = getattr(practitioner, 'practitioner_regulation_body', None) or reg_body

    # DHA /prescriptions accepts medication items only — keep payload compliant.
    payload = {
        'consent_token': session.consent_token,
        'intervention_code': intervention,
        'identification_number': id_number,
        'identification_type': id_type,
        'regulation_body': reg_body,
        'items': items,
    }
    client = ShaHieClient()
    try:
        raw = client.create_erx_prescription(payload)
    except ShaHieError as exc:
        session.status = 'error'
        session.last_error = str(exc)
        session.save(update_fields=['status', 'last_error', 'updated_at'])
        raise

    result = raw if isinstance(raw, dict) else {'value': raw}
    result['clinical_context'] = package.get('clinical_context') or {}
    result['erx_includes'] = package.get('includes') or {}
    result['api_payload'] = {
        k: v for k, v in payload.items() if k != 'consent_token'
    }
    session.erx_raw = result
    session.status = 'erx_submitted'
    session.last_error = ''
    session.save()

    # Stamp visit prescriptions as electronically transmitted
    now = timezone.now()
    for rx in Prescription.objects.filter(visit=session.visit).exclude(status='Cancelled'):
        rx.erx_transmitted_at = now
        rx.erx_transmission_raw = result
        if not rx.erx_clinical_context:
            rx.erx_clinical_context = package.get('clinical_context') or {}
            rx.problem_list_snapshot = (package.get('clinical_context') or {}).get('problem_list') or []
            rx.medication_list_snapshot = (package.get('clinical_context') or {}).get('medication_list') or []
            rx.diagnostic_tests_snapshot = (package.get('clinical_context') or {}).get('diagnostic_tests') or []
            rx.includes_problem_list = bool(rx.problem_list_snapshot)
            rx.includes_medication_list = bool(rx.medication_list_snapshot)
            rx.includes_diagnostic_tests = bool(rx.diagnostic_tests_snapshot)
        rx.save()

    return session


def snapshot_dispense_codes(visit: Visit) -> int:
    """Copy Medication.actual_product_code onto dispensed Rx lines when missing."""
    updated = 0
    qs = PrescriptionItem.objects.filter(
        prescription__visit=visit,
        dispensed=True,
    ).select_related('medication', 'medication__medication')
    for row in qs:
        if row.actual_product_code:
            continue
        med = getattr(row.medication, 'medication', None)
        pack = (getattr(med, 'actual_product_code', None) or '').strip() if med else ''
        if pack:
            row.actual_product_code = pack
            row.save(update_fields=['actual_product_code'])
            updated += 1
    return updated


def submit_erx_dispense(session: ShaClaimSession, *, practitioner: Any = None) -> ShaClaimSession:
    if not session.consent_token:
        raise ValueError('consent_token required.')
    snapshot_dispense_codes(session.visit)
    products = []
    qs = PrescriptionItem.objects.filter(
        prescription__visit=session.visit,
        dispensed=True,
    ).select_related('medication', 'medication__medication')
    for row in qs:
        pack = (row.actual_product_code or '').strip()
        if not pack:
            med = getattr(row.medication, 'medication', None)
            pack = (getattr(med, 'actual_product_code', None) or '').strip() if med else ''
        if not pack:
            continue
        price = row.medication.selling_price or Decimal('0')
        qty = int(row.quantity or 0)
        products.append({
            'actual_product_code': pack,
            'medication_price': float(price),
            'total_quantity': qty,
        })
    if not products:
        raise ValueError(
            'No dispensed lines with actual_product_code (PH*). '
            'Set pack codes on Medication or Rx items.'
        )
    id_number = session.practitioner_identification_number
    id_type = session.practitioner_identification_type or 'registration_number'
    if practitioner is not None:
        id_number = getattr(practitioner, 'practitioner_licence_number', None) or id_number
        id_type = getattr(practitioner, 'practitioner_identification_type', None) or id_type
    intervention = (session.intervention_codes or [_default_intervention(session.visit)])[0]
    payload = {
        'consent_token': session.consent_token,
        'intervention_code': intervention,
        'actual_products': products,
        'doctors': [{
            'identification_number': id_number,
            'identification_type': id_type,
        }],
    }
    client = ShaHieClient()
    try:
        raw = client.create_erx_dispense(payload)
    except ShaHieError as exc:
        session.status = 'error'
        session.last_error = str(exc)
        session.save(update_fields=['status', 'last_error', 'updated_at'])
        raise
    erx = dict(session.erx_raw or {})
    erx['dispense'] = raw
    session.erx_raw = erx
    session.status = 'dispensed'
    session.last_error = ''
    session.save()
    return session


def submit_claim(
    session: ShaClaimSession,
    *,
    otp: str | None = None,
    invoice: Invoice | None = None,
    notes: str = '',
) -> ShaClaimSession:
    if not session.consent_token:
        raise ValueError('consent_token required — start visit first.')
    inv = invoice or session.invoice
    inv_number = None
    if inv is not None:
        inv_number = getattr(inv, 'invoice_number', None) or f'INV-{inv.pk}'
        session.invoice = inv
    client = ShaHieClient()
    try:
        raw = client.submit_virtual_claim(
            consent_token=session.consent_token,
            otp=otp,
            invoice_number=inv_number,
            notes=notes or None,
            discharge_reason='RECOVERED' if session.service_type != 'INPATIENT' else None,
        )
    except ShaHieError as exc:
        session.status = 'error'
        session.last_error = str(exc)
        session.save(update_fields=['status', 'last_error', 'updated_at', 'invoice'])
        raise
    session.submit_raw = {
        **(session.submit_raw if isinstance(session.submit_raw, dict) else {}),
        'submit': raw,
    }
    session.workflow_state = str(raw.get('workflow_state') or session.workflow_state or '')
    if raw.get('claim_id'):
        session.claim_id = str(raw.get('claim_id'))
    if raw.get('edi_claim_guid'):
        session.edi_claim_guid = str(raw.get('edi_claim_guid'))
    session.status = 'submitted'
    session.last_error = ''
    session.save()
    return session


def create_normal_preauth(
    session: ShaClaimSession,
    *,
    unit_price: str = '0',
    icd_code: str = '',
) -> ShaClaimSession:
    if not session.consent_token:
        raise ValueError('consent_token required.')
    intervention = (session.intervention_codes or [_default_intervention(session.visit)])[0]
    start = timezone.now()
    end = start + timedelta(hours=24)
    # Pull ICD from visit diagnosis if not provided
    if not icd_code:
        from home.models import Diagnosis
        d = Diagnosis.objects.filter(visit=session.visit).exclude(icd11_code='').order_by('-id').first()
        if d:
            icd_code = d.icd11_code
    form = {
        'consent_token': session.consent_token,
        'intervention_code': intervention,
        'service_start': start.isoformat(),
        'service_end': end.isoformat(),
        'items': f'{{"unit_price":"{unit_price}"}}',
        'diagnoses': (
            f'{{"consent_token":"{session.consent_token}","icd_code":"{icd_code}"}}'
            if icd_code else ''
        ),
        'doctors': (
            f'{{"identification_number":"{session.practitioner_identification_number}",'
            f'"identification_type":"{session.practitioner_identification_type or "registration_number"}",'
            f'"regulation_body":"{session.practitioner_regulation_body or "KMPDC"}",'
            f'"intervention_code":"{intervention}","is_primary":true}}'
        ),
        'provider_notification_email': getattr(settings, 'SHA_HIE_PROVIDER_EMAIL', '') or 'claims@facility.local',
    }
    form = {k: v for k, v in form.items() if v}
    client = ShaHieClient()
    try:
        raw = client.create_preauth(form)
    except ShaHieError as exc:
        session.status = 'error'
        session.last_error = str(exc)
        session.save(update_fields=['status', 'last_error', 'updated_at'])
        raise
    session.preauth_raw = raw if isinstance(raw, dict) else {'value': raw}
    session.status = 'preauth_pending'
    session.last_error = ''
    session.save()
    return session


@transaction.atomic
def mark_rx_item_dispensed(item: PrescriptionItem, user, *, actual_product_code: str = '') -> PrescriptionItem:
    """Pharmacy helper: stamp dispense + optional PH* code."""
    if not item.dispensed:
        item.dispensed = True
        item.dispensed_at = timezone.now()
        item.dispensed_by = user
    code = (actual_product_code or item.actual_product_code or '').strip()
    if not code:
        med = getattr(item.medication, 'medication', None)
        code = (getattr(med, 'actual_product_code', None) or '').strip() if med else ''
    if code:
        item.actual_product_code = code
    item.save()
    return item
