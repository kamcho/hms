import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from accounts.models import Invoice, InvoiceItem
from inpatient.models import Admission, Bed, Ward
from home.models import Patient

def check_invoice_100():
    print("--- Invoice 100 Check ---")
    try:
        invoice = Invoice.objects.get(id=100)
        print(f"Invoice ID: {invoice.id}")
        print(f"Patient: {invoice.patient.full_name if invoice.patient else 'N/A'}")
        print(f"Visit ID: {invoice.visit_id}")
        
        items = invoice.items.all()
        for item in items:
            print(f"  - Item: {item.name}, Price: {item.unit_price}, Qty: {item.quantity}, Total: {item.amount}")
            
        if invoice.visit:
            admission = Admission.objects.filter(visit=invoice.visit).first()
            if admission:
                print(f"\n--- Admission Data ---")
                print(f"Admission ID: {admission.id}")
                print(f"Status: {admission.status}")
                print(f"Admitted At: {admission.admitted_at}")
                if admission.bed:
                    print(f"Bed: {admission.bed.bed_number}")
                    if admission.bed.ward:
                        print(f"Ward: {admission.bed.ward.name}")
                        print(f"Ward Base Charge: {admission.bed.ward.base_charge_per_day}")
                    else:
                        print("Bed has no ward!")
                else:
                    print("Admission has no bed!")
            else:
                print("\nNo admission found for this visit.")
    except Invoice.DoesNotExist:
        print("Invoice 100 does not exist.")

if __name__ == '__main__':
    check_invoice_100()
