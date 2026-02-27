import os
import django
import sys
from datetime import date
from decimal import Decimal

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient, Visit
from inpatient.models import Admission, GatePass
from accounts.models import Invoice, InvoiceItem
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()

def verify_gatepass():
    # 1. Setup
    user = User.objects.first()
    patient, _ = Patient.objects.get_or_create(
        first_name="GatePass",
        last_name="Test",
        defaults={'gender': 'Other', 'date_of_birth': date(2000, 1, 1)}
    )
    
    visit = Visit.objects.create(patient=patient, visit_type='IN-PATIENT', is_active=True)
    admission = Admission.objects.create(
        patient=patient,
        visit=visit,
        status='Discharged', # Must be discharged for gatepass
        admitted_by=user
    )
    
    invoice = Invoice.objects.create(patient=patient, visit=visit, status='Pending', created_by=user)
    InvoiceItem.objects.create(
        invoice=invoice,
        name="Test Service",
        unit_price=Decimal('100.00'),
        quantity=1,
        amount=Decimal('100.00'),
        paid_amount=Decimal('0.00'),
        created_by=user
    )
    
    print(f"Created Admission: {admission.id}, Status: {admission.status}")
    print(f"Created Invoice: {invoice.id}, Balance: {invoice.balance()}")

    # 2. Test Clearance Check (Should fail)
    from inpatient.utils import check_billing_clearance
    is_cleared, balance, msg = check_billing_clearance(admission)
    print(f"\nInitial Clearance Check: Is Cleared={is_cleared}, Balance={balance}, Msg={msg}")
    
    if is_cleared:
        print("FAILURE: Expected clearance to fail for unpaid bill.")
        sys.exit(1)

    # 3. Pay Bill
    invoice.items.all().update(paid_amount=F('amount'))
    invoice.status = 'Paid'
    invoice.save()
    print(f"\nInvoice paid. New Balance: {invoice.balance()}")

    # 4. Test Clearance Check (Should pass)
    is_cleared, balance, msg = check_billing_clearance(admission)
    print(f"Post-Payment Clearance Check: Is Cleared={is_cleared}, Balance={balance}, Msg={msg}")
    
    if not is_cleared:
        print("FAILURE: Expected clearance to pass after payment.")
        sys.exit(1)

    # 5. Create Gatepass
    gate_pass = GatePass.objects.create(admission=admission, issued_by=user)
    print(f"\nGatePass created: {gate_pass.pass_number}")

    print("\nSUCCESS: Gatepass workflow verified.")

    # Cleanup
    gate_pass.delete()
    invoice.delete()
    admission.delete()
    visit.delete()

from django.db.models import F

if __name__ == "__main__":
    verify_gatepass()
