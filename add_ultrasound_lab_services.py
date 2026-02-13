import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Departments
from accounts.models import Service
from django.db.models import Q

def add_services():
    try:
        imaging_dept = Departments.objects.get(name='Imaging')
        lab_dept = Departments.objects.get(name='Lab')
    except Departments.DoesNotExist as e:
        print(f"Error: {e}")
        return

    # 1. Ultrasound Services (Imaging)
    us_services = [
        ("Ultrasound Obstetric", 2000),
        ("Ultrasound Pelvic", 1500),
        ("Ultrasound Abdominal", 2000),
        ("Ultrasound Breast", 1500),
        ("Ultrasound Breast (Bilateral)", 2500),
        ("Ultrasound KUB", 2000),
        ("Ultrasound Cardiac", 3000),
        ("Ultrasound Thyroid", 1500),
        ("Ultrasound Testicular & Scrotum", 1500),
        ("Ultrasound Skin/Abscess", 1000),
        ("Ultrasound Prostate", 1500),
        ("Ultrasound Thoracic", 2000),
        ("Ultrasound Abdomino-Pelvic", 3000),
    ]

    print("\nAdding Ultrasound Services (Imaging Dept)...")
    for name, price in us_services:
        Service.objects.get_or_create(
            name=name,
            defaults={
                'department': imaging_dept,
                'price': price,
                'is_active': True
            }
        )
        print(f" - {name}")

    # 2. Laboratory Tests (Lab)
    lab_services = [
        ("PITC", 100),
        ("Sputum for AAFBS", 200),
        ("Malaria parasites (mps) BS", 200),
        ("Haemoglobin level (HB)", 150),
        ("Stool for ova and cysts (OC)", 150),
        ("Urinalysis", 200),
        ("Blood grouping", 500),
        ("Widal test", 300),
        ("Salmonella Typhi (SSAT)", 500),
        ("VDRL", 300),
        ("ASOT", 400),
        ("Pregnancy test (HCG)", 200),
        ("Random Blood Sugar (RBS)", 100),
        ("Brucellosis test (BAT)", 400),
        ("Rheumatoid factor (RF) test", 500),
        ("Fasting Blood Sugar (FBS)", 100),
        ("Bilirubin test", 400),
        ("Urea test", 400),
        ("Sputum test", 200),
        ("DCT", 300),
        ("ESR", 200),
        ("ANC Profile", 1500),
        ("Full Haemogram (FHG)", 500),
        ("Liver function test (LFT)", 1500),
        ("Cross match", 1000),
        ("H.Pylori AB Test", 500),
        ("H.Pylori AG Test", 800),
        ("Rhesus", 200),
        ("Sickling test", 300),
        ("Gram stain", 200),
        ("Hepatitis B Surface Antigen (HBsAg)", 500),
    ]

    print("\nAdding Laboratory Services (Lab Dept)...")
    for name, price in lab_services:
        # Check if exists first to avoid duplicates if name varies slightly
        if not Service.objects.filter(name__iexact=name).exists():
            Service.objects.create(
                name=name,
                department=lab_dept,
                price=price,
                is_active=True
            )
            print(f" - {name}")
        else:
            print(f" - {name} (Already exists)")

    print("\nDone.")

if __name__ == '__main__':
    add_services()
