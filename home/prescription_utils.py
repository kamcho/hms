from django.core.cache import cache
from django.utils import timezone

from .models import Prescription

SUBMIT_CACHE_TTL = 120


def prescription_submit_cache_key(visit_id, token):
    return f'presc_create:{visit_id}:{token}'


def prescription_submit_inflight_key(visit_id, token):
    return f'{prescription_submit_cache_key(visit_id, token)}:inflight'


def get_cached_prescription_id(visit_id, token):
    if not token:
        return None
    return cache.get(prescription_submit_cache_key(visit_id, token))


def try_acquire_prescription_submit_lock(visit_id, token):
    """Return True if this request may proceed (first submit for this token)."""
    if not token:
        return True
    return cache.add(prescription_submit_inflight_key(visit_id, token), True, SUBMIT_CACHE_TTL)


def release_prescription_submit_lock(visit_id, token):
    if token:
        cache.delete(prescription_submit_inflight_key(visit_id, token))


def cache_prescription_submit(visit_id, token, prescription_id):
    if token and prescription_id:
        cache.set(
            prescription_submit_cache_key(visit_id, token),
            prescription_id,
            SUBMIT_CACHE_TTL,
        )
        release_prescription_submit_lock(visit_id, token)


def prescription_edit_cache_key(prescription_id, token):
    return f'presc_edit:{prescription_id}:{token}'


def prescription_edit_inflight_key(prescription_id, token):
    return f'{prescription_edit_cache_key(prescription_id, token)}:inflight'


def get_cached_edit_prescription_id(prescription_id, token):
    if not token:
        return None
    return cache.get(prescription_edit_cache_key(prescription_id, token))


def try_acquire_prescription_edit_lock(prescription_id, token):
    if not token:
        return True
    return cache.add(prescription_edit_inflight_key(prescription_id, token), True, SUBMIT_CACHE_TTL)


def release_prescription_edit_lock(prescription_id, token):
    if token:
        cache.delete(prescription_edit_inflight_key(prescription_id, token))


def cache_prescription_edit(prescription_id, token):
    if token:
        cache.set(
            prescription_edit_cache_key(prescription_id, token),
            prescription_id,
            SUBMIT_CACHE_TTL,
        )
        release_prescription_edit_lock(prescription_id, token)


def get_or_create_visit_prescription(visit, patient, user, *, diagnosis='', notes=''):
    """Return (prescription, created) — one active header per visit."""
    prescription = (
        Prescription.objects.filter(visit=visit)
        .exclude(status='Cancelled')
        .order_by('-prescribed_at')
        .first()
    )
    if prescription:
        updates = []
        if diagnosis and prescription.diagnosis != diagnosis:
            prescription.diagnosis = diagnosis
            updates.append('diagnosis')
        if notes and prescription.notes != notes:
            prescription.notes = notes
            updates.append('notes')
        if updates:
            prescription.save(update_fields=updates)
        return prescription, False

    prescription = Prescription.objects.create(
        patient=patient,
        visit=visit,
        prescribed_by=user,
        diagnosis=diagnosis,
        notes=notes or '',
        status='Active',
        prescribed_at=timezone.now(),
    )
    return prescription, True
