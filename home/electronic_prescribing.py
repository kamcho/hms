"""
Electronic prescribing clinical context.

DHA POST /prescriptions accepts medication items only. This module attaches the
checklist extras — Problem List, Medication Lists, Diagnostic Tests — to the
local eRx package, prescription snapshot, and optional HIE clinical sync that
runs alongside electronic transmission.
"""
from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone


def collect_problem_list(patient, *, problem_ids: list[int] | None = None) -> list[dict[str, Any]]:
    from .knhts_conditions import ACTIVE_CLINICAL_STATUSES
    from .models import Problem

    qs = Problem.objects.filter(patient=patient).exclude(
        verification_status='entered-in-error',
    ).filter(clinical_status__in=ACTIVE_CLINICAL_STATUSES)
    if problem_ids:
        qs = qs.filter(pk__in=problem_ids)
    rows = []
    for p in qs.order_by('-updated_at')[:40]:
        rows.append({
            'id': p.pk,
            'display': p.display,
            'icd11_code': p.icd11_code or '',
            'clinical_status': p.clinical_status,
            'category': p.category,
            'severity': p.severity or '',
        })
    return rows


def collect_medication_list(patient) -> list[dict[str, Any]]:
    from .models import PatientMedication

    rows = []
    for m in PatientMedication.objects.filter(patient=patient, status='active').order_by('-updated_at')[:50]:
        rows.append({
            'id': m.pk,
            'display_name': m.display_name,
            'generic_concept_code': m.generic_concept_code or '',
            'generic_concept_display': m.generic_concept_display or '',
            'dose_text': m.dose_text or '',
            'frequency': m.frequency or '',
            'route': m.route or '',
            'source': m.source,
            'status': m.status,
        })
    return rows


def collect_diagnostic_tests(visit, *, service_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """Visit lab/imaging/procedure orders (existing + optionally newly selected)."""
    from accounts.models import Service
    from lab.models import LabResult

    rows: list[dict[str, Any]] = []
    seen: set[int] = set()

    labs = (
        LabResult.objects.filter(invoice__visit=visit)
        .select_related('service', 'service__department')
        .order_by('-requested_at')[:80]
    )
    for lab in labs:
        svc = lab.service
        if not svc:
            continue
        seen.add(svc.pk)
        rows.append({
            'id': svc.pk,
            'name': svc.name,
            'department': svc.department.name if svc.department_id else '',
            'status': lab.status if hasattr(lab, 'status') else '',
            'lab_result_id': lab.pk,
            'source': 'ordered',
        })

    if service_ids:
        for svc in Service.objects.filter(pk__in=service_ids, is_active=True).select_related('department'):
            if svc.pk in seen:
                continue
            rows.append({
                'id': svc.pk,
                'name': svc.name,
                'department': svc.department.name if svc.department_id else '',
                'status': 'selected',
                'lab_result_id': None,
                'source': 'prescription',
            })
    return rows


def build_erx_clinical_context(
    visit,
    *,
    problem_ids: list[int] | None = None,
    include_medication_list: bool = True,
    diagnostic_service_ids: list[int] | None = None,
) -> dict[str, Any]:
    patient = visit.patient
    problems = collect_problem_list(patient, problem_ids=problem_ids)
    medications = collect_medication_list(patient) if include_medication_list else []
    diagnostics = collect_diagnostic_tests(visit, service_ids=diagnostic_service_ids)

    # Visit diagnoses as encounter diagnoses (supplement problem list)
    from .models import Diagnosis
    diagnoses = [
        {
            'display': d.data or '',
            'icd11_code': d.icd11_code or '',
        }
        for d in Diagnosis.objects.filter(visit=visit).order_by('-created_at')[:20]
    ]

    return {
        'visit_id': visit.pk,
        'patient_id': patient.pk,
        'generated_at': timezone.now().isoformat(),
        'problem_list': problems,
        'diagnoses': diagnoses,
        'medication_list': medications,
        'diagnostic_tests': diagnostics,
        'includes': {
            'problem_list': bool(problems),
            'medication_list': bool(medications),
            'diagnostic_tests': bool(diagnostics),
            'diagnoses': bool(diagnoses),
        },
    }


@transaction.atomic
def order_diagnostic_tests_for_visit(visit, service_ids: list[int], *, user=None) -> list[dict[str, Any]]:
    """Bill + create LabResult rows for selected diagnostic services on the visit."""
    from accounts.models import InvoiceItem, Service
    from accounts.utils import get_or_create_invoice
    from lab.models import LabResult

    if not service_ids:
        return []

    invoice = get_or_create_invoice(visit=visit, user=user)
    ordered = []
    services = Service.objects.filter(pk__in=service_ids, is_active=True).select_related('department')
    for svc in services:
        dept_name = (svc.department.name if svc.department_id else '') or ''
        existing = (
            LabResult.objects.filter(invoice__visit=visit, service=svc)
            .exclude(status='Cancelled')
            .first()
        )
        if existing:
            ordered.append({
                'id': svc.pk,
                'name': svc.name,
                'department': dept_name,
                'lab_result_id': existing.pk,
                'status': existing.status,
                'source': 'existing',
            })
            continue

        item = InvoiceItem.objects.create(
            invoice=invoice,
            service=svc,
            name=svc.name,
            unit_price=svc.price or 0,
            quantity=1,
        )
        lab = LabResult.objects.create(
            patient=visit.patient,
            invoice=invoice,
            invoice_item=item,
            service=svc,
            requested_by=user,
            status='Pending',
        )
        ordered.append({
            'id': svc.pk,
            'name': svc.name,
            'department': dept_name,
            'lab_result_id': lab.pk,
            'status': lab.status,
            'source': 'ordered',
            'invoice_item_id': item.pk,
        })

    try:
        invoice.update_totals()
    except Exception:
        pass
    return ordered


def attach_clinical_context_to_prescription(
    prescription,
    *,
    problem_ids: list[int] | None = None,
    include_medication_list: bool = True,
    diagnostic_service_ids: list[int] | None = None,
    order_diagnostics: bool = True,
    user=None,
) -> dict[str, Any]:
    """Snapshot problem list, medication list, and diagnostic tests onto the prescription."""
    visit = prescription.visit
    if not visit:
        return {}

    ordered = []
    if order_diagnostics and diagnostic_service_ids:
        ordered = order_diagnostic_tests_for_visit(
            visit, diagnostic_service_ids, user=user,
        )

    context = build_erx_clinical_context(
        visit,
        problem_ids=problem_ids,
        include_medication_list=include_medication_list,
        diagnostic_service_ids=diagnostic_service_ids,
    )
    if ordered:
        # Prefer freshly ordered rows in snapshot
        by_id = {d['id']: d for d in context.get('diagnostic_tests') or []}
        for row in ordered:
            by_id[row['id']] = {**by_id.get(row['id'], {}), **row, 'source': row.get('source') or 'ordered'}
        context['diagnostic_tests'] = list(by_id.values())
        context['includes']['diagnostic_tests'] = bool(context['diagnostic_tests'])

    prescription.problem_list_snapshot = context.get('problem_list') or []
    prescription.medication_list_snapshot = context.get('medication_list') or []
    prescription.diagnostic_tests_snapshot = context.get('diagnostic_tests') or []
    prescription.erx_clinical_context = context
    prescription.includes_problem_list = bool(context.get('problem_list'))
    prescription.includes_medication_list = bool(context.get('medication_list'))
    prescription.includes_diagnostic_tests = bool(context.get('diagnostic_tests'))
    prescription.save(update_fields=[
        'problem_list_snapshot',
        'medication_list_snapshot',
        'diagnostic_tests_snapshot',
        'erx_clinical_context',
        'includes_problem_list',
        'includes_medication_list',
        'includes_diagnostic_tests',
    ])
    return context


def parse_id_list(raw_values) -> list[int]:
    ids: list[int] = []
    for v in raw_values or []:
        try:
            ids.append(int(v))
        except (TypeError, ValueError):
            continue
    return ids
