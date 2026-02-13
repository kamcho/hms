
import os
import django
import json
from datetime import date

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from home.models import Patient, Visit
from accounts.models import Procedure, Invoice, InvoiceItem
from accounts.views import charge_procedure
from users.models import User

# Setup Data
print("Setting up test data...")
# Create a dummy user
user, _ = User.objects.get_or_create(username='test_doctor', role='Doctor', id_number='DOC001')

# Create a patient and visit
patient, _ = Patient.objects.get_or_create(
    id_number='test_proc_patient',
    defaults={
        'first_name': 'Proc',
        'last_name': 'Patient',
        'date_of_birth': date(1990,1,1),
        'gender': 'F',
        'phone': '0700000000',
        'location': 'Nairobi'
    }
)

visit, _ = Visit.objects.get_or_create(
    patient=patient,
    visit_type='OUT-PATIENT',
    defaults={'visit_mode': 'Walk In'}
)

# Ensure no existing invoice for this visit (or use it)
invoice = Invoice.objects.filter(visit=visit).exclude(status='Cancelled').first()
if invoice:
    print(f"Found existing invoice: {invoice}")
else:
    print("No existing invoice, one should be created.")

# Get a procedure
proc = Procedure.objects.first()
if not proc:
    # Create one if missing
    proc = Procedure.objects.create(name="Test Procedure", price=1000)

print(f"Testing Charge Procedure: {proc.name} (ID: {proc.id}) -> Patient: {patient.full_name}")

# Create Request
factory = RequestFactory()
data = {
    'procedure_id': proc.id,
    'patient_id': patient.id,
    'visit_id': visit.id,
    'notes': 'Test charge from script'
}
request = factory.post('/accounts/api/procedures/charge/', data)
request.user = user

# Add session
middleware = SessionMiddleware(lambda x: None)
middleware.process_request(request)
request.session.save()

# Execute View
response = charge_procedure(request)
print(f"Response Status: {response.status_code}")
print(f"Response Content: {response.content.decode()}")

# Verify Side Effects
if response.status_code == 200:
    resp_data = json.loads(response.content)
    if resp_data.get('status') == 'success':
        # Check InvoiceItem
        invoice = Invoice.objects.filter(visit=visit).exclude(status='Cancelled').first()
        if invoice:
            item = InvoiceItem.objects.filter(invoice=invoice, procedure=proc).last()
            if item:
                print(f"SUCCESS: InvoiceItem created! ID: {item.id}, Amount: {item.amount}")
            else:
                print("FAILURE: InvoiceItem not found.")
        else:
            print("FAILURE: Invoice not found.")
    else:
        print(f"FAILURE: API returned error: {resp_data.get('message')}")
else:
    print("FAILURE: View returned non-200 status.")
