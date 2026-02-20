from .models import Invoice
from django.db import transaction

def get_or_create_invoice(visit=None, deceased=None, user=None):
    """
    Centralized utility to ensure a visit or deceased record has exactly one invoice.
    Enforces the single-invoice-per-visit business rule.
    """
    if not visit and not deceased:
        return None
    
    with transaction.atomic():
        if visit:
            invoice, created = Invoice.objects.get_or_create(
                visit=visit,
                defaults={
                    'patient': visit.patient,
                    'status': 'Pending',
                    'created_by': user
                }
            )
        else: # deceased
            invoice, created = Invoice.objects.get_or_create(
                deceased=deceased,
                defaults={
                    'status': 'Pending',
                    'created_by': user
                }
            )
            
    return invoice
