import os
import django
import random
from datetime import datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inventory.models import InventoryItem, InventoryCategory, Supplier, StockRecord
from home.models import Departments

# Create categories
categories_data = [
    ('Medications', 'Pharmaceutical drugs and medicines'),
    ('Medical Supplies', 'General medical supplies and consumables'),
    ('Laboratory', 'Laboratory equipment and supplies'),
    ('Surgical', 'Surgical instruments and supplies'),
    ('Equipment', 'Medical equipment and devices'),
    ('Personal Protective Equipment', 'PPE and safety equipment'),
    ('Cleaning Supplies', 'Cleaning and sanitation products'),
]

categories = {}
for name, desc in categories_data:
    cat, _ = InventoryCategory.objects.get_or_create(name=name, defaults={'description': desc})
    categories[name] = cat

# Create suppliers
suppliers_data = [
    ('MedSupply Co.', 'John Smith', '555-0101', 'orders@medsupply.com'),
    ('HealthCare Distributors', 'Jane Doe', '555-0102', 'sales@healthcare.com'),
    ('Pharma Direct', 'Bob Johnson', '555-0103', 'info@pharmadirect.com'),
    ('Surgical Solutions', 'Alice Brown', '555-0104', 'contact@surgicalsolutions.com'),
    ('Lab Equipment Inc.', 'Charlie Davis', '555-0105', 'sales@labequip.com'),
]

suppliers = []
for name, contact, phone, email in suppliers_data:
    supplier, _ = Supplier.objects.get_or_create(
        name=name,
        defaults={'contact_person': contact, 'phone': phone, 'email': email}
    )
    suppliers.append(supplier)

# Get all departments
departments = list(Departments.objects.all())

# Create 100 inventory items with stock records
items_data = [
    # Medications (30 items)
    ('Paracetamol 500mg', 'Medications', 'Tablets', 50.00),
    ('Ibuprofen 400mg', 'Medications', 'Tablets', 45.00),
    ('Amoxicillin 250mg', 'Medications', 'Capsules', 120.00),
    ('Metformin 500mg', 'Medications', 'Tablets', 80.00),
    ('Aspirin 75mg', 'Medications', 'Tablets', 35.00),
    ('Omeprazole 20mg', 'Medications', 'Capsules', 95.00),
    ('Atorvastatin 10mg', 'Medications', 'Tablets', 110.00),
    ('Ciprofloxacin 500mg', 'Medications', 'Tablets', 150.00),
    ('Diazepam 5mg', 'Medications', 'Tablets', 200.00),
    ('Morphine 10mg/ml', 'Medications', 'ml', 500.00),
    ('Insulin Glargine', 'Medications', 'Units', 350.00),
    ('Salbutamol Inhaler', 'Medications', 'Pieces', 180.00),
    ('Prednisolone 5mg', 'Medications', 'Tablets', 75.00),
    ('Warfarin 5mg', 'Medications', 'Tablets', 90.00),
    ('Clopidogrel 75mg', 'Medications', 'Tablets', 130.00),
    ('Amlodipine 5mg', 'Medications', 'Tablets', 70.00),
    ('Losartan 50mg', 'Medications', 'Tablets', 85.00),
    ('Simvastatin 20mg', 'Medications', 'Tablets', 95.00),
    ('Furosemide 40mg', 'Medications', 'Tablets', 60.00),
    ('Levothyroxine 100mcg', 'Medications', 'Tablets', 100.00),
    ('Ranitidine 150mg', 'Medications', 'Tablets', 55.00),
    ('Ceftriaxone 1g', 'Medications', 'Vials', 250.00),
    ('Gentamicin 80mg', 'Medications', 'Vials', 180.00),
    ('Dexamethasone 4mg', 'Medications', 'ml', 120.00),
    ('Epinephrine 1mg/ml', 'Medications', 'ml', 300.00),
    ('Atropine 0.5mg', 'Medications', 'ml', 150.00),
    ('Lidocaine 2%', 'Medications', 'ml', 80.00),
    ('Heparin 5000 IU', 'Medications', 'ml', 200.00),
    ('Dopamine 200mg', 'Medications', 'ml', 280.00),
    ('Norepinephrine 4mg', 'Medications', 'ml', 320.00),
    
    # Medical Supplies (25 items)
    ('Disposable Syringes 5ml', 'Medical Supplies', 'Pieces', 2.50),
    ('Disposable Syringes 10ml', 'Medical Supplies', 'Pieces', 3.00),
    ('IV Cannula 18G', 'Medical Supplies', 'Pieces', 5.00),
    ('IV Cannula 20G', 'Medical Supplies', 'Pieces', 4.50),
    ('IV Cannula 22G', 'Medical Supplies', 'Pieces', 4.00),
    ('IV Giving Set', 'Medical Supplies', 'Pieces', 8.00),
    ('Blood Collection Tubes EDTA', 'Medical Supplies', 'Pieces', 1.50),
    ('Blood Collection Tubes Plain', 'Medical Supplies', 'Pieces', 1.20),
    ('Urine Collection Containers', 'Medical Supplies', 'Pieces', 0.80),
    ('Specimen Containers', 'Medical Supplies', 'Pieces', 0.60),
    ('Cotton Wool 500g', 'Medical Supplies', 'Packs', 12.00),
    ('Gauze Swabs 10x10cm', 'Medical Supplies', 'Packs', 8.00),
    ('Adhesive Bandages', 'Medical Supplies', 'Boxes', 15.00),
    ('Elastic Bandage 10cm', 'Medical Supplies', 'Pieces', 6.00),
    ('Crepe Bandage 15cm', 'Medical Supplies', 'Pieces', 7.50),
    ('Surgical Tape 2.5cm', 'Medical Supplies', 'Rolls', 4.00),
    ('Alcohol Swabs', 'Medical Supplies', 'Boxes', 10.00),
    ('Thermometer Probe Covers', 'Medical Supplies', 'Boxes', 12.00),
    ('Tongue Depressors', 'Medical Supplies', 'Boxes', 5.00),
    ('Examination Gloves Medium', 'Medical Supplies', 'Boxes', 18.00),
    ('Examination Gloves Large', 'Medical Supplies', 'Boxes', 18.00),
    ('Catheter Foley 16Fr', 'Medical Supplies', 'Pieces', 15.00),
    ('Catheter Foley 18Fr', 'Medical Supplies', 'Pieces', 16.00),
    ('Nasogastric Tube 14Fr', 'Medical Supplies', 'Pieces', 12.00),
    ('Oxygen Mask Adult', 'Medical Supplies', 'Pieces', 8.00),
    
    # Laboratory (15 items)
    ('Blood Glucose Test Strips', 'Laboratory', 'Boxes', 45.00),
    ('Urine Dipsticks', 'Laboratory', 'Boxes', 35.00),
    ('Microscope Slides', 'Laboratory', 'Boxes', 20.00),
    ('Cover Slips', 'Laboratory', 'Boxes', 15.00),
    ('Pipette Tips 200μl', 'Laboratory', 'Boxes', 25.00),
    ('Pipette Tips 1000μl', 'Laboratory', 'Boxes', 28.00),
    ('Petri Dishes', 'Laboratory', 'Packs', 30.00),
    ('Culture Media Agar', 'Laboratory', 'Bottles', 40.00),
    ('Gram Stain Kit', 'Laboratory', 'Kits', 55.00),
    ('Blood Culture Bottles', 'Laboratory', 'Pieces', 12.00),
    ('Centrifuge Tubes 15ml', 'Laboratory', 'Packs', 22.00),
    ('Centrifuge Tubes 50ml', 'Laboratory', 'Packs', 28.00),
    ('Laboratory Reagents Set', 'Laboratory', 'Sets', 150.00),
    ('pH Test Strips', 'Laboratory', 'Boxes', 18.00),
    ('Distilled Water 5L', 'Laboratory', 'Bottles', 10.00),
    
    # Surgical (15 items)
    ('Surgical Blade #10', 'Surgical', 'Pieces', 3.00),
    ('Surgical Blade #15', 'Surgical', 'Pieces', 3.00),
    ('Surgical Blade #22', 'Surgical', 'Pieces', 3.00),
    ('Suture Silk 2-0', 'Surgical', 'Pieces', 8.00),
    ('Suture Nylon 3-0', 'Surgical', 'Pieces', 9.00),
    ('Suture Vicryl 2-0', 'Surgical', 'Pieces', 12.00),
    ('Surgical Drapes Sterile', 'Surgical', 'Pieces', 15.00),
    ('Surgical Gowns Large', 'Surgical', 'Pieces', 20.00),
    ('Surgical Masks', 'Surgical', 'Boxes', 25.00),
    ('Surgical Caps', 'Surgical', 'Boxes', 18.00),
    ('Scalpel Handles #3', 'Surgical', 'Pieces', 35.00),
    ('Forceps Artery 6"', 'Surgical', 'Pieces', 45.00),
    ('Scissors Mayo 6"', 'Surgical', 'Pieces', 40.00),
    ('Needle Holders 6"', 'Surgical', 'Pieces', 50.00),
    ('Retractors Weitlaner', 'Surgical', 'Pieces', 65.00),
    
    # Equipment (10 items)
    ('Stethoscope Adult', 'Equipment', 'Pieces', 250.00),
    ('Blood Pressure Monitor Digital', 'Equipment', 'Pieces', 450.00),
    ('Pulse Oximeter', 'Equipment', 'Pieces', 350.00),
    ('Thermometer Digital', 'Equipment', 'Pieces', 120.00),
    ('Otoscope', 'Equipment', 'Pieces', 800.00),
    ('Ophthalmoscope', 'Equipment', 'Pieces', 900.00),
    ('Nebulizer Machine', 'Equipment', 'Pieces', 1200.00),
    ('Wheelchair Standard', 'Equipment', 'Pieces', 3500.00),
    ('Walking Frame', 'Equipment', 'Pieces', 800.00),
    ('Crutches Pair', 'Equipment', 'Pieces', 450.00),
    
    # PPE (3 items)
    ('N95 Respirator Masks', 'Personal Protective Equipment', 'Boxes', 80.00),
    ('Face Shields', 'Personal Protective Equipment', 'Pieces', 15.00),
    ('Protective Gowns', 'Personal Protective Equipment', 'Pieces', 25.00),
    
    # Cleaning Supplies (2 items)
    ('Hand Sanitizer 5L', 'Cleaning Supplies', 'Bottles', 45.00),
    ('Disinfectant Solution 5L', 'Cleaning Supplies', 'Bottles', 35.00),
]

print(f"Creating {len(items_data)} inventory items with stock records...")

for item_name, category_name, unit, price in items_data:
    # Create inventory item
    item, created = InventoryItem.objects.get_or_create(
        name=item_name,
        defaults={
            'category': categories[category_name],
            'unit': unit,
            'reorder_level': random.randint(10, 50),
            'selling_price': price
        }
    )
    
    if created:
        # Create 1-3 stock records for this item across different departments
        num_stocks = random.randint(1, 3)
        selected_depts = random.sample(departments, min(num_stocks, len(departments)))
        
        for dept in selected_depts:
            batch_num = f"BATCH-{datetime.now().year}-{random.randint(1000, 9999)}"
            quantity = random.randint(50, 500)
            expiry_days = random.randint(180, 1095)  # 6 months to 3 years
            expiry_date = datetime.now().date() + timedelta(days=expiry_days)
            purchase_price = price * 0.6  # 60% of selling price
            
            StockRecord.objects.create(
                item=item,
                batch_number=batch_num,
                quantity=quantity,
                expiry_date=expiry_date,
                supplier=random.choice(suppliers),
                purchase_price=purchase_price,
                current_location=dept
            )

print("✓ Inventory population complete!")
print(f"Total items created: {InventoryItem.objects.count()}")
print(f"Total stock records created: {StockRecord.objects.count()}")
print("\nStock distribution by department:")
for dept in departments:
    count = StockRecord.objects.filter(current_location=dept).count()
    print(f"  {dept.name}: {count} stock records")
