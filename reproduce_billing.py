
import os
import django
from django.conf import settings
from django.utils import timezone

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient, Visit, Departments
from accounts.models import Invoice, InvoiceItem, Service
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from home.views import admit_patient_visit
import json

User = get_user_model()

def run_test():
    print("Setting up test data...")
    # Create User
    user, _ = User.objects.get_or_create(id_number='999999', defaults={'role': 'Admin', 'password': 'password'})
    
    import datetime
    patient, _ = Patient.objects.get_or_create(
        first_name="Test", last_name="Patient",
        date_of_birth=datetime.date(1990, 1, 1), gender="Male"
    )
    
    # Create Service
    service, _ = Service.objects.get_or_create(
        name="General Consultation",
        price=500.00,
        defaults={'description': 'General OPD Consultation'}
    )
    
    # Create Department
    opd_dept, _ = Departments.objects.get_or_create(name="OPD")
    service.department = opd_dept
    service.save()

    # Clear previous data
    InvoiceItem.objects.all().delete()
    Invoice.objects.all().delete()
    Visit.objects.all().delete()
    
    # 1. First Visit (Should be billed)
    print("\nTest 1: First Visit (Should be billed)")
    factory = RequestFactory()
    request = factory.post('/home/admit/', {
        'patient_id': patient.id,
        'consultation_id': service.id
    })
    request.user = user
    
    response = admit_patient_visit(request)
    print(f"Response: {response.content.decode()}")
    
    # Check Invoice
    invoice_count = InvoiceItem.objects.filter(invoice__patient=patient, service=service).count()
    print(f"Invoice Items Count: {invoice_count} (Expected: 1)")

    # 2. Second Visit (Should NOT be billed)
    print("\nTest 2: Second Visit (Same Year) (Should NOT be billed)")
    # Mark the first invoice as Paid to satisfy the check
    invoice = Invoice.objects.filter(patient=patient).first()
    if invoice:
        invoice.status = 'Paid'
        invoice.save()
        
    response = admit_patient_visit(request) # Same request
    print(f"Response: {response.content.decode()}")
    
    # Check Invoice (Should still be 1)
    invoice_count_2 = InvoiceItem.objects.filter(invoice__patient=patient, service=service).count()
    print(f"Invoice Items Count: {invoice_count_2} (Expected: 1)")
    
    if invoice_count == 1 and invoice_count_2 == 1:
        print("\nSUCCESS: Annual billing logic is working correctly.")
    else:
        print("\nFAILURE: Annual billing logic is NOT working.")

if __name__ == "__main__":
    run_test()
