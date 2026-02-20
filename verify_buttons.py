import os
import django
from django.template import Template, Context
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient
from inpatient.models import Admission, Ward, Bed
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.shortcuts import render

User = get_user_model()

def verify_buttons_hidden():
    # 1. Setup
    user = User.objects.filter(role='Doctor').first()
    
    # Create a dummy admission with status 'Discharged'
    patient = Patient.objects.first()
    admission = Admission.objects.filter(status='Discharged').first()
    if not admission:
        ward = Ward.objects.first()
        bed = Bed.objects.filter(ward=ward).first()
        admission = Admission.objects.create(
            patient=patient,
            bed=bed,
            status='Discharged'
        )

    # 2. Render Template
    factory = RequestFactory()
    request = factory.get('/')
    request.user = user
    
    context = {
        'admission': admission,
        'user': user,
        'invoice_is_paid': True,
        'notes': [],
        'medications': [],
        'instructions': [],
        'nutrition_orders': [],
        'activity_log': [],
        'lab_results': []
    }
    
    from django.template.loader import render_to_string
    html = render_to_string('inpatient/patient_case_folder.html', context, request=request)
    
    # 3. Check for buttons
    buttons_to_check = [
        'Transfer',
        'Refer',
        'Discharge',
        'Add Entry',
        'Prescribe',
        'Record Fluid',
        'New Instruction',
        'Update Diet',
        'vitalsModal',
        'next_action_widget.html'
    ]
    
    print(f"Checking visibility for Discharged status...")
    for btn in buttons_to_check:
        found = btn in html
        print(f" - {btn}: {'VISIBLE' if found else 'HIDDEN'}")

    # 4. Check for Admitted status (Doctor)
    admission.status = 'Admitted'
    admission.save()
    html_admitted = render_to_string('inpatient/patient_case_folder.html', context, request=request)
    
    print(f"\nChecking visibility for Admitted status (DOCTOR)...")
    for btn in buttons_to_check:
        found = btn in html_admitted
        print(f" - {btn}: {'VISIBLE' if found else 'HIDDEN'}")

    # 5. Check for Admitted status (Nurse)
    nurse = User.objects.filter(role='Nurse').first()
    if not nurse:
        nurse = User.objects.create_user(username='testnurse', password='password', role='Nurse')
    request.user = nurse
    html_nurse = render_to_string('inpatient/patient_case_folder.html', context, request=request)
    
    print(f"\nChecking visibility for Admitted status (NURSE)...")
    for btn in buttons_to_check:
        found = btn in html_nurse
        print(f" - {btn}: {'VISIBLE' if found else 'HIDDEN'}")

if __name__ == "__main__":
    verify_buttons_hidden()
