import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import InventoryRequest, StockRecord
from home.models import Departments

def investigate():
    print("--- Departments Check ---")
    depts = [d.name for d in Departments.objects.all()]
    print(f"Departments in DB: {depts}")
    main_store = Departments.objects.filter(name='Main Store').first()
    print(f"Main Store found: {main_store is not None}")
    
    print("\n--- Pending Inventory Requests ---")
    pending = InventoryRequest.objects.filter(status='Pending')
    print(f"Count: {pending.count()}")
    for r in pending:
        print(f"Request {r.id}: {r.item.name} x{r.quantity} for {r.location.name}")
        # Check Main Store stock for this item
        if main_store:
            stock = StockRecord.objects.filter(item=r.item, current_location=main_store).aggregate(django.db.models.Sum('quantity'))['quantity__sum'] or 0
            print(f"  - Available in Main Store: {stock}")

if __name__ == '__main__':
    investigate()
