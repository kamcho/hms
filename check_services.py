import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from accounts.models import Service

search_terms = [
    "Haemoglobin",
    "rhesus",
    "blood sugar",
    "urinalysis",
    "hepatitis B",
    "blood group"
]

print(f"{'Search Term':<20} | {'Found Name':<40} | {'Price':<10}")
print("-" * 75)

for term in search_terms:
    services = Service.objects.filter(name__icontains=term)
    if services.exists():
        for s in services:
            print(f"{term:<20} | {s.name:<40} | {s.price:<10}")
    else:
        print(f"{term:<20} | {'NOT FOUND':<40} | {'N/A':<10}")
