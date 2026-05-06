import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import StockRecord

depts = [32, 35, 37, 48]
for d_id in depts:
    print(f"\nDepartment ID {d_id} Stock:")
    for s in StockRecord.objects.filter(current_location_id=d_id):
        print(f"Item: {s.item.name} (ID: {s.item_id}), Qty: {s.quantity}")
