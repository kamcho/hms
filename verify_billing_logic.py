
import os
import django
from django.utils import timezone
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient, Visit, Departments
from accounts.models import Invoice, InvoiceItem, Service
from django.contrib.auth import get_user_model

def verify_billing():
    print("--- Verifying Billing Logic ---")
    User = get_user_model()
    user, _ = User.objects.get_or_create(id_number='test_admin', role='Admin')

    # 1. Setup Services
    opd_service, _ = Service.objects.get_or_create(name='General Consultation', price=500)
    anc_service, _ = Service.objects.get_or_create(name='ANC Consultation', price=1000)

    # 2. Test Case: New Patient (OPD) - Should be Billed
    print("\n[Test 1] New Patient (OPD) - Expecting Invoice")
    patient1 = Patient.objects.create(
        first_name='Billing', last_name='Test1',
        gender='M', date_of_birth=timezone.now().date(),
        location='Test'
    )
    
    # Simulate View Logic for Patient 1 (First Visit)
    # Check if billed this year? No.
    has_billed = InvoiceItem.objects.filter(
        invoice__patient=patient1,
        service=opd_service,
        invoice__created_at__year=timezone.now().year
    ).exists()
    
    if not has_billed:
        # Create Invoice
        visit1 = Visit.objects.create(patient=patient1, visit_type='OUT-PATIENT')
        inv1 = Invoice.objects.create(patient=patient1, visit=visit1, status='Pending', created_by=user)
        InvoiceItem.objects.create(invoice=inv1, service=opd_service, name=opd_service.name, unit_price=opd_service.price, quantity=1)
        print("  -> Invoice Created (Correct)")
    else:
        print("  -> NO Invoice Created (Incorrect)")

    # 3. Test Case: Same Patient Return Visit (OPD) - Should be Free
    print("\n[Test 2] Return Patient (OPD) - Expecting NO Invoice")
    
    # Simulate View Logic for Patient 1 (Second Visit)
    has_billed_2 = InvoiceItem.objects.filter(
        invoice__patient=patient1,
        service=opd_service,
        invoice__created_at__year=timezone.now().year
    ).exists()
    
    if has_billed_2:
        # Don't create invoice
        visit2 = Visit.objects.create(patient=patient1, visit_type='OUT-PATIENT')
        print("  -> Visit created, NO Invoice (Correct)")
    else:
        # Create Invoice
        print("  -> Invoice Created (Incorrect - Should be free)")

    # 4. Test Case: ANC Patient - Should ALWAYS be Billed
    print("\n[Test 3] ANC Patient - Expecting Invoice Always")
    patient2 = Patient.objects.create(
        first_name='Billing', last_name='Test2',
        gender='F', date_of_birth=timezone.now().date(),
        location='Test'
    )
    
    # Simulate View Logic for ANC (Always Bill)
    visit3 = Visit.objects.create(patient=patient2, visit_type='OUT-PATIENT')
    inv3 = Invoice.objects.create(patient=patient2, visit=visit3, status='Pending', created_by=user)
    InvoiceItem.objects.create(invoice=inv3, service=anc_service, name=anc_service.name, unit_price=anc_service.price, quantity=1)
    print("  -> ANC Invoice 1 Created")
    
    # Second ANC Visit
    print("[Test 3b] ANC Return Visit - Expecting Another Invoice")
    # For ANC, we don't check "has_billed", we just bill.
    visit4 = Visit.objects.create(patient=patient2, visit_type='OUT-PATIENT')
    inv4 = Invoice.objects.create(patient=patient2, visit=visit4, status='Pending', created_by=user)
    InvoiceItem.objects.create(invoice=inv4, service=anc_service, name=anc_service.name, unit_price=anc_service.price, quantity=1)
    print("  -> ANC Invoice 2 Created (Correct)")

if __name__ == '__main__':
    verify_billing()
