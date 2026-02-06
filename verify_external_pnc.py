import os
import django
import sys
from datetime import datetime, timedelta
from django.utils import timezone

# Setup Django environment
sys.path.append('/home/kali/Downloads/hms')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Patient, Visit, PatientQue
from maternity.models import Pregnancy, LaborDelivery, Newborn
from django.contrib.auth import get_user_model

User = get_user_model()

def verify_external_registration():
    print("--- Verifying External Delivery Registration Logic ---")
    user = User.objects.first()
    patient = Patient.objects.create(
        first_name="External",
        last_name="Mother",
        gender="Female",
        date_of_birth=datetime.strptime("1995-01-01", "%Y-%m-%d").date()
    )
    print(f"Created Test Patient: {patient.full_name}")

    # Create External Delivery (Twin Birth)
    print("\n--- Testing Twin Birth Registration (External) ---")
    data = {
        'patient': patient,
        'gravida': 2,
        'para': 1,
        'abortion': 0,
        'living': 2,
        'delivery_datetime': timezone.now(),
        'delivery_mode': 'SVD',
        'outcome': 'Alive',
        'number_of_babies': 2
    }
    
    try:
        # 1. Create Pregnancy record
        delivery_date = data['delivery_datetime'].date()
        lmp = delivery_date - timedelta(days=280)
        edd = delivery_date
        
        pregnancy = Pregnancy.objects.create(
            patient=data['patient'],
            lmp=lmp,
            edd=edd,
            gravida=data['gravida'],
            para=data['para'],
            abortion=data['abortion'],
            living=data['living'],
            status='Delivered',
            created_by=user
        )
        print(f"Successfully created Pregnancy: {pregnancy}")
        
        # 2. Create LaborDelivery record
        delivery = LaborDelivery.objects.create(
            pregnancy=pregnancy,
            delivery_datetime=data['delivery_datetime'],
            delivery_mode=data['delivery_mode'],
            gestational_age_at_delivery=40,
            labor_onset='Spontaneous'
        )
        print(f"Successfully created LaborDelivery: {delivery}")
        
        # 3. Create Newborn record(s) - Loop for twins
        for i in range(data['number_of_babies']):
            newborn = Newborn.objects.create(
                delivery=delivery,
                baby_number=i+1,
                gender='A',
                birth_datetime=data['delivery_datetime'],
                birth_weight=0,
                apgar_1min=9,
                apgar_5min=10,
                status=data['outcome'],
                created_by=user
            )
            print(f"Successfully created Newborn: {newborn} (Baby #{newborn.baby_number})")
        
        # Verification
        newborn_count = Newborn.objects.filter(delivery=delivery).count()
        print(f"Verification: Newborn records for this delivery: {newborn_count}")
        
        if newborn_count == 2:
            print("SUCCESS: Multiple births logic is sound.")
        else:
            print("FAILURE: Incorrect number of newborn records created.")

    except Exception as e:
        print(f"ERROR during verification: {e}")

if __name__ == "__main__":
    verify_external_registration()
