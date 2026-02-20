import os
import django
from django.conf import settings
from django.utils import timezone
from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient, Visit, Departments
from inventory.models import InventoryItem, InventoryCategory, DispensedItem, StockRecord
from maternity.models import Pregnancy
from accounts.models import Invoice, InvoiceItem

User = get_user_model()

def verify_fix():
    print("Starting verification of Refined Dispense Fix...")
    
    # 1. Setup Data
    user, _ = User.objects.get_or_create(id_number='DOC002', defaults={'role': 'Doctor'})
    if not user.check_password('testpass'):
        user.set_password('testpass')
        user.save()
        
    dob = timezone.now().date() - timezone.timedelta(days=365*25)
    patient, _ = Patient.objects.get_or_create(first_name='Maternity', last_name='HistoryTest', defaults={'date_of_birth': dob, 'gender': 'Female'})
    
    pregnancy, _ = Pregnancy.objects.get_or_create(
        patient=patient,
        defaults={'lmp': timezone.now().date() - timezone.timedelta(days=100), 'edd': timezone.now().date() + timezone.timedelta(days=180), 'status': 'Active', 'gravida': 1, 'para': 0}
    )
    
    cat, _ = InventoryCategory.objects.get_or_create(name='Consumables')
    item, _ = InventoryItem.objects.get_or_create(
        name='Syringe 5ml',
        category=cat,
        defaults={'selling_price': 10.0, 'reorder_level': 10, 'dispensing_unit': 'pcs'}
    )
    
    pharmacy_dept, _ = Departments.objects.get_or_create(name='Pharmacy')
    StockRecord.objects.get_or_create(
        item=item,
        current_location=pharmacy_dept,
        defaults={'quantity': 500, 'batch_number': 'B001', 'expiry_date': timezone.now().date() + timezone.timedelta(days=365)}
    )
    
    today = timezone.now().date()
    # Ensure visit is the LATEST and ACTIVE
    Visit.objects.filter(patient=patient).update(is_active=False)
    visit = Visit.objects.create(
        patient=patient,
        visit_date=timezone.now(),
        is_active=True,
        visit_type='Maternity'
    )
    
    # 2. Test Billed Item (Doctor's Request)
    invoice = Invoice.objects.create(patient=patient, visit=visit, status='Pending', created_by=user)
    InvoiceItem.objects.create(
        invoice=invoice,
        inventory_item=item,
        name=item.name,
        unit_price=item.selling_price,
        quantity=3
    )
    print("Created mock Billed Item (InvoiceItem)")
    
    # 3. Check View Context
    client = Client()
    client.force_login(user)
    
    # Check Maternity View
    print("\nChecking Maternity History context...")
    url_mat = reverse('maternity:pregnancy_detail', kwargs={'pregnancy_id': pregnancy.id})
    response_mat = client.get(url_mat)
    
    if response_mat.status_code == 200:
        items = response_mat.context.get('dispensed_items', [])
        print(f"Items found in context: {len(items)}")
        if any(i['status'] == 'Billed/Pending' for i in items):
            print("SUCCESS: Billed item appears in maternity history.")
        else:
            print("FAILED: Billed item missing from maternity history.")
    else:
        print(f"FAILED: Maternity GET returned {response_mat.status_code}")

    # Check Prescription Create View
    print("\nChecking Prescription Create History context...")
    url_rx = reverse('home:create_prescription', kwargs={'visit_id': visit.id})
    response_rx = client.get(url_rx)
    
    if response_rx.status_code == 200:
        items = response_rx.context.get('dispensed_items', [])
        if any(i['status'] == 'Billed/Pending' for i in items):
            print("SUCCESS: Billed item appears in Prescription Create history.")
        else:
            print("FAILED: Billed item missing from Prescription Create history.")
    else:
        print(f"FAILED: Prescription Create GET returned {response_rx.status_code}")

    # 4. Test Visit Validation (Security Check)
    print("\nTesting Prescription Create with Inactive Visit...")
    visit.is_active = False
    visit.save()
    
    response_inactive = client.get(url_rx, follow=True)
    if any("already closed" in str(msg) for msg in response_inactive.context.get('messages', [])):
        print("SUCCESS: Inactive visit correctly rejected with message.")
    else:
        print("FAILED: Inactive visit was not rejected correctly.")
        
    print("\nTesting Prescription Create with Not-Latest Visit...")
    visit.is_active = True
    visit.save()
    Visit.objects.create(patient=patient, visit_type='OUT_PATIENT', is_active=True, visit_date=timezone.now() + timezone.timedelta(seconds=10)) # Newer visit
    response_not_latest = client.get(url_rx, follow=True)
    if any("previous visit" in str(msg) for msg in response_not_latest.context.get('messages', [])):
        print("SUCCESS: Non-latest visit correctly rejected.")
    else:
        print("FAILED: Non-latest visit was not rejected.")

    # 5. Test Invoice Consolidation
    print("\nTesting Invoice Consolidation (Consumable + Prescription)...")
    # New visit for clean test
    Visit.objects.filter(patient=patient).update(is_active=False)
    v2 = Visit.objects.create(patient=patient, visit_type='OUT_PATIENT', is_active=True, visit_date=timezone.now() + timezone.timedelta(seconds=20))
    
    # Dispense a consumable
    client.post(reverse('inventory:dispense_item'), {
        'item_id': item.id,
        'patient_id': patient.id,
        'visit_id': v2.id,
        'quantity': 5
    })
    
    inv_count_1 = Invoice.objects.filter(visit=v2).count()
    print(f"Invoices after consumable: {inv_count_1}")
    
    # Create a prescription
    url_v2 = reverse('home:create_prescription', kwargs={'visit_id': v2.id})
    client.post(url_v2, {
        'items-TOTAL_FORMS': '1',
        'items-INITIAL_FORMS': '0',
        'items-MIN_NUM_FORMS': '0',
        'items-MAX_NUM_FORMS': '1000',
        'items-0-medication': item.id,
        'items-0-quantity': 2,
        'items-0-dosage': '1x1',
        'items-0-duration': '3 days',
    })
    
    inv_count_2 = Invoice.objects.filter(visit=v2).count()
    print(f"Invoices after prescription: {inv_count_2}")
    
    if inv_count_2 == 1:
        print("SUCCESS: Invoice consolidated correctly.")
    else:
        print(f"FAILED: Expected 1 invoice, found {inv_count_2}")
        for inv in Invoice.objects.filter(visit=v2):
            print(f"- Invoice ID: {inv.id}, Notes: {inv.notes}")

    # 6. Test Physical Dispensation (Pharmacist)
    DispensedItem.objects.create(
        item=item,
        patient=patient,
        visit=v2,
        quantity=3,
        dispensed_by=user,
        department=pharmacy_dept
    )
    print("\nSimulated physical dispensation (DispensedItem created)")
    
    response_v2 = client.get(reverse('home:patient_detail', kwargs={'pk': patient.id}))
    if response_v2.status_code == 200:
        items = response_v2.context.get('dispensed_items', [])
        print(f"Items found in context: {len(items)}")
        dispensed_count = sum(1 for i in items if i['status'] == 'Dispensed')
        if dispensed_count >= 1:
            print("SUCCESS: Physical dispensation appears in history.")
        else:
            print("FAILED: Dispensed item missing from history.")

if __name__ == '__main__':
    verify_fix()
