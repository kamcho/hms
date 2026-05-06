import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import InventoryItem

with open('all_items.txt', 'w') as f:
    for item in InventoryItem.objects.all().order_by('id'):
        f.write(f"{item.id}: {item.name}\n")
