
import os
import django
import sys
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # Not needed if I run from project root
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hms.settings")
django.setup()

from django.contrib.auth import get_user_model
from home.models import Departments
from inventory.models import InventoryItem, StockRecord, InventoryCategory, StockAdjustment
from django.utils import timezone
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib import messages
from django.http import HttpRequest

User = get_user_model()
admin = User.objects.filter(is_superuser=True).first()
if not admin:
  admin = User.objects.create_superuser('admin', 'admin@example.com', 'admin')

# 1. Create Departments
source_dept, _ = Departments.objects.get_or_create(name='Source Dept')
dest_dept, _ = Departments.objects.get_or_create(name='Dest Dept')

cat, _ = InventoryCategory.objects.get_or_create(name='Test Category')
item, _ = InventoryItem.objects.get_or_create(
    name="Transfer Item",
    defaults={'selling_price': 100, 'category': cat, 'dispensing_unit': 'Unit'}
)

# Clean previous test
StockRecord.objects.filter(item=item).delete()
StockAdjustment.objects.filter(item=item).delete()

# 2. Add Stock to Source
StockRecord.objects.create(
    item=item, quantity=50, current_location=source_dept, batch_number='BATCH_A', expiry_date='2030-01-01', supplier=None
)

print(f"Initial Source: {StockRecord.objects.filter(item=item, current_location=source_dept).first().quantity}")

# 3. Request Transfer
from inventory.views import transfer_stock

# Mock Request
class MockRequest(HttpRequest):
    def __init__(self):
        super().__init__()
        self.method = 'POST'
        self.POST = {
            'item': item.id,
            'source_location': source_dept.id,
            'destination_location': dest_dept.id,
            'quantity': 20,
            'batch_number': ''
        }
        self.user = admin
        self._messages = FallbackStorage(self)

request = MockRequest()

# 4. Execute
print("Executing Transfer...")
# We need to ensure import works inside the view, so we call it directly
try:
    response = transfer_stock(request)
    if response.status_code == 302:
        print("Redirected successfully (Likely Success)")
    else:
        print(f"Status Code: {response.status_code}")
except Exception as e:
    print(f"Error: {e}")

# 5. Verify
source_stock = StockRecord.objects.filter(item=item, current_location=source_dept).first()
dest_stock = StockRecord.objects.filter(item=item, current_location=dest_dept).first()

print(f"Final Source: {source_stock.quantity if source_stock else 0}")
print(f"Final Dest: {dest_stock.quantity if dest_stock else 0}")

if (source_stock and source_stock.quantity == 30) and (dest_stock and dest_stock.quantity == 20):
    print("PASS: Stock correctly transferred.")
else:
    print("FAIL: Stock transfer logic incorrect.")
