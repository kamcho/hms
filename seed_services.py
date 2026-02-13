import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Departments
from accounts.models import Service

def seed_services():
    services_data = [
        {'dept': 'Reception', 'name': 'Patient Registration', 'cat': 'Other', 'price': 500.00},
        {'dept': 'Consultation', 'name': 'General Consultation', 'cat': 'Consultation', 'price': 1000.00},
        {'dept': 'Consultation', 'name': 'Specialist Consultation', 'cat': 'Consultation', 'price': 2500.00},
        {'dept': 'Lab', 'name': 'Full Blood Count', 'cat': 'Lab', 'price': 800.00},
        {'dept': 'Lab', 'name': 'Malaria Test', 'cat': 'Lab', 'price': 400.00},
        {'dept': 'Lab', 'name': 'Urinalysis', 'cat': 'Lab', 'price': 300.00},
        {'dept': 'Imaging', 'name': 'X-Ray Chest', 'cat': 'Imaging', 'price': 1500.00},
        {'dept': 'Imaging', 'name': 'Ultrasound Abdomen', 'cat': 'Imaging', 'price': 2000.00},
        {'dept': 'Inpatient', 'name': 'General Ward Bed (Daily)', 'cat': 'Admission', 'price': 1200.00},
        {'dept': 'Inpatient', 'name': 'Private Room (Daily)', 'cat': 'Admission', 'price': 5000.00},
        {'dept': 'Pharmacy', 'name': 'Dispensing Fee', 'cat': 'Pharmacy', 'price': 100.00},
        {'dept': 'Morgue', 'name': 'Daily Storage Fee', 'cat': 'Mortuary', 'price': 1000.00},
        {'dept': 'Morgue', 'name': 'Embalming', 'cat': 'Mortuary', 'price': 5000.00},
    ]

    print("Cleaning existing services...")
    Service.objects.all().delete()

    print("Seeding hospital services...")
    for item in services_data:
        try:
            dept = Departments.objects.get(name=item['dept'])
            service, created = Service.objects.get_or_create(
                name=item['name'],
                department=dept,
                defaults={
                    'price': item['price'],
                    'is_active': True
                }
            )
            if created:
                print(f"Created service: {service.name} in {dept.name}")
            else:
                print(f"Service already exists: {service.name}")
        except Departments.DoesNotExist:
            print(f"Error: Department '{item['dept']}' not found. Please run seed_departments.py first.")

    print("Service seeding completed!")

if __name__ == "__main__":
    seed_services()
