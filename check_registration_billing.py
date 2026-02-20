import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from accounts.models import Service, Invoice, InvoiceItem

print("=" * 60)
print("1. ALL SERVICES IN DB:")
print("=" * 60)
for s in Service.objects.all().order_by('name'):
    dept_name = s.department.name if s.department else "No Dept"
    print(f"  ID={s.id} | Name='{s.name}' | Price={s.price} | Dept={dept_name} | Active={s.is_active}")

print("\n" + "=" * 60)
print("2. SERVICES MATCHING PatientForm QUERYSET (name__in=['OPD Consultation', 'ANC', 'PNC', 'CWC']):")
print("=" * 60)
form_services = Service.objects.filter(name__in=['OPD Consultation', 'ANC', 'PNC', 'CWC'], is_active=True)
for s in form_services:
    print(f"  ID={s.id} | Name='{s.name}' | Price={s.price}")
if not form_services.exists():
    print("  >>> NONE FOUND! The PatientForm dropdown would be EMPTY.")

print("\n" + "=" * 60)
print("3. SERVICES MATCHING admit_patient_visit CHECK (name__icontains='Consultation'):")
print("=" * 60)
consult_services = Service.objects.filter(name__icontains='Consultation')
for s in consult_services:
    print(f"  ID={s.id} | Name='{s.name}' | Price={s.price}")

print("\n" + "=" * 60)
print("4. ALL INVOICE ITEMS (showing service name, invoice status, patient):")
print("=" * 60)
items = InvoiceItem.objects.select_related('invoice__patient', 'invoice__visit', 'service').order_by('-created_at')[:20]
for item in items:
    patient_name = item.invoice.patient.full_name if item.invoice.patient else "N/A"
    visit_type = item.invoice.visit.visit_type if item.invoice.visit else "N/A"
    print(f"  Patient={patient_name} | Item='{item.name}' | Service={item.service.name if item.service else 'None'} | " +
          f"Price={item.unit_price} | Invoice Status={item.invoice.status} | Visit={visit_type} | Date={item.created_at.strftime('%Y-%m-%d')}")

print("\n" + "=" * 60)
print("5. reception_dashboard consultation dropdown (from template context):")
print("=" * 60)
# Check what admitConsultation dropdown gets populated with
# From reception_dashboard view, look for consultation services
consultations = Service.objects.filter(
    name__in=['General Consultation', 'OPD Consultation', 'ANC', 'PNC', 'CWC'],
    is_active=True
)
for s in consultations:
    print(f"  ID={s.id} | Name='{s.name}' | Price={s.price}")
if not consultations.exists():
    print("  >>> NONE FOUND!")

