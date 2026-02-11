import os
import django
from django.test import RequestFactory
from django.contrib.auth import get_user_model

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient
from home.views import PatientListView

User = get_user_model()

def test_patient_search():
    # Create a user for login
    user, created = User.objects.get_or_create(id_number='USER123', defaults={'password': 'testpassword'})
    
    # Create test patients
    p1 = Patient.objects.create(
        first_name='John', 
        last_name='Doe', 
        id_number='ID12345', 
        phone='555-0101', 
        date_of_birth='2000-01-01',
        gender='M',
        location='City A',
        created_by=user
    )
    
    p2 = Patient.objects.create(
        first_name='Jane', 
        last_name='Smith', 
        id_number='ID67890', 
        phone='555-0102', 
        date_of_birth='1995-05-05',
        gender='F',
        location='City B',
        created_by=user
    )

    factory = RequestFactory()
    view = PatientListView()

    print("Testing Search Functionality...")

    # Test 1: Search by ID Number
    request = factory.get('/patients/', {'search': 'ID12345'})
    request.user = user
    view.request = request
    queryset = view.get_queryset()
    if p1 in queryset and p2 not in queryset:
        print("PASS: Search by ID Number")
    else:
        print(f"FAIL: Search by ID Number. Found: {[p.id_number for p in queryset]}")

    # Test 2: Search by Primary Key (ID)
    request = factory.get('/patients/', {'search': str(p2.pk)})
    request.user = user
    view.request = request
    queryset = view.get_queryset()
    if p2 in queryset and p1 not in queryset:
        print("PASS: Search by Primary Key")
    else:
        print(f"FAIL: Search by Primary Key. Found: {[p.pk for p in queryset]}")

    # Test 3: Search by Name
    request = factory.get('/patients/', {'search': 'John'})
    request.user = user
    view.request = request
    queryset = view.get_queryset()
    if p1 in queryset and p2 not in queryset:
        print("PASS: Search by Name")
    else:
        print(f"FAIL: Search by Name. Found: {[p.first_name for p in queryset]}")
        
    # Test 4: Search by Phone
    request = factory.get('/patients/', {'search': '555-0102'})
    request.user = user
    view.request = request
    queryset = view.get_queryset()
    if p2 in queryset and p1 not in queryset:
        print("PASS: Search by Phone")
    else:
        print(f"FAIL: Search by Phone. Found: {[p.phone for p in queryset]}")

    # Cleanup
    p1.delete()
    p2.delete()

if __name__ == '__main__':
    try:
        test_patient_search()
    except Exception as e:
        print(f"Error: {e}")
