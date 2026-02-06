import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import Supplier, InventoryCategory, InventoryItem, StockRecord, StockAdjustment
from users.models import User

def verify_inventory():
    print("Starting verification of inventory models...")
    
    # 1. Create a category
    cat, created = InventoryCategory.objects.get_or_create(name="Medicines", description="All medicinal items")
    print(f"Category: {cat} (Created: {created})")
    
    # 2. Create a supplier
    sup, created = Supplier.objects.get_or_create(name="PharmaCorp", email="info@pharmacorp.com")
    print(f"Supplier: {sup} (Created: {created})")
    
    # 3. Create an item
    item, created = InventoryItem.objects.get_or_create(
        name="Paracetamol 500mg",
        category=cat,
        unit="Tablets",
        reorder_level=100
    )
    print(f"Item: {item} (Created: {created})")
    
    # 4. Create a stock record
    stock, created = StockRecord.objects.get_or_create(
        item=item,
        batch_number="BATCH-001",
        quantity=500,
        supplier=sup,
        purchase_price=0.50
    )
    print(f"Stock Record: {stock} (Created: {created})")
    
    # 5. Create an adjustment
    user = User.objects.filter(is_superuser=True).first()
    if not user:
        user = User.objects.get_or_create(username="admin", email="admin@test.com")[0]
        
    adj = StockAdjustment.objects.create(
        item=item,
        quantity=-10,
        adjustment_type="Usage",
        reason="Dispensed to patient",
        adjusted_by=user
    )
    print(f"Adjustment: {adj}")
    
    print("Verification complete!")

if __name__ == "__main__":
    verify_inventory()
