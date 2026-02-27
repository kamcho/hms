import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from maternity.models import Pregnancy, LaborDelivery
from inpatient.models import Admission

try:
    p = Pregnancy.objects.get(id=21)
    patient = p.patient
    delivery = getattr(p, 'delivery', None)
    latest_visit = patient.visits.latest('visit_date') if patient.visits.exists() else None
    
    print(f'Pregnancy ID: {p.id}')
    print(f'Patient Name: {patient.full_name}')
    
    print("\n--- Admissions for this patient ---")
    admissions = Admission.objects.filter(patient=patient).order_by('id')
    for adm in admissions:
        print(f'Admission ID: {adm.id}, Status: {adm.status}, Admitted At: {adm.admitted_at}, Discharged At: {adm.discharged_at}, Visit: {adm.visit_id}')
    
    print("\n--- Delivery Details ---")
    print(f'Delivery Found: {delivery is not None}')
    if delivery:
        print(f'Delivery Visit ID: {delivery.visit_id}')
        print(f'Delivery Linked Admission ID: {delivery.admission_id}')
        if delivery.visit:
            invoice = getattr(delivery.visit, "invoice", None)
            print(f'Invoice ID: {invoice.id if invoice else "None"}')
            print(f'Invoice Status: {invoice.status if invoice else "N/A"}')
        else:
            print('Delivery has no associated visit.')
    
    print("\n--- Button Visibility Conditions ---")
    print(f'Delivery exists: {delivery is not None}')
    print(f'Delivery visit exists: {delivery.visit is not None if delivery else False}')
    print(f'Delivery visit invoice exists: {delivery.visit.invoice is not None if delivery and delivery.visit else False}')
    print(f'Invoice status != "Paid": {delivery.visit.invoice.status != "Paid" if delivery and delivery.visit and delivery.visit.invoice else False}')
    current_ipd_admission = Admission.objects.filter(patient=patient, status='Admitted').exists()
    print(f'Current IPD Admission exists (blocking): {current_ipd_admission}')
    print(f'Latest Visit ID: {latest_visit.id if latest_visit else "None"}')
    print(f'Delivery Visit == Latest Visit: {delivery.visit == latest_visit if delivery and delivery.visit else False}')

except Exception as e:
    import traceback
    traceback.print_exc()
