
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
from inpatient.models import Ward, Bed, Admission

@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
def verify_new_visit_admission():
    User = get_user_model()
    print("Verifying New Visit Creation on Admission...")
    
    # 1. Setup Data
    user, _ = User.objects.get_or_create(id_number='DOC_TEST', defaults={'password': 'testpass', 'role': 'Doctor'})
    patient = Patient.objects.create(
        first_name='Test', last_name='PatientForVisit', 
        date_of_birth='1990-01-01', gender='M', 
        phone='9999999999', id_number='ID999'
    )
    ward = Ward.objects.create(name='Test Ward', capacity=10, ward_type='General')
    bed = Bed.objects.create(ward=ward, bed_number='B-999', is_occupied=False)
    
    client = Client()
    client.force_login(user)
    
    url = reverse('inpatient:admit_patient', args=[patient.id])
    print(f"Testing Admission URL: {url}")
    
    # 2. Submit admission form WITHOUT visit
    data = {
        'ward': ward.id,
        'bed': bed.id,
        'provisional_diagnosis': 'Testing new visit creation',
        'visit': '' # Explicitly empty
    }
    
    try:
        response = client.post(url, data, follow=True)
        print(f"Response Status Code: {response.status_code}")
        
        # 3. Verification
        admission = Admission.objects.filter(patient=patient).last()
        if admission:
            print(f"Admission created: ID {admission.id}")
            if admission.visit:
                print(f"SUCCESS: Admission linked to Visit ID {admission.visit.id}")
                print(f"Visit Type: {admission.visit.visit_type}")
                print(f"Visit Notes: {admission.visit.notes}")
                if "Auto-generated" in admission.visit.notes:
                    print("SUCCESS: Visit notes confirm auto-generation.")
            else:
                print("FAILURE: Admission has NO linked visit.")
                
            # Clean up
            admission.visit.delete()
            admission.delete()
        else:
            print("FAILURE: Admission was NOT created.")
            print(response.content.decode('utf-8')) # Debug errors

    except Exception as e:
        print(f"FAILURE: Exception during test: {e}")
        
    print("Cleanup...")
    patient.delete()
    bed.delete()
    ward.delete()
    user.delete()

if __name__ == '__main__':
    verify_new_visit_admission()
