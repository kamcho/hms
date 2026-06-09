from django.utils import timezone
from django.db import transaction
from .models import Admission
from home.models import Visit
from accounts.models import Invoice, InvoiceItem
from django.db.models import F, Q

def handle_admission_transition(patient, new_visit, user, previous_invoice=None):
    """
    Closes any existing active admissions for a patient and transfers unpaid 
    invoice items to a new visit.
    
    Args:
        patient: The Patient object
        new_visit: The new Visit object (IN-PATIENT)
        user: The user performing the action
        previous_invoice: Optional explicit invoice to transfer from
    """
    # 1. Close all active admissions
    active_admissions = Admission.objects.filter(patient=patient, status='Admitted')
    
    for adm in active_admissions:
        adm.status = 'Discharged'
        adm.discharged_at = timezone.now()
        adm.discharged_by = user
        adm.save()
        
        # Release the bed
        if adm.bed:
            adm.bed.is_occupied = False
            adm.bed.save()
            
    # 2. Deactivate previous active visits
    # This ensures only the new visit is the "latest active" one
    Visit.objects.filter(patient=patient, is_active=True).exclude(id=new_visit.id).update(is_active=False)
    
    # 3. Transfer Invoice Items if transfer source is identified
    if not previous_invoice:
        # If no explicit invoice, look for the most recent pending invoice for this patient
        previous_invoice = Invoice.objects.filter(
            patient=patient, 
            status__in=['Pending', 'Partial']
        ).exclude(visit=new_visit).order_by('-created_at').first()
        
    if previous_invoice and previous_invoice.visit != new_visit:
        from accounts.utils import get_or_create_invoice
        new_invoice = get_or_create_invoice(visit=new_visit, user=user)
        
        items_transferred = 0
        for item in previous_invoice.items.all():
            # Only transfer unpaid items or the unpaid portion?
            # User said "zeroes its invoice", so we'll mirror the items
            if item.amount > item.paid_amount:
                # Calculate unpaid portion
                unpaid_amount = item.amount - item.paid_amount
                
                # In this system, we usually create a new item with the full price
                # and mark the old one as "Paid" or "Canceled"
                InvoiceItem.objects.create(
                    invoice=new_invoice,
                    service=item.service,
                    inventory_item=item.inventory_item,
                    name=item.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    amount=item.amount,
                    paid_amount=item.paid_amount, # Carry over what was already paid? 
                    # Usually we want the new invoice to show the total bill.
                    created_by=user
                )
                items_transferred += 1
        
        # 4. Zero out/Cancel the previous invoice
        if items_transferred > 0:
            # Mark all items in previous invoice as "paid" by setting paid_amount = amount
            # This prevents them from showing up in pending bills
            previous_invoice.items.all().update(paid_amount=F('amount'))
            previous_invoice.status = 'Cancelled'
            previous_invoice.notes = f"Items transferred to Invoice #{new_invoice.id} via admission transition."
            previous_invoice.save()
            
    return active_admissions.count()

def check_billing_clearance(admission):
    """
    Checks if all invoices linked to the admission's visit are fully paid.
    Returns (is_cleared, pending_balance, message)
    """
    if not admission.visit:
        return True, 0, "No visit linked to this admission."
    
    invoices = Invoice.objects.filter(visit=admission.visit).exclude(status='Cancelled')
    
    total_balance = 0
    pending_invoices = []
    
    for inv in invoices:
        balance = inv.balance
        if balance > 0:
            total_balance += balance
            pending_invoices.append(f"#{inv.id}")
            
    if total_balance > 0:
        return False, total_balance, f"Pending balance: {total_balance}. Unpaid invoices: {', '.join(pending_invoices)}."
        
    return True, 0, "All bills cleared."


def _map_mother_condition_for_discharge(delivery):
    """Map LaborDelivery.mother_condition to MaternityDischarge choices."""
    raw = (delivery.mother_condition or '').strip()
    mapping = {
        'Stable': 'Stable',
        'ICU': 'Complicated',
        'Deceased': 'Complicated',
    }
    return mapping.get(raw, 'Stable')


def _baby_condition_summary(delivery):
    newborns = delivery.newborns.all()
    if newborns.exists():
        return ', '.join(f"Baby {b.baby_number}: {b.status}" for b in newborns)
    return 'Healthy'


def sync_maternity_discharge_from_ipd(admission, ipd_discharge, user, medications_prescribed=''):
    """
    When a maternity-linked admission is discharged from IPD, mirror the record
    into MaternityDischarge and update pregnancy status.
    """
    delivery = getattr(admission, 'delivery', None)
    if not delivery:
        return None

    from maternity.models import MaternityDischarge

    pregnancy = delivery.pregnancy
    mat_discharge, _created = MaternityDischarge.objects.update_or_create(
        pregnancy=pregnancy,
        defaults={
            'discharge_date': ipd_discharge.discharge_date,
            'mother_condition_at_discharge': _map_mother_condition_for_discharge(delivery),
            'baby_condition_at_discharge': _baby_condition_summary(delivery),
            'final_diagnosis': ipd_discharge.final_diagnosis or '',
            'discharge_summary': ipd_discharge.clinical_management_summary or '',
            'follow_up_plan': ipd_discharge.discharge_care_plan or '',
            'medications_prescribed': medications_prescribed or '',
            'discharged_by': user,
        },
    )

    if pregnancy.status == 'Active':
        pregnancy.status = 'Delivered'
        pregnancy.save(update_fields=['status'])

    return mat_discharge


def get_active_maternity_admission(pregnancy):
    """Return the active IPD admission for a pregnancy patient, if any."""
    from inpatient.models import Admission

    admission = Admission.objects.filter(
        patient=pregnancy.patient,
        status='Admitted',
    ).order_by('-admitted_at').first()
    if admission:
        return admission

    delivery = getattr(pregnancy, 'delivery', None)
    if delivery and delivery.admission_id and delivery.admission.status == 'Admitted':
        return delivery.admission
    return None


def ensure_maternity_admission_for_discharge(pregnancy, user):
    """
    Return an active Admission so maternity patients can discharge from the
    case folder even when delivery was recorded without ward/bed assignment.
    """
    from inpatient.models import Admission

    admission = get_active_maternity_admission(pregnancy)
    if admission:
        return admission

    if hasattr(pregnancy, 'maternity_discharge'):
        return None

    delivery = getattr(pregnancy, 'delivery', None)
    if not delivery:
        return None

    if delivery.admission_id and delivery.admission.status == 'Discharged':
        return None

    if not delivery.visit_id:
        visit = Visit.objects.create(
            patient=pregnancy.patient,
            visit_type='IN-PATIENT',
            visit_mode='Walk In',
            is_active=True,
        )
        delivery.visit = visit
        delivery.save(update_fields=['visit'])
    else:
        visit = delivery.visit

    Visit.objects.filter(
        patient=pregnancy.patient,
        is_active=True,
    ).exclude(id=visit.id).update(is_active=False)

    if not visit.is_active:
        visit.is_active = True
        visit.save(update_fields=['is_active'])

    if delivery.delivery_mode:
        diagnosis = f"Delivery - {delivery.get_delivery_mode_display()}"
    else:
        diagnosis = 'Maternity / Delivery'

    admission = Admission.objects.create(
        patient=pregnancy.patient,
        visit=visit,
        bed=None,
        provisional_diagnosis=diagnosis,
        admitted_by=user,
        status='Admitted',
    )
    delivery.admission = admission
    delivery.save(update_fields=['admission'])

    return admission


def admin_close_admission_and_visit(admission, user):
    """Administratively discharge an admission and close its visit (Clean Admissions)."""
    now = timezone.now()

    with transaction.atomic():
        admission.status = 'Discharged'
        admission.discharged_at = now
        admission.discharged_by = user
        admission.save()

        if admission.visit_id:
            Visit.objects.filter(pk=admission.visit_id).update(is_active=False)

        from maternity.models import LaborDelivery, MaternityDischarge

        try:
            delivery = admission.delivery
        except LaborDelivery.DoesNotExist:
            delivery = None

        if delivery:
            pregnancy = delivery.pregnancy
            if pregnancy.status == 'Active':
                pregnancy.status = 'Delivered'
                pregnancy.save(update_fields=['status'])

            if not hasattr(pregnancy, 'maternity_discharge'):
                MaternityDischarge.objects.create(
                    pregnancy=pregnancy,
                    discharge_date=now,
                    mother_condition_at_discharge=_map_mother_condition_for_discharge(delivery),
                    baby_condition_at_discharge=_baby_condition_summary(delivery),
                    final_diagnosis=admission.provisional_diagnosis or '',
                    discharge_summary='Administratively closed from Clean Admissions.',
                    follow_up_plan='',
                    discharged_by=user,
                )


def admin_close_orphan_visit(visit):
    """Close an active inpatient visit that has no open admission."""
    visit.is_active = False
    visit.save(update_fields=['is_active'])
