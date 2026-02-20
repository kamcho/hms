import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from accounts.models import Service, Invoice, InvoiceItem
from home.models import Patient, Visit, Departments
from lab.models import LabResult
from django.test import RequestFactory
from home.views import submit_next_action
from django.contrib.auth import get_user_model

User = get_user_model()

def verify_anc_profile():
    # 1. Setup
    user = User.objects.filter(role='Doctor').first()
    if not user:
        user = User.objects.create_user(username='testdoctor', password='password', role='Doctor')
    
    patient = Patient.objects.first()
    visit = Visit.objects.filter(patient=patient, is_active=True).first()
    if not visit:
        print("No active visit found for testing.")
        return

    # Find ANC Profile service
    anc_service = Service.objects.filter(name__icontains='ANC Profile').first()
    if not anc_service:
        print("ANC Profile service not found.")
        return

    # 2. Simulate Request
    factory = RequestFactory()
    data = {
        'patient_id': patient.id,
        'tests': [str(anc_service.id)],
        'send_to': ['Lab']
    }
    request = factory.post('/home/submit-next-action/', data)
    request.user = user

    # 3. Execute
    from django.http import JsonResponse
    response = submit_next_action(request)
    print(f"Response: {response.content}")

    # 4. Verify
    invoice = Invoice.objects.filter(visit=visit).latest('created_at')
    items = InvoiceItem.objects.filter(invoice=invoice)
    
    print(f"Invoice Items: {items.count()}")
    for item in items:
        print(f"- {item.name}: {item.unit_price}")

    bundled_names = [
        "Haemoglobin level (HB)",
        "Rhesus",
        "Random Blood Sugar (RBS)",
        "Urinalysis",
        "Hepatitis B Surface Antigen (HBsAg)",
        "Blood grouping"
    ]
    
    found_bundled = [item.name for item in items if item.name in bundled_names]
    print(f"Found bundled tests: {len(found_bundled)}")
    
    all_zero = all(item.unit_price == 0 for item in items if item.name in bundled_names)
    print(f"Bundled tests have 0 price: {all_zero}")
    
    anc_price_correct = any(item.name == anc_service.name and item.unit_price == anc_service.price for item in items)
    print(f"ANC Profile price correct: {anc_price_correct}")

    lab_results = LabResult.objects.filter(invoice=invoice)
    print(f"Lab Results created: {lab_results.count()}")

if __name__ == "__main__":
    verify_anc_profile()
