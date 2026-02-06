
import os
import django
from django.conf import settings
from django.test import RequestFactory, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient, Visit, PatientQue, Departments
from home.views import opd_dashboard

@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
def verify_opd_search():
    User = get_user_model()
    print("Verifying OPD Search Filter...")
    
    # 1. Setup Data
    user, _ = User.objects.get_or_create(id_number='OPD_DOC', defaults={'password': 'pass', 'role': 'Doctor'})
    
    # Patient 1: John Searchable
    p1 = Patient.objects.create(
        first_name='John', last_name='Searchable', 
        phone='0700000001', id_number='ID_SEARCH_1', 
        date_of_birth='1990-01-01', gender='M'
    )
    v1 = Visit.objects.create(patient=p1, visit_type='OUT-PATIENT', visit_mode='Walk In')
    
    # Patient 2: Jane Hidden
    p2 = Patient.objects.create(
        first_name='Jane', last_name='Hidden', 
        phone='0700000002', id_number='ID_SEARCH_2', 
        date_of_birth='1992-01-01', gender='F'
    )
    v2 = Visit.objects.create(patient=p2, visit_type='OUT-PATIENT', visit_mode='Walk In')
    
    # Queue both
    consult_dept, _ = Departments.objects.get_or_create(name='Consultation Room 1')
    PatientQue.objects.create(visit=v1, sent_to=consult_dept, created_by=user)
    PatientQue.objects.create(visit=v2, sent_to=consult_dept, created_by=user)
    
    factory = RequestFactory()
    
    # Test 1: No Search (Expect 2) - Note: depends on other test data, but at least 2
    # But since we look at context['queue_list'], we can check for our specific patients
    request = factory.get('/home/opd-dashboard/')
    request.user = user
    response = opd_dashboard(request)
    # response is TemplateResponse, need to render or check context data if accessible?
    # standard view returns HttpResponse(render...), so context is lost unless we mock render or use client.
    # But Views in Django return HttpResponse. The context is only available if we use Client or simple request/response check logic.
    # Actually, opd_dashboard returns render(...) which is HttpResponse.
    # To check context, we should use Client or modify view to separate logic. 
    # Use Client instead.
    
    print("Cleaning up potential old data first...")
    # (Optional cleanup logic if needed)
    
    from django.test import Client
    client = Client()
    client.force_login(user)
    
    print("\n--- Test 1: Empty Query ---")
    resp = client.get('/home/opd-dashboard/')
    q_list = resp.context['queue_list']
    p1_found = any(i['patient'].id == p1.id for i in q_list)
    p2_found = any(i['patient'].id == p2.id for i in q_list)
    print(f"John Searchable found: {p1_found}")
    print(f"Jane Hidden found: {p2_found}")
    if p1_found and p2_found:
        print("SUCCESS: Both patients visible without filter.")
    else:
        print("FAILURE: Patients missing without filter.")
        
    print("\n--- Test 2: Search for 'John' ---")
    resp = client.get('/home/opd-dashboard/?q=John')
    q_list = resp.context['queue_list']
    p1_found = any(i['patient'].id == p1.id for i in q_list)
    p2_found = any(i['patient'].id == p2.id for i in q_list)
    print(f"John Searchable found: {p1_found}")
    print(f"Jane Hidden found: {p2_found}")
    
    if p1_found and not p2_found:
        print("SUCCESS: Filter correctly showed John and hid Jane.")
    else:
        print("FAILURE: Filter logic incorrect.")

    print("\n--- Test 3: Search for 'ID_SEARCH_2' ---")
    resp = client.get('/home/opd-dashboard/?q=ID_SEARCH_2')
    q_list = resp.context['queue_list']
    p1_found = any(i['patient'].id == p1.id for i in q_list)
    p2_found = any(i['patient'].id == p2.id for i in q_list)
    
    if not p1_found and p2_found:
        print("SUCCESS: Filter correctly showed Jane by ID.")
    else:
        print("FAILURE: Filter logic incorrect for ID.")

    # Cleanup
    print("\nCleanup...")
    PatientQue.objects.filter(visit__in=[v1, v2]).delete()
    v1.delete(); v2.delete()
    p1.delete(); p2.delete()

if __name__ == '__main__':
    verify_opd_search()
