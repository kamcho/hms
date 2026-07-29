"""Patient longitudinal medications & allergies (HPT-coded)."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import PatientMedication, Prescription, PrescriptionItem


def sync_active_medications_from_prescription(prescription: Prescription, *, user=None) -> int:
    """
    Upsert active PatientMedication rows from a saved prescription's items.
    Returns number of rows created/updated.
    """
    if not prescription or not prescription.patient_id:
        return 0
    count = 0
    today = timezone.localdate()
    items = PrescriptionItem.objects.filter(prescription=prescription).select_related(
        'medication', 'medication__medication',
    )
    for item in items:
        med_detail = getattr(item.medication, 'medication', None)
        code = (item.generic_concept_code or '').strip()
        display = (item.generic_concept_display or '').strip()
        if not code and med_detail:
            code = (med_detail.generic_concept_code or '').strip()
            display = display or (med_detail.generic_concept_display or '').strip()
        name = display or item.medication.name
        pack = (item.actual_product_code or '').strip()
        if not pack and med_detail:
            pack = (med_detail.actual_product_code or '').strip()

        dose_bits = []
        if item.dose_count is not None:
            dose_bits.append(str(item.dose_count))
        if item.dose_unit:
            dose_bits.append(item.dose_unit)
        elif item.medication.dispensing_unit:
            dose_bits.append(item.medication.dispensing_unit)
        dose_text = ' '.join(dose_bits)

        existing = None
        if item.pk:
            existing = PatientMedication.objects.filter(
                source_prescription_item=item,
            ).first()
        if not existing and code:
            existing = PatientMedication.objects.filter(
                patient=prescription.patient,
                generic_concept_code=code,
                status='active',
            ).first()
        if not existing:
            existing = PatientMedication.objects.filter(
                patient=prescription.patient,
                display_name=name,
                status='active',
                inventory_item=item.medication,
            ).first()

        if existing:
            existing.display_name = name
            existing.generic_concept_code = code
            existing.generic_concept_display = display
            existing.actual_product_code = pack
            existing.dose_text = dose_text
            existing.frequency = item.frequency or ''
            existing.instructions = item.instructions or ''
            existing.inventory_item = item.medication
            existing.visit = prescription.visit
            existing.source_prescription_item = item
            existing.source = 'prescription'
            existing.updated_by = user
            existing.save()
            existing.record_history(action='updated', changed_by=user, change_summary='Synced from prescription')
        else:
            row = PatientMedication.objects.create(
                patient=prescription.patient,
                visit=prescription.visit,
                source_prescription_item=item,
                inventory_item=item.medication,
                display_name=name,
                generic_concept_code=code,
                generic_concept_display=display,
                actual_product_code=pack,
                dose_text=dose_text,
                frequency=item.frequency or '',
                instructions=item.instructions or '',
                status='active',
                source='prescription',
                start_date=today,
                recorded_by=user,
                updated_by=user,
            )
            row.record_history(action='created', changed_by=user, change_summary='Added from prescription')
        count += 1
    return count


@transaction.atomic
def stop_patient_medication(med: PatientMedication, *, user=None, reason='') -> PatientMedication:
    med.status = 'stopped'
    med.end_date = timezone.localdate()
    if reason:
        med.notes = (med.notes + '\n' if med.notes else '') + reason
    med.updated_by = user
    med.save()
    med.record_history(action='stopped', changed_by=user, change_summary=reason or 'Stopped')
    return med


def search_hpt_allergens(query: str, *, limit: int = 25) -> dict:
    """
    Search HPT for allergen substances. Prefer AC* (active component), then GE*.
    """
    from home.dha_medication import search_dha_medications, rank_hpt_results

    payload = search_dha_medications(query, limit=max(limit, 40), prefer_generic=False)
    if not payload.get('success'):
        return payload
    results = payload.get('results') or []
    # Re-fetch without GE-only filter: search_dha with prefer_generic False still filters?
    # Our search_dha with prefer_generic=False keeps all kinds after rank.
    # Prefer active_component, then generic_product.
    ranked = rank_hpt_results(results, query=query, prefer_generic=False)

    def sort_key(item):
        kind = item.get('kind') or ''
        kind_rank = 0 if kind == 'active_component' else (1 if kind == 'generic_product' else 2)
        return (kind_rank, (item.get('title') or '').lower())

    ranked = sorted(ranked, key=sort_key)
    # Deduplicate by code
    seen = set()
    out = []
    for item in ranked:
        code = (item.get('code') or '').upper()
        if not code or code in seen:
            continue
        # Skip pure form/route junk if any
        if code.startswith(('DF', 'RT')):
            continue
        seen.add(code)
        out.append(item)
        if len(out) >= limit:
            break
    payload['results'] = out
    payload['count'] = len(out)
    payload['message'] = (
        f'Found {len(out)} HPT allergen/substance concept(s).'
        if out else 'No HPT allergen match. You can still save a free-text allergen.'
    )
    return payload
