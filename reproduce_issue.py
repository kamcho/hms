
import os
import django
from django.utils import timezone
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient, Visit, Departments
from maternity.models import Pregnancy
from inventory.models import InventoryItem, StockRecord, DispensedItem
from accounts.models import Invoice, InvoiceItem
from django.contrib.auth import get_user_model
from django.db.models import Prefetch, F

User = get_user_model()

def reproduction():
    print("Setting up reproduction...")
    # 1. Create User
    user, _ = User.objects.get_or_create(id_number='test_admin', role='Admin')

    # 2. Create Patient
    patient = Patient.objects.create(
        first_name='Maternity',
        last_name='Test',
        gender='F',
        date_of_birth=timezone.now().date() - timedelta(days=365*25),
        phone='1234567890',
        location='Test Loc'
    )
    print(f"Created Patient: {patient}")

    # 3. Create Pregnancy
    pregnancy = Pregnancy.objects.create(
        patient=patient,
        status='Active',
        lmp=timezone.now().date() - timedelta(days=90),
        edd=timezone.now().date() + timedelta(days=190),
        gravida=1,
        para=0,
        created_by=user
    )
    print(f"Created Pregnancy: {pregnancy}")

    # 4. Create Visit (OUT-PATIENT)
    visit = Visit.objects.create(
        patient=patient,
        visit_type='OUT-PATIENT',
        visit_mode='Walk In',
        is_active=True
    )
    print(f"Created Visit: {visit} (Type: {visit.visit_type})")

    # 5. Create Inventory Item & Stock
    from inventory.models import InventoryCategory
    category, _ = InventoryCategory.objects.get_or_create(name='Medicine')
    
    item = InventoryItem.objects.create(
        name='Test Med',
        selling_price=100,
        buying_price=80,
        category=category,
        dispensing_unit='Tablet'
    )
    
    dept, _ = Departments.objects.get_or_create(name='Pharmacy')
    
    StockRecord.objects.create(
        item=item,
        quantity=100,
        batch_number='BATCH001',
        expiry_date=timezone.now().date() + timedelta(days=365),
        current_location=dept
    )

    # 6. Simulate Dispense Logic (from maternity/views.py)
    # Using the logic found in dispense_inventory
    print("Simulating Dispense...")
    from accounts.utils import get_or_create_invoice

    # Dispense Item logic
    d_item_qty = 2
    
    # Update Stock
    stock_record = StockRecord.objects.filter(item=item).first()
    stock_record.quantity -= d_item_qty
    stock_record.save()
    
    # Create DispensedItem
    DispensedItem.objects.create(
        item=item,
        patient=patient,
        visit=visit,
        quantity=d_item_qty,
        dispensed_by=user,
        department=dept
    )
    
    # Create Invoice
    invoice = get_or_create_invoice(visit=visit, user=user)
    print(f"Created/Retrieved Invoice: {invoice} (Status: {invoice.status})")
    
    InvoiceItem.objects.create(
        invoice=invoice,
        inventory_item=item,
        name=item.name,
        unit_price=item.selling_price,
        quantity=d_item_qty
    )
    
    # 7. Check Reception Dashboard Query
    print("Checking Reception Dashboard Query...")
    
    reception_invoices = Invoice.objects.filter(
        status__in=['Pending', 'Partial', 'Draft'],
        visit__visit_type='OUT-PATIENT'
    ).select_related('patient', 'deceased')
    
    found = reception_invoices.filter(id=invoice.id).exists()
    
    if found:
        print("SUCCESS: Invoice IS visible in reception query.")
    else:
        print("FAILURE: Invoice is NOT visible in reception query.")
        # Debug why
        print(f"Invoice Status: {invoice.status}")
        print(f"Invoice Visit Type: {invoice.visit.visit_type}")
        print(f"Query Count: {reception_invoices.count()}")

    # 8. Test with IN-PATIENT
    print("\n--- Testing IN-PATIENT scenario ---")
    visit_in = Visit.objects.create(
        patient=patient,
        visit_type='IN-PATIENT',
        visit_mode='Walk In',
        is_active=True
    )
    print(f"Created IN-PATIENT Visit: {visit_in}")
    
    invoice_in = get_or_create_invoice(visit=visit_in, user=user)
    InvoiceItem.objects.create(
        invoice=invoice_in,
        inventory_item=item,
        name=item.name,
        unit_price=item.selling_price,
        quantity=d_item_qty
    )
    
    
    # 9. Verify Visit Type Defaults
    # If the user says "the visit was OPD", maybe the reception dashboard invoice list
    # has a strict filter that misses some edge case?
    # The filter is: status__in=['Pending', 'Partial', 'Draft'], visit__visit_type='OUT-PATIENT'
    
    print(f"\nInvoice ID {invoice.id} Status: {invoice.status}")
    print(f"Invoice Visit Type: {invoice.visit.visit_type}")
    
    # Check if 'Pending' is in the query list
    # The query is hardcoded in the view, so we just match it.
    
    if invoice.status not in ['Pending', 'Partial', 'Draft']:
        print("FAILURE: Invoice status is NOT Pending/Partial/Draft")
        
    if invoice.visit.visit_type != 'OUT-PATIENT':
        print("FAILURE: Invoice visit type is NOT OUT-PATIENT")


if __name__ == '__main__':
    reproduction()
