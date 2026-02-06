
import os
import django
from django.utils import timezone
from datetime import timedelta

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient, Visit, Departments
from inpatient.models import Ward, Bed, Admission
from morgue.models import Deceased, MorgueAdmission
from accounts.models import Service, Invoice, InvoiceItem, Payment
from users.models import User

def verify_discharge_billing():
    print("--- Verifying Discharge Billing ---")
    
    # 1. Setup Admin User
    admin, _ = User.objects.get_or_create(id_number="ADMIN_TEST", defaults={'role': 'Admin', 'is_staff': True, 'is_superuser': True})
    
    # 2. Setup Department and Service
    dept, _ = Departments.objects.get_or_create(name="Inpatient")
    service, _ = Service.objects.get_or_create(name="Consultation", defaults={'price': 1000, 'department': dept})
    
    # [Testing IPD Discharge...]
    print("\n[Testing IPD Discharge...]")
    patient, _ = Patient.objects.get_or_create(id_number="PAT001", defaults={'surname': 'Doe', 'other_names': 'John', 'sex': 'MALE', 'date_of_birth': '1990-01-01'})
    visit, _ = Visit.objects.get_or_create(patient=patient, status='Active', defaults={'visit_type': 'Inpatient', 'department': dept})
    ward, _ = Ward.objects.get_or_create(name="General Ward", defaults={'base_charge_per_day': 2000})
    bed, _ = Bed.objects.get_or_create(ward=ward, bed_number="G1", defaults={'is_occupied': True})
    
    admission, _ = Admission.objects.get_or_create(
        patient=patient, 
        visit=visit, 
        defaults={
            'bed': bed,
            'status': 'Admitted',
            'admitted_at': timezone.now() - timedelta(days=3),
            'provisional_diagnosis': 'Test'
        }
    )
    
    print(f"Created Admission for {patient.full_name}")
    print(f"Stay duration: 3 days")
    
    # [Testing Morgue Discharge...]
    print("\n[Testing Morgue Discharge...]")
    deceased, _ = Deceased.objects.get_or_create(tag="TAG001", defaults={
        'surname': 'Smith', 'other_names': 'Jane', 'sex': 'FEMALE', 
        'date_of_death': '2026-01-25', 'time_of_death': '10:00',
        'id_number': 'D123', 'id_type': 'NATIONAL_ID',
        'storage_area': 'MAIN_MORGUE', 'storage_chamber': 'CHAMBER_A',
        'expected_removal_date': '2026-02-10', 'created_by': admin
    })
    
    morgue_admission, _ = MorgueAdmission.objects.get_or_create(
        deceased=deceased,
        defaults={
            'admission_number': 'MADM001',
            'admission_datetime': timezone.now() - timedelta(days=5),
            'status': 'ADMITTED',
            'created_by': admin
        }
    )
    
    print(f"Created Morgue Admission for {deceased.full_name}")
    print(f"Stay duration: 5 days")

    print("\nVerification Data Setup Complete.")

if __name__ == "__main__":
    verify_discharge_billing()
