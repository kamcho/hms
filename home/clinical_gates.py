"""Clinical workflow gates (e.g. compulsory TB screening before documentation)."""

from .models import TBScreening, Visit

TB_SCREENING_MESSAGE = (
    'Complete compulsory TB screening for this visit before other clinical actions.'
)


def is_latest_active_visit(visit):
    if not visit or not visit.is_active:
        return False
    latest = Visit.objects.filter(patient=visit.patient).order_by('-visit_date').first()
    return latest and visit.pk == latest.pk


def doctor_requires_tb_screening(user, visit):
    """Doctors must record TB screening on the latest active OPD visit before other work."""
    if getattr(user, 'role', None) != 'Doctor':
        return False
    if not visit or getattr(visit, 'visit_type', None) == 'IN-PATIENT':
        return False
    if not is_latest_active_visit(visit):
        return False
    return not TBScreening.objects.filter(visit=visit).exists()


def tb_screening_required_for_patient_view(user, latest_visit, selected_visit):
    """True when the patient detail page should lock clinical actions for this doctor."""
    if not latest_visit or not latest_visit.is_active:
        return False
    if getattr(user, 'role', None) != 'Doctor':
        return False
    if latest_visit.visit_type == 'IN-PATIENT':
        return False
    viewing_latest = selected_visit is None or selected_visit.pk == latest_visit.pk
    if not viewing_latest:
        return False
    if selected_visit and selected_visit.visit_type == 'IN-PATIENT':
        return False
    return not TBScreening.objects.filter(visit=latest_visit).exists()
