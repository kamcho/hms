import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import StockRecord, InventoryItem
from home.models import Departments
from django.db.models import Sum

print("=== PHARMACY DEPARTMENTS ===")
for d in Departments.objects.filter(name__icontains='pharm'):
    print(f"  {d.name} (ID: {d.id})")

print("\n=== CHECKING ITEMS 418, 197, 208, 270 ===")
for item_id in [418, 197, 208, 270]:
    item = InventoryItem.objects.filter(pk=item_id).first()
    if item:
        print(f"\nItem {item_id}: {item.name}")
        recs = StockRecord.objects.filter(item=item)
        if recs.exists():
            for r in recs:
                print(f"  Location: {r.current_location.name} (ID:{r.current_location_id}), Qty: {r.quantity}, Batch: {r.batch_number}")
            total = recs.aggregate(total=Sum('quantity'))['total'] or 0
            print(f"  TOTAL STOCK: {total}")
        else:
            print("  NO STOCK RECORDS FOUND")
    else:
        print(f"\nItem {item_id}: DOES NOT EXIST in InventoryItem table")

print("\n=== ALL ITEMS WITH 'ferrous' or 'folic' or 'lesso' in name ===")
for item in InventoryItem.objects.filter(name__icontains='ferrous'):
    total = StockRecord.objects.filter(item=item).aggregate(t=Sum('quantity'))['t'] or 0
    print(f"  ID:{item.id} - {item.name} - Total Stock: {total}")
for item in InventoryItem.objects.filter(name__icontains='folic'):
    total = StockRecord.objects.filter(item=item).aggregate(t=Sum('quantity'))['t'] or 0
    print(f"  ID:{item.id} - {item.name} - Total Stock: {total}")
for item in InventoryItem.objects.filter(name__icontains='lesso'):
    total = StockRecord.objects.filter(item=item).aggregate(t=Sum('quantity'))['t'] or 0
    print(f"  ID:{item.id} - {item.name} - Total Stock: {total}")
