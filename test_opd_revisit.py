import os, django, datetime, json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient, Visit, Departments
from accounts.models import Invoice, InvoiceItem, Service
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from home.views import admit_patient_visit

User = get_user_model()

# Setup
user, _ = User.objects.get_or_create(id_number='999999', defaults={'role': 'Admin', 'password': 'password'})
patient, _ = Patient.objects.get_or_create(first_name="Test", last_name="Patient", date_of_birth=datetime.date(1990, 1, 1), gender="Male")

# Use the EXACT "OPD Consultation" service (ID=19, Ksh 50)
opd_service = Service.objects.get(name='OPD Consultation')
print(f"Using service: '{opd_service.name}' (ID={opd_service.id}, Price={opd_service.price})")

# Clean slate
InvoiceItem.objects.filter(invoice__patient=patient).delete()
Invoice.objects.filter(patient=patient).delete()
Visit.objects.filter(patient=patient).delete()

factory = RequestFactory()

# TEST 1: First visit with OPD Consultation
print("\n--- TEST 1: First visit with OPD Consultation ---")
request = factory.post('/home/admit/', {'patient_id': patient.id, 'consultation_id': opd_service.id})
request.user = user
response = json.loads(admit_patient_visit(request).content)
print(f"Response: {response}")
items = InvoiceItem.objects.filter(invoice__patient=patient)
print(f"InvoiceItems count: {items.count()}")
for item in items:
    print(f"  → name='{item.name}', service='{item.service.name}', price={item.unit_price}, invoice_status={item.invoice.status}")

# Mark invoice as Paid (simulating payment at registration)
inv = Invoice.objects.filter(patient=patient).first()
if inv:
    inv.status = 'Paid'
    inv.save()
    print(f"  → Invoice {inv.id} marked as Paid")

# TEST 2: Second visit with OPD Consultation AGAIN (same service, same year)
print("\n--- TEST 2: Second visit with OPD Consultation AGAIN ---")
request2 = factory.post('/home/admit/', {'patient_id': patient.id, 'consultation_id': opd_service.id})
request2.user = user
response2 = json.loads(admit_patient_visit(request2).content)
print(f"Response: {response2}")
items2 = InvoiceItem.objects.filter(invoice__patient=patient)
print(f"InvoiceItems count: {items2.count()} (should still be 1 if annual check works)")
for item in items2:
    print(f"  → name='{item.name}', service='{item.service.name}', price={item.unit_price}, invoice_status={item.invoice.status}")

# TEST 3: What if first invoice is still 'Draft'? (not paid)
print("\n--- TEST 3: What if invoice is Draft (unpaid)? ---")
InvoiceItem.objects.filter(invoice__patient=patient).delete()
Invoice.objects.filter(patient=patient).delete()
Visit.objects.filter(patient=patient).delete()

# First visit - create but leave invoice as Draft
request3 = factory.post('/home/admit/', {'patient_id': patient.id, 'consultation_id': opd_service.id})
request3.user = user
response3 = json.loads(admit_patient_visit(request3).content)
print(f"First visit: {response3}")
inv3 = Invoice.objects.filter(patient=patient).first()
if inv3:
    print(f"  → Invoice status: '{inv3.status}' (leaving as-is, NOT paying)")

# Second visit - will the Draft invoice count?
request4 = factory.post('/home/admit/', {'patient_id': patient.id, 'consultation_id': opd_service.id})
request4.user = user
response4 = json.loads(admit_patient_visit(request4).content)
print(f"Second visit: {response4}")
items4 = InvoiceItem.objects.filter(invoice__patient=patient)
print(f"InvoiceItems count: {items4.count()}")
for item in items4:
    print(f"  → name='{item.name}', price={item.unit_price}, invoice_status={item.invoice.status}")

