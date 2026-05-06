import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import StockRecord

print("Main Store (ID 28) Stock:")
for s in StockRecord.objects.filter(current_location_id=28):
    print(f"Item: {s.item.name} (ID: {s.item_id}), Qty: {s.quantity}")
