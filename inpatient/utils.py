from django.utils import timezone
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
        balance = inv.balance()
        if balance > 0:
            total_balance += balance
            pending_invoices.append(f"#{inv.id}")
            
    if total_balance > 0:
        return False, total_balance, f"Pending balance: {total_balance}. Unpaid invoices: {', '.join(pending_invoices)}."
        
    return True, 0, "All bills cleared."
