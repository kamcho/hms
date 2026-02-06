
import os
import django
from django.conf import settings
from django.test import Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
def verify_admission_link():
    User = get_user_model()
    print("Verifying Admission Link...")
    
    # Create or get a test user
    id_number = 'NURSE001'
    password = 'testpassword123'
    try:
        user = User.objects.get(id_number=id_number)
        print(f"User {id_number} exists.")
    except User.DoesNotExist:
        user = User.objects.create_user(id_number=id_number, password=password)
        user.role = 'Nurse' # Assuming nurses can admit
        user.save()
        print(f"Created user {id_number}.")
        
    client = Client()
    client.login(id_number=id_number, password=password)
    
    # 1. Check Dashboard Link
    try:
        url = reverse('inpatient:dashboard')
        print(f"Testing Dashboard URL: {url}")
        response = client.get(url)
        
        if response.status_code == 200:
            content = response.content.decode('utf-8')
            new_admission_url = reverse('inpatient:new_admission')
            if new_admission_url in content:
                print(f"SUCCESS: Link to {new_admission_url} found in dashboard.")
            else:
                print(f"FAILURE: Link to {new_admission_url} NOT found in dashboard.")
        else:
            print(f"FAILURE: Dashboard returned status {response.status_code}.")

    except Exception as e:
        print(f"FAILURE: Error checking dashboard: {e}")

    # 2. Check New Admission Page
    try:
        url = reverse('inpatient:new_admission')
        print(f"Testing New Admission Page URL: {url}")
        response = client.get(url)
        
        if response.status_code == 200:
            print("SUCCESS: New Admission page loaded with status 200.")
            content = response.content.decode('utf-8')
            if "New Admission" in content:
                 print("SUCCESS: 'New Admission' title found.")
            if "patients" in response.context:
                 print(f"SUCCESS: 'patients' context variable present with {len(response.context['patients'])} records.")
        else:
             print(f"FAILURE: New Admission page returned status {response.status_code}.")
             
    except Exception as e:
        print(f"FAILURE: Error checking new admission page: {e}")

if __name__ == '__main__':
    verify_admission_link()
