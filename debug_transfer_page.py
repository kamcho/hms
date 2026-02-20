
import os
import django
import sys
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hms.settings")
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model

try:
    User = get_user_model()
    admin = User.objects.filter(is_superuser=True).first()
    if not admin:
        print("No superuser found.")
        sys.exit(1)

    client = Client()
    client.force_login(admin)

    print("Fetching /inventory/transfer/ ...")
    response = client.get('/inventory/transfer/')

    if response.status_code != 200:
        print(f"Error: Status Code {response.status_code}")
    else:
        content = response.content.decode('utf-8')
        if 'Transfer Stock' in content and '<button type="submit"' in content:
            print("PASS: Button HTML found in response.")
            # print(content[-500:]) # Print last 500 chars to see closure
        else:
            print("FAIL: Button HTML NOT found in response.")
            print("Content snippet around end of form:")
            idx = content.find('</form>')
            if idx != -1:
                print(content[idx-200:idx+20])
            else:
                print("Form tag not found.")

except Exception as e:
    print(f"EXCEPTION: {e}")
