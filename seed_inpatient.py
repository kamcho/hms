import os
import django
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inpatient.models import Ward, Bed, Admission
from home.models import Patient, Visit
from users.models import User

def seed_inpatient_data():
    print("Seeding inpatient data for dashboard testing...")
    
    # 1. Create a Ward
    ward, _ = Ward.objects.get_or_create(
        name="General Ward A",
        defaults={'ward_type': 'General', 'base_charge_per_day': 1500}
    )
    ward_icu, _ = Ward.objects.get_or_create(
        name="ICU Section",
        defaults={'ward_type': 'ICU', 'base_charge_per_day': 5000}
    )
    
    # 2. Create some Beds
    for i in range(1, 6):
        Bed.objects.get_or_create(
            bed_number=f"GW-A{i}",
            ward=ward,
            defaults={'bed_type': 'Normal'}
        )
    
    for i in range(1, 4):
        Bed.objects.get_or_create(
            bed_number=f"ICU-{i}",
            ward=ward_icu,
            defaults={'bed_type': 'Ventilator'}
        )
        
    # 3. Get or create a patient
    from datetime import date
    patient, _ = Patient.objects.get_or_create(
        first_name="Jane",
        last_name="Doe",
        defaults={'date_of_birth': date(1990, 1, 1), 'gender': 'F', 'phone': '0711223344', 'location': 'Nairobi'}
    )
    
    # 4. Create a visit
    visit = Visit.objects.create(
        patient=patient,
        visit_type='IN-PATIENT',
        visit_mode='Walk In'
    )
    
    # 5. Admit the patient
    user = User.objects.filter(is_superuser=True).first()
    bed = Bed.objects.filter(ward=ward, is_occupied=False).first()
    
    if bed and user:
        Admission.objects.get_or_create(
            patient=patient,
            visit=visit,
            bed=bed,
            defaults={
                'admitted_by': user,
                'provisional_diagnosis': 'Acute Malaria with complications',
                'status': 'Admitted'
            }
        )
        print(f"Admitted {patient.full_name} to {bed}")
    
    print("Seeding complete!")

if __name__ == "__main__":
    seed_inpatient_data()
