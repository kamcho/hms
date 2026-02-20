import os
import django
from django.test import RequestFactory
from django.contrib.auth import get_user_model

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

User = get_user_model()
from home.views import reception_dashboard

def verify_dashboard():
    factory = RequestFactory()
    # Try multiple roles that might access the dashboard
    roles = ['Triage Nurse', 'Receptionist', 'Admin']
    
    for role in roles:
        user = User.objects.filter(role=role).first()
        if not user:
            print(f"{role} not found, skipping...")
            continue
            
        print(f"Testing dashboard for role: {role}")
        request = factory.get('/home/dashboard/')
        request.user = user
        try:
            response = reception_dashboard(request)
            if response.status_code == 200:
                print(f"  Dashboard rendered successfully for {role}")
            else:
                print(f"  Dashboard failed for {role} with status code {response.status_code}")
        except Exception as e:
            import traceback
            print(f"  Dashboard raised exception for {role}: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    verify_dashboard()
