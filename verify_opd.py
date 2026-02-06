
import os
import django
from django.conf import settings
from django.test import Client
from django.urls import reverse
from django.contrib.auth import get_user_model

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from django.test.utils import override_settings

@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
def verify_opd_dashboard():
    User = get_user_model()
    print("Verifying OPD Dashboard...")
    
    # Create or get a test doctor user
    id_number = 'DOC001'
    password = 'testpassword123'
    try:
        user = User.objects.get(id_number=id_number)
        print(f"User {id_number} exists.")
    except User.DoesNotExist:
        user = User.objects.create_user(id_number=id_number, password=password)
        user.role = 'Doctor'
        user.save()
        print(f"Created user {id_number}.")
        
    client = Client()
    client.login(id_number=id_number, password=password)
    
    try:
        url = reverse('home:opd_dashboard')
        print(f"Testing URL: {url}")
        
        response = client.get(url)
        
        if response.status_code == 200:
            print("SUCCESS: OPD Dashboard loaded with status 200.")
            
            # Check for context variables
            context_keys = ['todays_visits_count', 'waiting_count', 'critical_count', 'queue_list']
            for key in context_keys:
                if key in response.context:
                    print(f"SUCCESS: Context variable '{key}' is present.")
                else:
                    print(f"FAILURE: Context variable '{key}' is MISSING.")
            
            # Check for template content
            content = response.content.decode('utf-8')
            if "Outpatient Department" in content:
                print("SUCCESS: Dashboard title found in content.")
            else:
                print("FAILURE: Dashboard title not found.")
                
        else:
            print(f"FAILURE: OPD Dashboard returned status {response.status_code}.")
            print(response.content.decode('utf-8')[:500]) # Print start of error
            
    except Exception as e:
        print(f"FAILURE: An error occurred: {e}")

if __name__ == '__main__':
    verify_opd_dashboard()
