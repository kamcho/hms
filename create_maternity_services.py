import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Departments
from accounts.models import Service

def create_maternity_services():
    print("Checking and creating Maternity services...")

    # Ensure Departments exist
    anc_dept, _ = Departments.objects.get_or_create(name='ANC', defaults={'abbreviation': 'ANC'})
    pnc_dept, _ = Departments.objects.get_or_create(name='PNC', defaults={'abbreviation': 'PNC'})
    cwc_dept, _ = Departments.objects.get_or_create(name='CWC', defaults={'abbreviation': 'CWC'})
    mat_dept, _ = Departments.objects.get_or_create(name='Maternity', defaults={'abbreviation': 'MAT'})

    services_to_create = [
        {'name': 'ANC Profile', 'price': 1500, 'dept': anc_dept},
        {'name': 'ANC Follow-up', 'price': 500, 'dept': anc_dept},
        {'name': 'PNC Visit (Mother)', 'price': 1000, 'dept': pnc_dept},
        {'name': 'PNC Visit (Baby)', 'price': 500, 'dept': pnc_dept},
        {'name': 'CWC Immunization', 'price': 200, 'dept': cwc_dept},
        {'name': 'CWC Growth Monitoring', 'price': 100, 'dept': cwc_dept},
    ]

    for svc_data in services_to_create:
        service, created = Service.objects.get_or_create(
            name=svc_data['name'],
            defaults={
                'price': svc_data['price'],
                'department': svc_data['dept'],
                'is_active': True
            }
        )
        if created:
            print(f"Created Service: {service.name}")
        else:
            print(f"Service exists: {service.name} (Department: {service.department.name})")
            # Optional: Update department if it was wrong (e.g. generic Maternity)
            if service.department != svc_data['dept']:
                print(f"  -> Updating department from {service.department.name} to {svc_data['dept'].name}")
                service.department = svc_data['dept']
                service.save()

    print("Done.")

if __name__ == '__main__':
    create_maternity_services()
