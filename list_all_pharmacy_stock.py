import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import StockRecord

print("Pharmacy (ID 23) Stock:")
for s in StockRecord.objects.filter(current_location_id=23):
    print(f"Item: {s.item.name} (ID: {s.item_id}), Qty: {s.quantity}")

print("\nMini Pharmacy (ID 49) Stock:")
for s in StockRecord.objects.filter(current_location_id=49):
    print(f"Item: {s.item.name} (ID: {s.item_id}), Qty: {s.quantity}")

print("\nMini Pharmacy (ID 42) Stock:")
for s in StockRecord.objects.filter(current_location_id=42):
    print(f"Item: {s.item.name} (ID: {s.item_id}), Qty: {s.quantity}")
