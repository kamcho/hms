import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from inventory.models import InventoryItem, InventoryCategory, StockRecord, StockAdjustment, DispensedItem
from home.models import Patient, Visit, Departments
from django.utils import timezone
from datetime import timedelta

User = get_user_model()

def run_test():
    # Setup Data
    print("Setting up test data...")
    user, _ = User.objects.get_or_create(id_number='test_dispenser', role='Nurse')
    if not user.check_password('testpass'):
        user.set_password('testpass')
        user.save()
    
    dept, _ = Departments.objects.get_or_create(name='Main Store') # Ensure Main Store exists
    
    cat, _ = InventoryCategory.objects.get_or_create(name='Consumables')
    item, _ = InventoryItem.objects.get_or_create(name='Test Syringe', category=cat, defaults={'reorder_level': 10, 'dispensing_unit': 'pcs', 'selling_price': 10.0})
    
    # Create Stock Records (FEFO test)
    # Batch A: Expires sooner, qty 10
    sr1, _ = StockRecord.objects.get_or_create(
        item=item, batch_number='BATCH-A', 
        defaults={
            'quantity': 10, 
            'current_location': dept,
            'expiry_date': timezone.now().date() + timedelta(days=30),
            'purchase_price': 5.0,
            'supplier': None
        }
    )
    sr1.quantity = 10
    sr1.expiry_date = timezone.now().date() + timedelta(days=30)
    sr1.save()
    
    # Batch B: Expires later, qty 20
    sr2, _ = StockRecord.objects.get_or_create(
        item=item, batch_number='BATCH-B', 
        defaults={
            'quantity': 20, 
            'current_location': dept,
            'expiry_date': timezone.now().date() + timedelta(days=60),
            'purchase_price': 5.0,
            'supplier': None
        }
    )
    sr2.quantity = 20
    sr2.expiry_date = timezone.now().date() + timedelta(days=60)
    sr2.save()
    
    print(f"Initial Stock: Batch A={sr1.quantity}, Batch B={sr2.quantity}")
    
    from datetime import date
    patient, _ = Patient.objects.get_or_create(
        id_number='test_patient_01', # Use id_number for uniqueness
        defaults={
            'first_name': 'Test', 
            'last_name': 'Patient', 
            'date_of_birth': date(2000, 1, 1), 
            'gender': 'M',
            'phone': '000000',
            'location': 'Test Loc'
        }
    )
    visit = Visit.objects.create(patient=patient, visit_type='IN-PATIENT')
    
    # Test Dispensing
    print("Dispensing 15 items...")
    client = Client()
    client.force_login(user)
    
    url = '/inventory/api/dispense/'
    data = {
        'item_id': item.id,
        'patient_id': patient.id,
        'visit_id': visit.id,
        'quantity': 15,
        'department_id': dept.id 
    }
    
    response = client.post(url, data)
    print(f"Response: {response.status_code} - {response.content.decode()}")
    
    if response.status_code != 200:
        print("FAILED: View returned error")
        return

    # Verify Results
    sr1.refresh_from_db()
    sr2.refresh_from_db()
    
    print(f"Final Stock: Batch A={sr1.quantity}, Batch B={sr2.quantity}")
    
    if sr1.quantity == 0 and sr2.quantity == 15:
        print("SUCCESS: Stock deducted correctly (FEFO).")
    else:
        print(f"FAILED: Stock deduction incorrect. Expected 0 and 15.")
        
    # Verify DispensedItem
    di = DispensedItem.objects.filter(visit=visit).first()
    if di and di.quantity == 15:
        print("SUCCESS: DispensedItem record created.")
    else:
        print("FAILED: DispensedItem record missing or incorrect.")
        
    # Verify StockAdjustment
    adj = StockAdjustment.objects.filter(item=item, quantity__lt=0).order_by('-pk')[:2]
    # Should have 2 adjustments: -5 and -10 (order depends on creation, likely -10 first then -5)
    print(f"Adjustments found: {[a.quantity for a in adj]}")

if __name__ == '__main__':
    run_test()
