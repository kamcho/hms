import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Departments

def seed_departments():
    # Standard departments to create
    departments_to_create = [
        {'name': 'Reception', 'abbreviation': 'REC'},
        {'name': 'Triage', 'abbreviation': 'TRI'},
        {'name': 'Consultation', 'abbreviation': 'CON'},
        {'name': 'Lab', 'abbreviation': 'LAB'},
        {'name': 'Pharmacy', 'abbreviation': 'PHARM'},
        {'name': 'Imaging', 'abbreviation': 'IMG'},
        {'name': 'Inpatient', 'abbreviation': 'IPD'},
        {'name': 'Morgue', 'abbreviation': 'MOR'},
        {'name': 'Accounts', 'abbreviation': 'ACC'},
        {'name': 'Main Store', 'abbreviation': 'MST'},
        {'name': 'ANC', 'abbreviation': 'ANC-MAT'},
        {'name': 'Procedure Room', 'abbreviation': 'INJ'},
        {'name': 'PNC', 'abbreviation': 'PNC=MAT'},
        {'name': 'CWC', 'abbreviation': 'CWC'},
        {'name': 'Maternity', 'abbreviation': 'MAT'},
        {'name': 'OPD', 'abbreviation': None},
        {'name': 'Consultation Room 2', 'abbreviation': 'CR2'},
        {'name': 'Consultation Room 1', 'abbreviation': 'CR1'},
    ]

    print("Deleting existing departments...")
    Departments.objects.all().delete()

    print("Creating standard departments...")
    for dept_data in departments_to_create:
        dept, created = Departments.objects.get_or_create(
            name=dept_data['name'],
            defaults={'abbreviation': dept_data['abbreviation']}
        )
        if created:
            print(f"Created department: {dept.name}")
        else:
            print(f"Department already exists: {dept.name}")

    print("Seeding completed successfully!")

if __name__ == "__main__":
    seed_departments()
