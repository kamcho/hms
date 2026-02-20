import os
import django
from django.conf import settings
from django.db.models import Q

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inpatient.models import InpatientConsumable, Admission
from accounts.models import InvoiceItem, Invoice
from inventory.models import DispensedItem

def debug_ipd_consumables():
    print("--- Debugging IPD Consumables Visibility ---")
    
    # 1. Check InpatientConsumable records (created in ward)
    print("\n[Step 1] Checking InpatientConsumable records (last 10)...")
    ipd_consumables = InpatientConsumable.objects.select_related('admission__patient', 'item').order_by('-prescribed_at')[:10]
    
    if not ipd_consumables.exists():
        print("No InpatientConsumable records found.")
    
    for ic in ipd_consumables:
        print(f"ID: {ic.id} | Item: {ic.item.name} | Patient: {ic.admission.patient.full_name}")
        print(f"  - Dispensed Status: {ic.is_dispensed}")
        print(f"  - Admission Status: {ic.admission.status}")
    
    # 2. Check general InvoiceItems for IPD patients
    print("\n[Step 2] Checking InvoiceItems for currently admitted patients...")
    admitted_visits = Admission.objects.filter(status='Admitted').values_list('visit_id', flat=True)
    
    current_ipd_items = InvoiceItem.objects.filter(
        invoice__visit__id__in=admitted_visits,
        inventory_item__isnull=False,
        inventory_item__medication__isnull=True
    ).select_related('invoice__patient', 'inventory_item')[:10]
    
    if not current_ipd_items.exists():
         print("No consumable InvoiceItems found for currently admitted patients.")
         
    for item in current_ipd_items:
        print(f"InvItem ID: {item.id} | Item: {item.inventory_item.name} | Patient: {item.invoice.patient.full_name}")
        print(f"  - Invoice Status: {item.invoice.status}")
        
    # 3. dry run the loop logic from view
    print("\n[Step 3] Dry running view logic...")
    
    # Mocking the list from view
    pending_consumables = InvoiceItem.objects.filter(
        inventory_item__isnull=False,
        inventory_item__medication__isnull=True, 
        invoice__status__in=['Draft', 'Pending', 'Paid', 'Partial'],
    )
    
    dispensed_keys = set()
    for d in DispensedItem.objects.all().values_list('visit_id', 'item_id', 'quantity'):
        dispensed_keys.add(d)

    pending_consumable_list = []
    for ci in pending_consumables:
        key = (ci.invoice.visit_id, ci.inventory_item_id, ci.quantity)
        if key not in dispensed_keys:
            pending_consumable_list.append(ci)
            
    print(f"Total Pending Consumables (InvoiceItems) passing first filter: {len(pending_consumable_list)}")
    
    # Simulated IPD filtering
    ipd_count = 0
    approved_ids = []
    for ci in pending_consumable_list:
        visit = ci.invoice.visit
        if not visit: continue
        is_ipd = Admission.objects.filter(visit=visit, status='Admitted').exists()
        if is_ipd:
            ipd_count += 1
            approved_ids.append(ci.id)
            
    print(f"Consumables matched to Active IPD Admission: {ipd_count}")
    if ipd_count == 0 and len(pending_consumable_list) > 0:
        print("  -> It seems none of the pending consumables matched an active 'Admitted' admission.")
        # Check one to see why
        sample = pending_consumable_list[0]
        print(f"  Sample Check: Item {sample.inventory_item.name} (Visit {sample.invoice.visit_id})")
        adm = Admission.objects.filter(visit=sample.invoice.visit).first()
        print(f"  Admission found? {adm} (Status: {adm.status if adm else 'None'})")

if __name__ == '__main__':
    debug_ipd_consumables()
