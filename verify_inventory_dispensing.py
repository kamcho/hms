import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from maternity.models import Pregnancy
from home.models import Patient, Visit, Departments
from inventory.models import InventoryItem, InventoryCategory, StockRecord, DispensedItem, StockAdjustment
from accounts.models import Invoice, InvoiceItem
from django.utils import timezone

User = get_user_model()

def run_test():
    print("Setting up test data for Inventory Dispensing...")
    # 1. Create User
    user, _ = User.objects.get_or_create(username='nurse_test', role='Nurse')
    if not user.check_password('testpass'):
        user.set_password('testpass')
        user.save()

    # 2. Create Inventory Item (Consumable)
    cat, _ = InventoryCategory.objects.get_or_create(name='Consumables')
    item, _ = InventoryItem.objects.get_or_create(
        name='Test Gloves', 
        category=cat,
        defaults={'selling_price': 50.0, 'reorder_level': 100, 'dispensing_unit': 'pairs'}
    )
    
    # 3. Create Stock Record
    dept, _ = Departments.objects.get_or_create(name='Maternity Ward')
    stock, _ = StockRecord.objects.get_or_create(
        item=item,
        batch_number='BATCH-GLOVES-001',
        defaults={
            'quantity': 100,
            'current_location': dept,
            'expiry_date': timezone.now().date() + timezone.timedelta(days=365)
        }
    )
    # Ensure sufficient stock
    stock.quantity = 200 # Set high to avoid running out during multiple tests
    stock.save()

    # 4. Create Patient and Pregnancy
    patient, _ = Patient.objects.get_or_create(first_name='Maternity', last_name='InventoryTest')
    pregnancy, _ = Pregnancy.objects.get_or_create(
        patient=patient,
        defaults={
            'lmp': timezone.now().date(),
            'edd': timezone.now().date(),
            'status': 'Active'
        }
    )

    # 5. Simulate POST request
    print(f"Testing inventory dispensing for Pregnancy ID: {pregnancy.id}")
    client = Client()
    client.force_login(user)

    url = f'/maternity/pregnancy/{pregnancy.id}/'
    
    data = {
        'dispense_inventory': '1',
        'item': item.id,
        'quantity': 5
    }

    response = client.post(url, data, follow=True)
    
    if response.status_code == 200:
        print("POST request successful (200 OK)")
    else:
        print(f"POST failed: {response.status_code}")
        
    # 6. Verify Logic
    
    # Check DispensedItem
    d_item = DispensedItem.objects.filter(patient=patient, item=item).last()
    if d_item:
        print(f"SUCCESS: DispensedItem created: {d_item}")
        if d_item.quantity == 5:
            print("  - Quantity Correct (5)")
        else:
            print(f"  - Quantity Incorrect: {d_item.quantity}")
    else:
        print("FAILED: DispensedItem not created.")

    # Check Stock Deduction
    stock.refresh_from_db()
    print(f"Remaining Stock: {stock.quantity}")

    # Check Stock Adjustment
    adj = StockAdjustment.objects.filter(item=item, quantity=-5).last()
    if adj:
        print(f"SUCCESS: StockAdjustment created: {adj}")
    else:
        print("FAILED: StockAdjustment not created.")

    # Check Invoice
    today = timezone.now().date()
    visit = Visit.objects.filter(patient=patient, visit_date__date=today).last()
    if visit:
        invoice = Invoice.objects.filter(visit=visit).last()
        if invoice:
            inv_item = InvoiceItem.objects.filter(invoice=invoice, inventory_item=item).last()
            if inv_item:
                print(f"SUCCESS: InvoiceItem created: {inv_item.name} - {inv_item.amount}")
            else:
                print("FAILED: InvoiceItem not found.")
        else:
            print("FAILED: Invoice not found.")
    else:
        print("FAILED: Visit not found.")

if __name__ == '__main__':
    run_test()
