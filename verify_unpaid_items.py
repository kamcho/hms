import os
import django
from django.db.models import F, Prefetch

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms.settings')
django.setup()

from accounts.models import Invoice, InvoiceItem

def test_prefetch_logic():
    print("Testing prefetch logic for excluding paid items...")
    
    # Get invoices using the same logic as the view
    invoices = Invoice.objects.filter(
        status__in=['Pending', 'Partial', 'Draft']
    ).prefetch_related(
        Prefetch('items', queryset=InvoiceItem.objects.filter(paid_amount__lt=F('amount')).select_related('service'))
    )
    
    total_invoices = invoices.count()
    print(f"Found {total_invoices} invoices to check.")
    
    failure_found = False
    for inv in invoices:
        items = inv.items.all()
        for item in items:
            if item.paid_amount >= item.amount:
                print(f"  [FAILURE] Invoice {inv.id} has a fully paid item listed: {item.name} (Amount: {item.amount}, Paid: {item.paid_amount})")
                failure_found = True
    
    if not failure_found:
        print("  [SUCCESS] No fully paid items were found in the prefetched items for any invoice.")
    else:
        print("  [FAILURE] Some fully paid items were still listed.")

if __name__ == "__main__":
    test_prefetch_logic()
    
    # Now let's try to verify via the view if possible
    from django.test import RequestFactory
    from django.contrib.auth import get_user_model
    User = get_user_model()
    from home.views import reception_dashboard
    
    factory = RequestFactory()
    user = User.objects.filter(role='Receptionist').first()
    if user:
        print(f"\nTesting dashboard render for role: {user.role}")
        request = factory.get('/home/dashboard/')
        request.user = user
        try:
            response = reception_dashboard(request)
            if response.status_code == 200:
                print("  Dashboard rendered successfully with the new prefetch logic.")
            else:
                print(f"  Dashboard failed with status code {response.status_code}")
        except Exception as e:
            print(f"  Dashboard raised exception: {e}")
    else:
        print("\nNo Receptionist user found to test dashboard render.")
