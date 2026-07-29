import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from django.db.models import Sum, Count, F, Q
from django.http import JsonResponse
from home.models import Patient, Visit, Appointments
from accounts.models import Invoice
from morgue.models import Deceased, MorgueAdmission
from inpatient.models import Admission, Ward, Bed
from datetime import datetime, timedelta, date
from django.utils import timezone

from .forms import SignUpForm


def _pct_change(current, previous):
    """Return percent change between two values, or None if undefined."""
    if previous in (None, 0):
        return None if current == 0 else 100.0
    return round(((current - previous) / previous) * 100, 1)

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
    elif role == 'Accountant':
        return reverse_lazy('accounts:accountant_dashboard')
    elif role == 'SHA Manager':
        return reverse_lazy('accounts:insurance_manager')
    elif role == 'Procurement Officer':
        return reverse_lazy('inventory:item_list')
    return reverse_lazy('users:dashboard')

class CustomLoginView(LoginView):
    template_name = 'users/login.html'
    redirect_authenticated_user = True
    
    def get_success_url(self):
        return get_dashboard_url(self.request.user)

@login_required
def signup_view(request):
    """View for user registration (accessible only by superusers)."""
    if not request.user.is_superuser:
        raise PermissionDenied
        
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.is_staff = True  # All current roles require staff permissions
            user.save()
            
            messages.success(request, f'User {user.username} (ID: {user.id_number}) has been created successfully.')
            return redirect('users:signup')
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

    today = timezone.localdate()
    now = timezone.now()
    last_30 = now - timedelta(days=30)
    prev_30_start = now - timedelta(days=60)

    # Patient Statistics
    total_patients = Patient.objects.count()
    new_patients_30d = Patient.objects.filter(created_at__gte=last_30).count()
    new_patients_prev_30d = Patient.objects.filter(
        created_at__gte=prev_30_start, created_at__lt=last_30
    ).count()
    male_patients = Patient.objects.filter(gender='male').count()
    female_patients = Patient.objects.filter(gender='female').count()

    # Visits & appointments
    visits_today = Visit.objects.filter(visit_date__date=today).count()
    visits_yesterday = Visit.objects.filter(
        visit_date__date=today - timedelta(days=1)
    ).count()
    active_visits = Visit.objects.filter(is_active=True).count()
    appointments_today = Appointments.objects.filter(
        appointment_date__date=today
    ).count()
    pending_appointments = Appointments.objects.filter(
        is_completed=False, appointment_date__gte=now
    ).count()

    # Mortuary Statistics
    total_deceased = Deceased.objects.count()
    currently_admitted_deceased = Deceased.objects.filter(is_released=False).count()
    released_deceased_30d = Deceased.objects.filter(
        is_released=True,
        release_date__gte=last_30
    ).count()
    on_the_table_count = Deceased.objects.filter(
        is_released=False, storage_area__name__iexact='TEMPORARY'
    ).count()

    # Inpatient / bed occupancy
    active_inpatient_count = Admission.objects.filter(status='Admitted').count()
    total_beds = Bed.objects.count()
    occupied_beds = Bed.objects.filter(is_occupied=True).count()
    bed_occupancy_pct = round((occupied_beds / total_beds) * 100, 1) if total_beds else 0

    # Financial Statistics
    pending_qs = Invoice.objects.filter(status__in=['Pending', 'Partial', 'Draft'])
    pending_invoices = pending_qs.select_related('patient', 'deceased').order_by('-created_at')[:10]
    total_pending_invoices = pending_qs.count()
    total_pending_amount = pending_qs.aggregate(
        total=Sum(F('total_amount') - F('paid_amount'))
    )['total'] or 0
    collected_30d = Invoice.objects.filter(
        created_at__gte=last_30
    ).aggregate(total=Sum('paid_amount'))['total'] or 0
    collected_prev_30d = Invoice.objects.filter(
        created_at__gte=prev_30_start, created_at__lt=last_30
    ).aggregate(total=Sum('paid_amount'))['total'] or 0

    # Chart Data: Last 7 Days Trends
    days = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
    chart_labels = [d.strftime('%b %d') for d in days]
    patient_trends = []
    deceased_trends = []
    visit_trends = []
    admission_trends = []

    for d in days:
        patient_trends.append(Patient.objects.filter(created_at__date=d).count())
        deceased_trends.append(Deceased.objects.filter(created_at__date=d).count())
        visit_trends.append(Visit.objects.filter(visit_date__date=d).count())
        admission_trends.append(Admission.objects.filter(admitted_at__date=d).count())

    # Ward Occupancy
    wards = Ward.objects.annotate(
        patient_count=Count('beds', filter=Q(beds__is_occupied=True)),
        bed_total=Count('beds'),
    )
    ward_labels = [w.name for w in wards]
    ward_data = [w.patient_count for w in wards]
    ward_capacity = [w.bed_total for w in wards]

    # Storage Area Distribution
    storage_distributions = (
        Deceased.objects.filter(is_released=False, storage_area__isnull=False)
        .values('storage_area__name')
        .annotate(count=Count('id'))
    )
    storage_labels = [e['storage_area__name'] for e in storage_distributions]
    storage_data = [e['count'] for e in storage_distributions]

    hour = now.hour
    if hour < 12:
        greeting = 'Good morning'
    elif hour < 17:
        greeting = 'Good afternoon'
    else:
        greeting = 'Good evening'

    context = {
        'greeting': greeting,
        'total_patients': total_patients,
        'new_patients_30d': new_patients_30d,
        'patients_change_pct': _pct_change(new_patients_30d, new_patients_prev_30d),
        'male_patients': male_patients,
        'female_patients': female_patients,
        'visits_today': visits_today,
        'visits_change_pct': _pct_change(visits_today, visits_yesterday),
        'active_visits': active_visits,
        'appointments_today': appointments_today,
        'pending_appointments': pending_appointments,
        'total_deceased': total_deceased,
        'currently_admitted_deceased': currently_admitted_deceased,
        'released_deceased_30d': released_deceased_30d,
        'active_inpatient_count': active_inpatient_count,
        'on_the_table_count': on_the_table_count,
        'total_beds': total_beds,
        'occupied_beds': occupied_beds,
        'available_beds': max(total_beds - occupied_beds, 0),
        'bed_occupancy_pct': bed_occupancy_pct,
        'ward_labels_json': json.dumps(ward_labels),
        'ward_data_json': json.dumps(ward_data),
        'ward_capacity_json': json.dumps(ward_capacity),
        'storage_labels_json': json.dumps(storage_labels),
        'storage_data_json': json.dumps(storage_data),
        'recent_patients': Patient.objects.all().order_by('-created_at')[:8],
        'recent_deceased': Deceased.objects.all().order_by('-created_at')[:8],
        'pending_invoices': pending_invoices,
        'total_pending_invoices': total_pending_invoices,
        'total_pending_amount': total_pending_amount,
        'collected_30d': collected_30d,
        'collected_change_pct': _pct_change(float(collected_30d), float(collected_prev_30d)),
        'chart_labels_json': json.dumps(chart_labels),
        'patient_trends_json': json.dumps(patient_trends),
        'deceased_trends_json': json.dumps(deceased_trends),
        'visit_trends_json': json.dumps(visit_trends),
        'admission_trends_json': json.dumps(admission_trends),
        'range_start': today - timedelta(days=6),
        'range_end': today,
        # Back-compat aliases used by older template fragments
        'ward_labels': ward_labels,
        'ward_data': ward_data,
        'storage_labels': storage_labels,
        'storage_data': storage_data,
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


@login_required
def switch_role(request):
    """Allow superusers and authorized staff to switch their active role."""
    user = request.user
    # Authorized roles for switching
    authorized_switcher = user.is_superuser or user.role in ['Admin', 'Pharmacist', 'Receptionist']
    
    if not authorized_switcher:
        raise PermissionDenied
    
    if request.method == 'POST':
        new_role = request.POST.get('role')
        # Get role codes from the roles choices list
        valid_roles = [r[0] for r in request.user.roles]
        
        if new_role in valid_roles:
            # Enforce restrictions for non-Admins/non-superusers
            if not (user.is_superuser or user.role == 'Admin'):
                if user.role == 'Pharmacist' and new_role not in ['Receptionist', 'Pharmacist']:
                    messages.error(request, 'Pharmacists can only switch to Receptionist role.')
                    return redirect(get_dashboard_url(user))
                if user.role == 'Receptionist' and new_role not in ['Pharmacist', 'Receptionist']:
                    messages.error(request, 'You can only switch back to Pharmacist role.')
                    return redirect(get_dashboard_url(user))

            user.role = new_role
            user.save()
            messages.success(request, f'Role switched to {new_role}')
            return redirect(get_dashboard_url(user))
        else:
            messages.error(request, 'Invalid role selected.')
            
    return redirect(get_dashboard_url(user))


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
