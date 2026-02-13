import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Departments
from accounts.models import Service, Procedure, InvoiceItem
from django.db import transaction

def migrate_procedures():
    with transaction.atomic():
        print("Ensuring 'Procedure Room' department exists...")
        proc_dept, _ = Departments.objects.get_or_create(
            name='Procedure Room',
            defaults={'abbreviation': 'PROC'}
        )
        print(f"Using department: {proc_dept.name}")

        procedures = Procedure.objects.all()
        print(f"Found {procedures.count()} procedures to migrate.")

        for proc in procedures:
            # Check if a service with the same name already exists in Procedure Room
            service, s_created = Service.objects.get_or_create(
                name=proc.name,
                department=proc_dept,
                defaults={
                    'price': proc.price,
                    'is_active': proc.is_active,
                }
            )
            
            if s_created:
                print(f"Migrated procedure '{proc.name}' to Service in Procedure Room.")
            else:
                # Update price if it exists but might be different? 
                # (Optional, but let's stick to get_or_create logic)
                print(f"Service '{proc.name}' already exists in Procedure Room.")

            # Update InvoiceItems that point to this Procedure
            items_to_update = InvoiceItem.objects.filter(procedure=proc)
            count = items_to_update.count()
            if count > 0:
                items_to_update.update(service=service)
                print(f"Updated {count} InvoiceItem records for '{proc.name}'.")

        print("Migration completed successfully!")

if __name__ == "__main__":
    migrate_procedures()
