import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import InventoryItem, StockRecord
from home.models import Departments

def check_stock():
    print("Checking stock for 'Syringe'...")
    items = InventoryItem.objects.filter(name__icontains='Syringe')
    if not items.exists():
        print("No item found with name containing 'Syringe'")
        return

    ph_dept = Departments.objects.filter(name='Pharmacy').first()
    print(f"Pharmacy Department: {ph_dept.name if ph_dept else 'NOT FOUND'}")

    for item in items:
        print(f"\nItem: {item.name} (ID: {item.id})")
        records = StockRecord.objects.filter(item=item)
        print(f"Total StockRecords in database: {records.count()}")
        
        total_pharmacy = 0
        for r in records:
            loc_name = r.current_location.name if r.current_location else "None"
            print(f"- [Record {r.id}] Location: {loc_name}, Qty: {r.quantity}, Expiry: {r.expiry_date}")
            if ph_dept and r.current_location == ph_dept:
                total_pharmacy += r.quantity
        
        print(f"Total available in Pharmacy department: {total_pharmacy}")

if __name__ == '__main__':
    check_stock()
