import os
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import InventoryCategory, DrugClass

def seed_inventory_data():
    print("Seeding production-ready hospital inventory data...")

    # 1. Seed Inventory Categories
    categories = [
        ("Pharmaceuticals", "Tablets, capsules, syrups, and other medications."),
        ("Medical Consumables", "Syringes, gloves, bandages, and clinical disposables."),
        ("Laboratory Supplies", "Reagents, specimen containers, slides, and lab kits."),
        ("Surgical Instruments", "Scalpels, forceps, sutures, and theater equipment."),
        ("Radiology & Imaging", "X-ray films, contrast media, and imaging supplies."),
        ("Dental Supplies", "Dental composites, cements, and theater disposables."),
        ("Patient Care & Nursing", "Beddings, patient gowns, and ward supplies."),
        ("First Aid & Emergency", "Emergency kits, resuscitation supplies, and trauma care."),
        ("Housekeeping & Hygiene", "Disinfectants, soaps, and cleaning supplies."),
        ("Stationery & Admin", "Patient files, record books, and office supplies.")
    ]

    for name, description in categories:
        cat, created = InventoryCategory.objects.get_or_create(
            name=name,
            defaults={'description': description}
        )
        if created:
            print(f"✓ Created Category: {name}")
        else:
            print(f"| Category exists: {name}")

    # 2. Seed Drug Classes (Medication Classifications)
    drug_classes = [
        ("Antibiotics", "Drugs used to treat bacterial infections."),
        ("Antivirals", "Medications for viral infections."),
        ("Antifungals", "Treatments for fungal infections."),
        ("Analgesics", "Pain relief medications (e.g., NSAIDs, Opioids)."),
        ("Antipyretics", "Medications used to reduce fever."),
        ("Antihypertensives", "Drugs for high blood pressure management."),
        ("Antidiabetics", "Medications for blood sugar control."),
        ("Antihistamines", "Treatments for allergies and hay fever."),
        ("Anticoagulants", "Blood thinners to prevent clots."),
        ("Antidepressants", "Medications for mental health and mood disorders."),
        ("IV Fluids", "Intravenous solutions (e.g., Normal Saline, Dextrose)."),
        ("Vaccines", "Immunization and prophylactic treatments."),
        ("Vitamins & Supplements", "Micronutrients and nutritional boosters."),
        ("Topical Agents", "Creams, ointments, and skin treatments."),
        ("Anesthetics", "Drugs used to induce anesthesia.")
    ]

    for name, description in drug_classes:
        dc, created = DrugClass.objects.get_or_create(
            name=name,
            defaults={'description': description}
        )
        if created:
            print(f"✓ Created Drug Class: {name}")
        else:
            print(f"| Drug Class exists: {name}")

    print("\nSeeding complete! Hospital inventory is now production-ready.")

if __name__ == "__main__":
    seed_inventory_data()
