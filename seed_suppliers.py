import os
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import Supplier

def seed_suppliers():
    print("Seeding realistic hospital suppliers...")

    suppliers = [
        {
            "name": "Global Pharma Solutions",
            "contact_person": "Sarah Johnson",
            "phone": "+254 711 000 111",
            "email": "sales@globalpharma.com",
            "address": "Industrial Area, Nairobi, Kenya"
        },
        {
            "name": "MediEquip Africa Ltd",
            "contact_person": "David Kamau",
            "phone": "+254 722 000 222",
            "email": "support@mediequip.co.ke",
            "address": "Westlands, Nairobi, Kenya"
        },
        {
            "name": "Biotech Diagnostics",
            "contact_person": "Grace Wambui",
            "phone": "+254 733 000 333",
            "email": "orders@biotechdiag.com",
            "address": "Upper Hill, Nairobi, Kenya"
        },
        {
            "name": "Surgical Specialists Int.",
            "contact_person": "Dr. Michael Chen",
            "phone": "+254 788 000 444",
            "email": "logistics@surgicalspecialists.com",
            "address": "Medical Park, Nairobi, Kenya"
        },
        {
            "name": "CareOne Healthcare Supplies",
            "contact_person": "Mercy Otieno",
            "phone": "+254 755 000 555",
            "email": "info@careone.co.ke",
            "address": "Mombasa Road, Nairobi, Kenya"
        },
        {
            "name": "Radiology Direct",
            "contact_person": "Peter Ndung'u",
            "phone": "+254 766 000 666",
            "email": "sales@radiologydirect.com",
            "address": "Business Center, Nairobi, Kenya"
        }
    ]

    for supplier_data in suppliers:
        supplier, created = Supplier.objects.get_or_create(
            name=supplier_data["name"],
            defaults={
                "contact_person": supplier_data["contact_person"],
                "phone": supplier_data["phone"],
                "email": supplier_data["email"],
                "address": supplier_data["address"]
            }
        )
        if created:
            print(f"✓ Created Supplier: {supplier_data['name']}")
        else:
            print(f"| Supplier exists: {supplier_data['name']}")

    print("\nSupplier seeding complete!")

if __name__ == "__main__":
    seed_suppliers()
