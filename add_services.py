import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from home.models import Departments
from accounts.models import Service

def add_services():
    # 1. X-Ray Services (Imaging)
    xray_list = [
        "Chest", "Abdomen", "Lumbar Spine", "Thoracic Spine", "Ribs", "Sternum", 
        "Pelvis", "Hip Joint", "Femur", "Knee Joint", "Knee Joint (Bilateral)", 
        "Tibia and Fibula", "Foot", "Toes", "Ankle Joint", "Hand", "Radius and Ulna", 
        "Elbow", "Finger", "Wrist Joint", "Forearm", "Humerus", "Shoulder Joint", 
        "Clavicle", "Scapula", "Skull", "Barium Swallow", "Barium Meal", 
        "Calcaneus", "Calcaneus (Bilateral)", "Paranasal Sinuses", "Maxilla", 
        "Cervical Spine", "Lumbo-Sacral Spine", "Thoraco-Lumbar Spine", 
        "Sacral Spine", "Mandible"
    ]
    
    imaging_dept = Departments.objects.get(name='Imaging')
    
    print("Adding X-Ray Services...")
    for item in xray_list:
        name = f"X-Ray {item}"
        # Educated guess pricing
        if "Spine" in item: price = 2500
        elif "Barium" in item: price = 4000
        elif "Chest" in item: price = 1000
        else: price = 1500
        
        Service.objects.get_or_create(
            name=name,
            defaults={
                'department': imaging_dept,
                'price': price,
                'is_active': True
            }
        )
        print(f" - {name}")

    # 2. Lab Tests (Lab) - From Image 1
    lab_list = [
        "Compatibility Test",
        "DU Test",
        "Differential Counts",
        "ICT",
        "HVS Swab"
    ]
    
    lab_dept = Departments.objects.get(name='Lab')
    
    print("\nAdding Lab Services...")
    for item in lab_list:
        # Educated guess pricing
        if "Compatibility" in item: price = 1500
        elif "Counts" in item: price = 800
        else: price = 1000
        
        Service.objects.get_or_create(
            name=item,
            defaults={
                'department': lab_dept,
                'price': price,
                'is_active': True
            }
        )
        print(f" - {item}")

    print("\nDone.")

if __name__ == '__main__':
    add_services()
