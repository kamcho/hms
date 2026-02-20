import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from inpatient.models import Bed, Ward

def list_beds():
    beds = Bed.objects.all().select_related('ward')
    print(f"Total beds: {beds.count()}")
    for b in beds:
        print(f"- Bed {b.bed_number} ({b.ward.name}): {'Occupied' if b.is_occupied else 'Available'}")

if __name__ == '__main__':
    list_beds()
