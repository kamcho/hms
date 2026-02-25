from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from django.db.models import Sum, Count, F
from django.http import JsonResponse
from home.models import Patient, Visit
from accounts.models import Invoice
from morgue.models import Deceased, MorgueAdmission
from inpatient.models import Admission, Ward, Bed
from datetime import datetime, timedelta, date

from .forms import SignUpForm

def get_dashboard_url(user):
    """Centralized role-based redirection logic."""
    role = user.role
    if role == 'Admin':
        return reverse_lazy('users:dashboard')
    elif role in ['Receptionist', 'Triage Nurse']:
        return reverse_lazy('home:reception_dashboard')
    elif role == 'Doctor':
        return reverse_lazy('home:opd_dashboard')
    elif role == 'Nurse':
        return reverse_lazy('inpatient:dashboard')
    elif role == 'Pharmacist':
        return reverse_lazy('home:pharmacy_dashboard')
    elif role in ['Lab Technician', 'Radiographer']:
        return reverse_lazy('lab:radiology_dashboard')
    elif role in ['Accountant', 'SHA Manager']:
        return reverse_lazy('accounts:accountant_dashboard')
    elif role == 'Procurement Officer':
        return reverse_lazy('inventory:item_list')
    return reverse_lazy('users:dashboard')

class CustomLoginView(LoginView):
    template_name = 'users/login.html'
    redirect_authenticated_user = True
    
    def get_success_url(self):
        return get_dashboard_url(self.request.user)

def signup_view(request):
    """View for user registration."""
    if request.user.is_authenticated:
        return redirect(get_dashboard_url(request.user))
        
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.is_staff = True  # All current roles require staff permissions
            user.save()
            
            # Log the user in
            login(request, user)
            messages.success(request, f'Welcome, {user.first_name}! Your account has been created successfully.')
            return redirect(get_dashboard_url(user))
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SignUpForm()
    
    return render(request, 'users/signup.html', {'form': form})

@login_required
def dashboard_view(request):
    """View for displaying the main dashboard."""
    if not request.user.is_staff:
        raise PermissionDenied
    # Patient Statistics
    total_patients = Patient.objects.count()
    new_patients_30d = Patient.objects.filter(
        created_at__gte=datetime.now() - timedelta(days=30)
    ).count()
    
    # Mortuary Statistics
    total_deceased = Deceased.objects.count()
    currently_admitted_deceased = Deceased.objects.filter(is_released=False).count()
    released_deceased_30d = Deceased.objects.filter(
        is_released=True,
        release_date__gte=datetime.now() - timedelta(days=30)
    ).count()
    
    # Financial Statistics
    pending_invoices = Invoice.objects.filter(
        status__in=['Pending', 'Partial', 'Draft']
    ).select_related('patient', 'deceased').order_by('-created_at')[:10]
    
    total_pending_amount = Invoice.objects.filter(
        status__in=['Pending', 'Partial', 'Draft']
    ).aggregate(
        total=Sum(F('total_amount') - F('paid_amount'))
    )['total'] or 0

    # Chart Data: Last 7 Days Trends
    today = date.today()
    days = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
    chart_labels = [d.strftime('%b %d') for d in days]
    
    patient_trends = []
    deceased_trends = []
    
    for d in days:
        p_count = Patient.objects.filter(created_at__date=d).count()
        d_count = Deceased.objects.filter(created_at__date=d).count()
        patient_trends.append(p_count)
        deceased_trends.append(d_count)

    # Inpatient Statistics
    active_inpatient_count = Admission.objects.filter(status='Admitted').count()
    
    # Morgue "On the Table" Statistics
    # Assuming 'TEMPORARY' storage area represents "on the table"
    on_the_table_count = Deceased.objects.filter(is_released=False, storage_area__name__iexact='TEMPORARY').count()
    
    # Ward Occupancy Data for Charts
    wards = Ward.objects.annotate(patient_count=Count('beds', filter=F('beds__is_occupied')))
    ward_labels = [w.name for w in wards]
    ward_data = [w.patient_count for w in wards]
    
    # Storage Area Distribution for Charts
    storage_distributions = Deceased.objects.filter(is_released=False, storage_area__isnull=False).values('storage_area__name').annotate(count=Count('id'))
    storage_labels = []
    storage_data = []
    
    for entry in storage_distributions:
        storage_labels.append(entry['storage_area__name'])
        storage_data.append(entry['count'])

    context = {
        'total_patients': total_patients,
        'new_patients_30d': new_patients_30d,
        'total_deceased': total_deceased,
        'currently_admitted_deceased': currently_admitted_deceased,
        'released_deceased_30d': released_deceased_30d,
        'active_inpatient_count': active_inpatient_count,
        'on_the_table_count': on_the_table_count,
        'ward_labels': ward_labels,
        'ward_data': ward_data,
        'storage_labels': storage_labels,
        'storage_data': storage_data,
        'recent_patients': Patient.objects.all().order_by('-created_at')[:5],
        'recent_deceased': Deceased.objects.all().order_by('-created_at')[:5],
        'pending_invoices': pending_invoices,
        'total_pending_invoices': Invoice.objects.filter(status__in=['Pending', 'Partial', 'Draft']).count(),
        'total_pending_amount': total_pending_amount,
        'chart_labels': chart_labels,
        'patient_trends': patient_trends,
        'deceased_trends': deceased_trends,
    }
    
    return render(request, 'users/dashboard.html', context)

@login_required
def profile_view(request):
    """View for displaying user profile."""
    return render(request, 'users/profile.html')

def logout_view(request):
    """View for logging out the user."""
    logout(request)
    messages.success(request, 'You have been successfully logged out.')
    return redirect('users:login')

@login_required
def mark_invoices_paid(request, patient_id):
    """Mark all pending invoices for a patient as paid."""
    if not request.user.is_staff:
        raise PermissionDenied
    if request.method == 'POST':
        try:
            patient = get_object_or_404(Patient, pk=patient_id)
            
            # Find unpaid invoices
            unpaid_invoices = Invoice.objects.filter(
                patient=patient, 
                status__in=['Pending', 'Partial', 'Draft']
            )
            
            count = 0
            for inv in unpaid_invoices:
                # Create a "Cash" payment for the balance
                balance = inv.total_amount - inv.paid_amount
                if balance > 0:
                    from accounts.models import Payment
                    Payment.objects.create(
                        invoice=inv,
                        amount=balance,
                        payment_method='Cash',
                        notes='Auto-paid via Dashboard',
                        created_by=request.user
                    )
                    count += 1
            
            if count > 0:
                return JsonResponse({
                    'success': True,
                    'message': f'Marked {count} invoice{"s" if count != 1 else ""} as paid for {patient.first_name} {patient.last_name}'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'No pending invoices found for this patient'
                })
                
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({
        'success': False,
        'error': 'Invalid request method'
    })


def handler404(request, exception=None):
    """Custom 404 error handler."""
    response = render(request, '404.html')
    response.status_code = 404
    return response


def handler500(request):
    """Custom 500 error handler."""
    response = render(request, '500.html')
    response.status_code = 500
    return response
