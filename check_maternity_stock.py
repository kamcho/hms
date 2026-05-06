import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import StockRecord

ids = [418, 197]
for item_id in ids:
    print(f"\nItem ID {item_id}:")
    stocks = StockRecord.objects.filter(item_id=item_id)
    if not stocks:
        print("  - No stock records found.")
    for s in stocks:
        print(f"  - Location: {s.current_location.name} (ID: {s.current_location.id}), Qty: {s.quantity}")
