
import os
import django
from django.conf import settings
from django.test import Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient, Visit
from inpatient.models import Ward, Bed, Admission, PatientVitals

@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
def verify_case_folder_modals():
    User = get_user_model()
    print("Verifying Case Folder Modal Submissions...")
    
    # 1. Setup Data
    user, _ = User.objects.get_or_create(id_number='NURSE_TEST', defaults={'password': 'testpass', 'role': 'Nurse'})
    patient = Patient.objects.create(
        first_name='Test', last_name='ModalPatient', 
        date_of_birth='1990-01-01', gender='M', 
        phone='1111111111', id_number='ID_MODAL'
    )
    visit = Visit.objects.create(patient=patient, visit_type='IN-PATIENT', visit_mode='Walk In')
    ward = Ward.objects.create(name='Modal Ward', capacity=5, ward_type='General')
    bed = Bed.objects.create(ward=ward, bed_number='M-1', is_occupied=True)
    admission = Admission.objects.create(
        patient=patient, visit=visit, bed=bed, 
        admitted_by=user, provisional_diagnosis='Testing Modals'
    )
    
    client = Client()
    client.force_login(user)
    
    # 2. Test Add Vitals
    url = reverse('inpatient:add_vitals', args=[admission.id])
    print(f"Testing Add Vitals URL: {url}")
    
    data = {
        'temperature': '37.5',
        'pulse_rate': '80',
        'respiratory_rate': '18',
        'systolic_bp': '120',
        'diastolic_bp': '80',
        'spo2': '99',
        'weight': '70.5',
        'blood_sugar': '5.5'
    }
    
    try:
        response = client.post(url, data, follow=True) # Follow redirect
        
        # Check if redirected back to case folder
        expected_url = reverse('inpatient:patient_case_folder', args=[admission.id])
        # response.redirect_chain contains tuples (url, status_code)
        if response.redirect_chain:
             last_url, status = response.redirect_chain[-1]
             if expected_url in last_url:
                  print("SUCCESS: Redirected back to case folder.")
             else:
                  print(f"FAILURE: Redirected to unexpected URL: {last_url}")
        else:
             print(f"FAILURE: No redirect. Status: {response.status_code}")
             
        # Check if data saved
        vitals = PatientVitals.objects.filter(admission=admission).last()
        if vitals and float(vitals.temperature) == 37.5:
             print("SUCCESS: Vitals saved correctly.")
        else:
             print("FAILURE: Vitals not saved.")

    except Exception as e:
        print(f"FAILURE: Exception during test: {e}")
        
    print("Cleanup...")
    admission.delete()
    visit.delete()
    patient.delete()
    bed.delete()
    ward.delete()
    
    # Don't delete user if created before, but here it's fine
    # user.delete() 

if __name__ == '__main__':
    verify_case_folder_modals()
