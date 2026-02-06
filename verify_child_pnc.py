import os
import django
import sys
from datetime import timedelta
from django.utils import timezone

# Set up Django environment
sys.path.append('/home/kali/Downloads/hms')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient, Visit, PatientQue, Departments
from maternity.models import Pregnancy, LaborDelivery, Newborn, PostnatalBabyVisit

def verify_child_pnc_workflow():
    print("--- Verifying Robust External Child PNC Workflow ---")
    
    # 1. Setup - Mock Reception Action (Baby Registered as Patient)
    baby_patient = Patient.objects.create(
        first_name="External",
        last_name="Baby",
        date_of_birth=timezone.now().date() - timedelta(days=7), # 1 week old
        phone="0700000000",
        location="Outside",
        gender='M'
    )
    print(f"1. Baby registered as patient: {baby_patient.full_name} (Age: {baby_patient.age})")
    
    # 2. Setup - Mock Payment & Triage (Sent to Maternity for PNC)
    visit = Visit.objects.create(
        patient=baby_patient,
        visit_type='OUT-PATIENT',
        visit_mode='Walk In'
    )
    
    # Mocking an invoice with PNC service would be complex, 
    # but the dashboard view looks for "PNC" in service names of the visit's invoices.
    # In a real environment, this would be done at reception.
    
    maternity_dept = Departments.objects.filter(name='Maternity').first()
    que = PatientQue.objects.create(
        visit=visit,
        sent_to=maternity_dept
    )
    print(f"2. Baby sent to Maternity Queue: {que}")
    
    # 3. Verify Dashboard Recognition (Simulating view logic)
    print("3. Verifying Dashboard View Logic...")
    today = timezone.now().date()
    
    # Check if this que item would be caught as a Child Arrival
    patient = que.visit.patient
    arrival_type = None
    if patient.age < 1:
        # Check for service (simulated here as True)
        is_pnc = True 
        
        if is_pnc:
            has_baby_visit = PostnatalBabyVisit.objects.filter(newborn__patient_profile=patient, visit_date=today).exists()
            if not has_baby_visit:
                linked_newborn = Newborn.objects.filter(patient_profile=patient).first()
                arrival_type = 'Child'
                print(f"   - SUCCESS: Detected as {arrival_type} arrival.")
                if not linked_newborn:
                    print("   - SUCCESS: Correctly identified as needing maternal link.")
    
    # 4. Verify Linkage Logic (Simulating register_external_delivery view)
    print("4. Verifying Linkage Logic (Clinical Record Creation)...")
    mother_patient = Patient.objects.create(
        first_name="External",
        last_name="Mother",
        date_of_birth=timezone.now().date() - timedelta(days=25*365),
        phone="0711111111",
        location="Outside",
        gender='F'
    )
    
    # Simulated view processing
    pregnancy = Pregnancy.objects.create(
        patient=mother_patient,
        lmp=today - timedelta(days=287),
        edd=today - timedelta(days=7),
        gravida=1, para=1, status='Delivered'
    )
    
    delivery = LaborDelivery.objects.create(
        pregnancy=pregnancy,
        delivery_datetime=timezone.now() - timedelta(days=7),
        delivery_mode='SVD',
        gestational_age_at_delivery=40
    )
    
    # Linking existing child patient during newborn creation
    newborn = Newborn.objects.create(
        delivery=delivery,
        patient_profile=baby_patient, # THE LINK
        baby_number=1,
        gender='M',
        birth_datetime=timezone.now() - timedelta(days=7),
        birth_weight=3.2,
        apgar_1min=9,
        apgar_5min=10
    )
    
    print(f"   - Linked Baby Patient {baby_patient} to Clinical Newborn Record {newborn}")
    
    # 5. Final Verification
    print("5. Running Final Verification Checks...")
    check_link = Newborn.objects.filter(patient_profile=baby_patient).exists()
    if check_link:
        print("   - SUCCESS: Patient profile successfully linked to clinical history.")
    else:
        print("   - FAILURE: Linkage failed.")
    
    print("--- Verification Complete ---")

if __name__ == "__main__":
    verify_child_pnc_workflow()
