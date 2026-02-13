import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from maternity.models import Pregnancy
from home.models import Patient, Prescription, PrescriptionItem, Visit
from inventory.models import InventoryItem, InventoryCategory
from django.utils import timezone

User = get_user_model()

def run_test():
    print("Setting up test data...")
    # 1. Create User
    user, _ = User.objects.get_or_create(username='doc_test', role='Doctor')
    if not user.check_password('testpass'):
        user.set_password('testpass')
        user.save()

    # 2. Create Inventory Item
    cat, _ = InventoryCategory.objects.get_or_create(name='Pharmaceuticals')
    med, _ = InventoryItem.objects.get_or_create(
        name='Test Panadol', 
        category=cat,
        defaults={'selling_price': 10.0, 'reorder_level': 10, 'dispensing_unit': 'tablets'}
    )

    # 3. Create Patient and Pregnancy
    patient, _ = Patient.objects.get_or_create(first_name='Pregnancy', last_name='Tester')
    pregnancy, _ = Pregnancy.objects.get_or_create(
        patient=patient,
        defaults={
            'lmp': timezone.now().date(),
            'edd': timezone.now().date(),
            'status': 'Active'
        }
    )

    # 4. Simulate POST request
    print(f"Testing dispensing for Pregnancy ID: {pregnancy.id}")
    client = Client()
    client.force_login(user)

    url = f'/maternity/pregnancy/{pregnancy.id}/'
    
    data = {
        'dispense_medication': '1',
        'medication': med.id,
        'dose_count': 2,
        'frequency': 'Twice Daily',
        'quantity': 10,
        'instructions': 'Take with water'
    }

    response = client.post(url, data, follow=True)
    
    if response.status_code == 200:
        print("POST request successful (200 OK)")
    else:
        print(f"POST failed: {response.status_code}")
        
    # 5. Verify Prescription Created
    # Find active visit for today
    today = timezone.now().date()
    visit = Visit.objects.filter(patient=patient, visit_date__date=today).last()
    
    if visit:
        print(f"Visit found/created: {visit}")
        prescription = Prescription.objects.filter(patient=patient, visit=visit).last()
        if prescription:
            print(f"Prescription found: {prescription}")
            item = PrescriptionItem.objects.filter(prescription=prescription, medication=med).last()
            if item:
                print(f"SUCCESS: Item '{item.medication.name}' recorded.")
                print(f"  - Qty: {item.quantity}")
                print(f"  - Freq: {item.frequency}")
            else:
                print("FAILED: PrescriptionItem not found.")
        else:
            print("FAILED: Prescription not created.")
    else:
        print("FAILED: Visit not created.")

if __name__ == '__main__':
    run_test()
