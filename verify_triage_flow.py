import os
import django
from django.conf import settings

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from home.models import Patient, Visit, Departments, PatientQue, TriageEntry
from home.views import create_triage_entry
import json

User = get_user_model()

def verify_triage_flow():
    print("Verifying Triage to Consultation Flow...")
    
    # 1. Setup Data
    # Create User (Nurse)
    nurse, _ = User.objects.get_or_create(username='nurse_test', role='Triage Nurse')
    
    # Create Departments
    reception, _ = Departments.objects.get_or_create(name='Reception', abbreviation='REC')
    triage, _ = Departments.objects.get_or_create(name='Triage', abbreviation='TRI')
    
    # Create Patient
    patient = Patient.objects.create(
        first_name='Test',
        last_name='Patient',
        date_of_birth='1990-01-01',
        gender='M',
        phone='1234567890'
    )
    
    # Create Visit
    visit = Visit.objects.create(
        patient=patient,
        visit_type='OUT-PATIENT',
        visit_mode='Walk In'
    )
    
    print(f"Created Patient: {patient.first_name} {patient.last_name}")
    print(f"Created Visit: {visit.id}")
    
    # 2. Simulate POST Request to create_triage_entry
    factory = RequestFactory()
    data = {
        'visit_id': visit.id,
        'category': 'GENERAL',
        'priority': 'MEDIUM',
        'temperature': '37.0',
        'blood_pressure_systolic': '120',
        'blood_pressure_diastolic': '80',
        'heart_rate': '80',
        'respiratory_rate': '16',
        'oxygen_saturation': '98',
        'send_to': '1', # Send to Room 1
        'triage_notes': 'Test Triage Note'
    }
    
    request = factory.post('/home/triage/create/', data)
    request.user = nurse
    
    # 3. Call View
    response = create_triage_entry(request)
    print(f"Response Status: {response.status_code}")
    print(f"Response Content: {response.content.decode()}")
    
    # 4. Verify TriageEntry
    triage_entry = TriageEntry.objects.filter(visit=visit).first()
    if triage_entry:
        print("✅ TriageEntry created.")
    else:
        print("❌ TriageEntry NOT created.")
        return
        
    # 5. Verify PatientQue
    consultation_room_name = 'Consultation Room 1'
    queue_entry = PatientQue.objects.filter(
        visit=visit,
        sent_to__name=consultation_room_name
    ).first()
    
    if queue_entry:
        print(f"✅ PatientQue created for {consultation_room_name}.")
        print(f"   Queued From: {queue_entry.qued_from.name}")
        print(f"   Sent To: {queue_entry.sent_to.name}")
    else:
        print(f"❌ PatientQue for {consultation_room_name} NOT created.")
        
    # Cleanup
    patient.delete()
    print("Cleanup complete.")

if __name__ == '__main__':
    verify_triage_flow()
