from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings
from .utils import get_or_create_invoice
from django.db.models import Sum, Count, Q, F
from django.db import transaction
from django.utils import timezone
from datetime import timedelta, datetime, time
from django.http import HttpResponse, JsonResponse
from decimal import Decimal
from django.views.decorators.http import require_POST
from django.contrib import messages
from .models import (
    Invoice, Payment, Service, Expense, InventoryPurchase, 
    ExpenseCategory, SupplierInvoice, SupplierPayment, InvoiceItem
)
from .forms import (
    ExpenseForm, InventoryPurchaseForm, ExpenseCategoryForm, 
    SupplierInvoiceForm, SupplierPaymentForm, ServiceForm, SupplierForm
)
from home.models import Patient, Departments, Visit
from home.discharge_codes import get_or_create_discharge_code_payload
from .sha_hie_service import (
    ShaHieConfigError,
    ShaHieRequestError,
    get_facility_by_code,
    get_patient_info_by_id_number,
)
from morgue.models import Deceased, MorgueAdmission
from inpatient.models import Admission, Ward, MedicationChart, ServiceAdmissionLink
from inventory.models import StockRecord, Supplier
import json
import csv

def is_accountant(user):
    return user.is_authenticated and (user.role == 'Accountant' or user.is_superuser)

def is_receptionist(user):
    return user.is_authenticated and (user.role == 'Receptionist' or user.is_superuser)

IPD_SHA_PER_DIEM_RATE = Decimal('2240')
MATERNITY_SHA_REBATE = Decimal('10000')


def _is_maternity_invoice(invoice):
    """True when invoice visit is linked to a labor & delivery record."""
    if not invoice.visit_id:
        return False
    from maternity.models import LaborDelivery
    return LaborDelivery.objects.filter(visit_id=invoice.visit_id).exists()


def _is_sha_visit(invoice):
    visit = getattr(invoice, 'visit', None)
    if not visit:
        return False
    return (visit.payment_method or '').upper() == 'SHA'


def _get_ipd_per_diem_info(invoice):
    """
    SHA inpatient per-diem: insurance pays days × rate; adjustment records loss/gain.
    Positive adjustment = billed > per-diem (facility loss).
    Negative adjustment = billed < per-diem (facility gain).
    Maternity (L&D) invoices use a fixed SHA rebate instead — not per-diem.
    """
    if not invoice.visit or invoice.visit.visit_type != 'IN-PATIENT':
        return None
    if _is_maternity_invoice(invoice):
        return None
    admission = Admission.objects.filter(visit=invoice.visit).order_by('-admitted_at').first()
    if not admission:
        return None

    if admission.discharged_at:
        days = max(1, (admission.discharged_at - admission.admitted_at).days)
    else:
        days = max(1, (timezone.now() - admission.admitted_at).days)

    per_diem_total = IPD_SHA_PER_DIEM_RATE * days
    normal_delivery_total = (
        invoice.items.filter(service__name='Normal Delivery').aggregate(total=Sum('amount'))['total']
        or Decimal('0')
    )
    total_billed_for_per_diem = invoice.total_amount - normal_delivery_total
    adjustment = total_billed_for_per_diem - per_diem_total

    return {
        'days': days,
        'per_diem_rate': IPD_SHA_PER_DIEM_RATE,
        'per_diem_total': per_diem_total,
        'total_billed': invoice.total_amount,
        'normal_delivery_total': normal_delivery_total,
        'total_billed_for_per_diem': total_billed_for_per_diem,
        'adjustment': adjustment,
    }


def _get_maternity_sha_rebate_info(invoice):
    """Fixed SHA maternity package amount (default Ksh 10,000) when visit is SHA."""
    if not _is_maternity_invoice(invoice) or not _is_sha_visit(invoice):
        return None
    package_item = _maternity_package_item(invoice)
    return {
        'default_rebate': float(MATERNITY_SHA_REBATE),
        'current_rebate': float(invoice.insurance_adjustment or 0),
        'suggested_rebate': float(MATERNITY_SHA_REBATE),
        'package_item_id': package_item.id if package_item else None,
        'package_item_name': package_item.name if package_item else None,
        'package_unit_price': float(package_item.unit_price) if package_item else None,
        'total_billed': float(invoice.total_amount),
        'effective_after_rebate': float(invoice.total_amount),
    }


def _maternity_package_item(invoice):
    """Prefer Normal Delivery / C-section line for SHA package amount edit."""
    keywords = (
        'normal delivery',
        'caesarean',
        'cesarean',
        'c-section',
        'c section',
        'delivery',
    )
    items = list(invoice.items.all().order_by('created_at'))
    for item in items:
        name = (item.name or '').lower()
        if any(k in name for k in keywords[:5]):  # exact-ish delivery packages first
            return item
    for item in items:
        name = (item.name or '').lower()
        if 'delivery' in name:
            return item
    # Fallback: highest-priced unpaid non-drug line, else first item
    non_meds = [i for i in items if not (i.name or '').lower().startswith('medication') and 'paracetamol' not in (i.name or '').lower() and 'test drug' not in (i.name or '').lower()]
    if non_meds:
        return max(non_meds, key=lambda i: i.unit_price * i.quantity)
    return items[0] if items else None


def is_billing_staff(user):
    return user.is_authenticated and (user.role in ['Accountant', 'Receptionist', 'SHA Manager', 'SHA'] or user.is_superuser)


def can_query_sha_client_registry(user):
    """Staff allowed to verify patients against the national SHA client registry."""
    return user.is_authenticated and (
        user.is_superuser
        or user.role in [
            'Admin', 'Receptionist', 'SHA Manager', 'SHA',
            'Nurse', 'Doctor', 'Accountant',
        ]
    )


def can_view_invoice(user):
    """View or manage patient invoices (billing desk + night pharmacy staff)."""
    return user.is_authenticated and (
        is_billing_staff(user)
        or user.role in ['Nurse', 'Pharmacist', 'Admin']
        or user.is_superuser
    )


@login_required
@user_passes_test(is_accountant)
def accountant_dashboard(request):
    # Get date filters from request
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    # Date ranges for analytics
    today = timezone.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)
    
    # Base querysets
    invoices = Invoice.objects.all()
    payments = Payment.objects.all()
    
    # New Expense system
    general_expenses = Expense.objects.all()
    inventory_purchases = InventoryPurchase.objects.all()
    supplier_invoices = SupplierInvoice.objects.all()
    
    # Apply date filters if provided
    if from_date:
        try:
            from_date = timezone.datetime.strptime(from_date, '%Y-%m-%d').date()
            invoices = invoices.filter(created_at__date__gte=from_date)
            payments = payments.filter(payment_date__date__gte=from_date)
            general_expenses = general_expenses.filter(date__gte=from_date)
            inventory_purchases = inventory_purchases.filter(date__gte=from_date)
            supplier_invoices = supplier_invoices.filter(date__gte=from_date)
        except ValueError:
            from_date = None
    
    if to_date:
        try:
            to_date = timezone.datetime.strptime(to_date, '%Y-%m-%d').date()
            invoices = invoices.filter(created_at__date__lte=to_date)
            payments = payments.filter(payment_date__date__lte=to_date)
            general_expenses = general_expenses.filter(date__lte=to_date)
            inventory_purchases = inventory_purchases.filter(date__lte=to_date)
            supplier_invoices = supplier_invoices.filter(date__lte=to_date)
        except ValueError:
            to_date = None
    
    # --- 1. Revenue Metrics ---
    total_revenue = payments.aggregate(Sum('amount'))['amount__sum'] or 0
    total_general_expenses = general_expenses.aggregate(Sum('amount'))['amount__sum'] or 0
    total_inventory_purchases = inventory_purchases.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    # Supplier Metrics (AP)
    total_invoice_debt = supplier_invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_invoice_paid = supplier_invoices.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
    total_payable = total_invoice_debt - total_invoice_paid
    
    total_expenses = total_general_expenses + total_invoice_debt # Accrual basis: Operational + Invoiced Debt
    net_profit = total_revenue - (total_general_expenses + total_invoice_paid) # Cash basis profit

    # Weekly/Monthly Revenue (only if no custom filter)
    if not from_date and not to_date:
        start_of_week_dt = timezone.make_aware(datetime.combine(start_of_week, time.min))
        start_of_month_dt = timezone.make_aware(datetime.combine(start_of_month, time.min))
        weekly_revenue = Payment.objects.filter(payment_date__gte=start_of_week_dt).aggregate(Sum('amount'))['amount__sum'] or 0
        monthly_revenue = Payment.objects.filter(payment_date__gte=start_of_month_dt).aggregate(Sum('amount'))['amount__sum'] or 0
    else:
        weekly_revenue = 0
        monthly_revenue = 0

    # --- 2. Payment Method Reconciliation ---
    payment_methods = payments.values('payment_method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')

    # --- 3. In-Patient vs Out-Patient Revenue ---
    visit_revenue = invoices.values('visit__visit_type').annotate(
        total=Sum('paid_amount')
    ).order_by('-total')

    # --- 4. Aging Debtors (Unpaid Invoices) ---
    unpaid_invoices = invoices.filter(status__in=['Pending', 'Partial', 'Draft'])
    aging_debtors = {
        '0-7 Days': 0,
        '8-30 Days': 0,
        '30+ Days': 0
    }
    
    for inv in unpaid_invoices:
        age = (today - inv.created_at.date()).days
        balance = inv.balance
        if age <= 7:
            aging_debtors['0-7 Days'] += float(balance)
        elif age <= 30:
            aging_debtors['8-30 Days'] += float(balance)
        else:
            aging_debtors['30+ Days'] += float(balance)

    # --- 5. Cashier Accountability ---
    cashier_stats = payments.values(
        'created_by__id_number'
    ).annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')

    # --- Chart Data Preparation ---
    
    # Revenue Trend (Daily or Monthly)
    daily_revenue_data = []
    daily_labels = []
    for i in range(30, 0, -1):
        date = today - timedelta(days=i)
        daily_labels.append(date.strftime('%b %d'))
        sod = timezone.make_aware(datetime.combine(date, time.min))
        eod = timezone.make_aware(datetime.combine(date, time.max))
        day_rev = Payment.objects.filter(payment_date__range=(sod, eod)).aggregate(Sum('amount'))['amount__sum'] or 0
        daily_revenue_data.append(float(day_rev))
        
    # Service Type Breakdown (Revenue by Service Category)
    service_breakdown = invoices.filter(items__service__isnull=False).values(
        'items__service__department__name'
    ).annotate(
        revenue=Sum(F('items__quantity') * F('items__unit_price'))
    ).order_by('-revenue')
    
    service_labels = [item['items__service__department__name'] for item in service_breakdown]
    service_data = [float(item['revenue']) for item in service_breakdown]

    # Recent Transactions
    recent_transactions = payments.select_related('invoice', 'invoice__patient').order_by('-payment_date')[:10]

    # Handle Export
    if request.GET.get('export') == 'csv':
        return export_accountant_csv(payments, invoices, total_revenue, total_expenses, payment_methods)

    context = {
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'total_payable': total_payable,
        'total_general_expenses': total_general_expenses,
        'total_inventory_purchases': total_inventory_purchases,
        'net_profit': net_profit,
        'weekly_revenue': weekly_revenue,
        'monthly_revenue': monthly_revenue,
        
        'payment_methods': payment_methods,
        'visit_revenue': visit_revenue,
        'aging_debtors': aging_debtors,
        'cashier_stats': cashier_stats,
        'recent_transactions': recent_transactions,
        
        'from_date': from_date,
        'to_date': to_date,
        
        # JSON Data for Charts
        'daily_labels': json.dumps(daily_labels),
        'daily_revenue_data': json.dumps(daily_revenue_data),
        'service_labels': json.dumps(service_labels),
        'service_data': json.dumps(service_data),
        'payment_method_labels': json.dumps([p['payment_method'] for p in payment_methods]),
        'payment_method_data': json.dumps([float(p['total']) for p in payment_methods]),
    }
    
    return render(request, 'accounts/accountant_dashboard.html', context)

@login_required
@user_passes_test(lambda u: u.is_authenticated and (u.role in ['SHA Manager', 'Admin', 'Accountant'] or u.is_superuser))
def insurance_manager(request):
    search_query = request.GET.get('search', '')
    search_opd = request.GET.get('search_opd', '')
    search_ipd = request.GET.get('search_ipd', '')
    search_mat = request.GET.get('search_mat', '')
    search_sha = request.GET.get('search_sha', '')
    
    # Base filter for unpaid or partially paid invoices with actual balance > 0
    unpaid_invoices = Invoice.objects.filter(
        status__in=['Pending', 'Partial'],
        visit__payment_method='SHA'
    ).annotate(
        balance_check=F('total_amount') - F('insurance_adjustment') - F('paid_amount')
    ).filter(
        balance_check__gt=0.01
    ).select_related('patient', 'visit', 'deceased').order_by('-created_at')
    
    def apply_robust_search(queryset, query):
        if not query:
            return queryset
        search_terms = query.split()
        q_objects = Q()
        for term in search_terms:
            term_q = Q(
                Q(patient__first_name__icontains=term) |
                Q(patient__last_name__icontains=term) |
                Q(patient__id_number__icontains=term) |
                Q(patient__phone__icontains=term) |
                Q(deceased__surname__icontains=term) |
                Q(deceased__other_names__icontains=term) |
                Q(id__icontains=term)
            )
            q_objects &= term_q
        return queryset.filter(q_objects)

    # Initial global search if any
    unpaid_invoices = apply_robust_search(unpaid_invoices, search_query)

    # Grouping by visit type
    opd_invoices = unpaid_invoices.filter(visit__visit_type='OUT-PATIENT')
    ipd_invoices = unpaid_invoices.filter(visit__visit_type='IN-PATIENT', visit__labor_delivery__isnull=True)
    maternity_invoices = unpaid_invoices.filter(visit__visit_type='IN-PATIENT', visit__labor_delivery__isnull=False)

    # Apply section-specific searches
    opd_invoices = apply_robust_search(opd_invoices, search_opd)
    ipd_invoices = apply_robust_search(ipd_invoices, search_ipd)
    maternity_invoices = apply_robust_search(maternity_invoices, search_mat)

    from home.models import Visit
    
    def apply_visit_search(queryset, query):
        if not query:
            return queryset
        search_terms = query.split()
        q_objects = Q()
        for term in search_terms:
            term_q = Q(
                Q(patient__first_name__icontains=term) |
                Q(patient__last_name__icontains=term) |
                Q(patient__id_number__icontains=term) |
                Q(patient__phone__icontains=term) |
                Q(id__icontains=term)
            )
            q_objects &= term_q
        return queryset.filter(q_objects)

    thirty_days_ago = timezone.now() - timedelta(days=30)

    if search_query or search_sha:
        active_cash_visits = Visit.objects.filter(
            is_active=True,
            payment_method='CASH',
            visit_type='IN-PATIENT',
            visit_date__gte=thirty_days_ago
        ).order_by('-visit_date')
        if search_query:
            active_cash_visits = apply_visit_search(active_cash_visits, search_query)
        if search_sha:
            active_cash_visits = apply_visit_search(active_cash_visits, search_sha)
    else:
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        active_cash_visits = Visit.objects.filter(
            is_active=True, 
            payment_method='CASH', 
            visit_type='IN-PATIENT',
            visit_date__gte=today_start
        ).order_by('-visit_date')

    discharge_visit_ids = set(active_cash_visits.values_list('id', flat=True))
    discharge_visit_ids.update(ipd_invoices.values_list('visit_id', flat=True))
    discharge_visit_ids = [visit_id for visit_id in discharge_visit_ids if visit_id]

    discharge_codes = {
        visit_id: get_or_create_discharge_code_payload(visit_id)
        for visit_id in discharge_visit_ids
    }

    balance_expr = F('total_amount') - F('insurance_adjustment') - F('paid_amount')

    def outstanding_total(qs):
        result = qs.aggregate(total=Sum(balance_expr))
        return result['total'] or Decimal('0')

    context = {
        'opd_invoices': opd_invoices,
        'ipd_invoices': ipd_invoices,
        'maternity_invoices': maternity_invoices,
        'search_query': search_query,
        'search_opd': search_opd,
        'search_ipd': search_ipd,
        'search_mat': search_mat,
        'search_sha': search_sha,
        'active_cash_visits': active_cash_visits,
        'discharge_codes': discharge_codes,
        'title': 'Insurance & Credit Manager',
        'stats': {
            'opd_count': opd_invoices.count(),
            'ipd_count': ipd_invoices.count(),
            'maternity_count': maternity_invoices.count(),
            'cash_count': active_cash_visits.count(),
            'total_claims': opd_invoices.count() + ipd_invoices.count() + maternity_invoices.count(),
            'opd_balance': outstanding_total(opd_invoices),
            'ipd_balance': outstanding_total(ipd_invoices),
            'maternity_balance': outstanding_total(maternity_invoices),
            'total_balance': outstanding_total(unpaid_invoices),
        },
    }

    return render(request, 'accounts/insurance_manager.html', context)


@login_required
@user_passes_test(can_query_sha_client_registry)
def sha_patient_by_id_number(request):
    """
    GET /accounts/api/sha/patient-by-id/?id_number=12345678
    GET /accounts/api/sha/eligibility/?id_number=12345678&identification_type=National ID
    Looks up a patient in the SHA/DHA eligibility registry.
    """
    import logging
    import traceback

    logger = logging.getLogger(__name__)
    id_number = (request.GET.get('id_number') or request.GET.get('national_id') or '').strip()
    identification_type = (
        request.GET.get('identification_type')
        or request.GET.get('id_type')
        or 'National ID'
    ).strip() or 'National ID'
    skip_eligibility = request.GET.get('skip_eligibility', '').strip() in ('1', 'true', 'yes')
    debug = {
        'step': 'start',
        'id_number': id_number,
        'identification_type': identification_type,
        'skip_eligibility': skip_eligibility,
        'user': getattr(request.user, 'username', None),
        'base_url': getattr(settings, 'SHA_HIE_BASE_URL', None),
        'has_username': bool(getattr(settings, 'SHA_HIE_USERNAME', '')),
        'has_password': bool(getattr(settings, 'SHA_HIE_PASSWORD', '')),
        'has_consumer_key': bool(getattr(settings, 'SHA_HIE_CONSUMER_KEY', '')),
        'agent_id': getattr(settings, 'SHA_HIE_AGENT_ID', '') or None,
    }
    print(f"[SHA DEBUG] lookup requested by={debug['user']} id={id_number} skip_eligibility={skip_eligibility}")
    logger.info("SHA patient lookup start: %s", debug)

    if not id_number:
        debug['step'] = 'validation_failed'
        print("[SHA DEBUG] missing id_number")
        return JsonResponse(
            {'success': False, 'error': 'id_number is required.', 'debug': debug},
            status=400,
        )

    try:
        debug['step'] = 'calling_hie'
        print("[SHA DEBUG] calling get_patient_info_by_id_number...")
        payload = get_patient_info_by_id_number(
            id_number,
            identification_type=identification_type,
            skip_eligibility=skip_eligibility,
        )
        debug['step'] = 'success'
        debug['found'] = payload.get('found')
        debug['dependents_count'] = len(payload.get('dependents') or [])
        debug['eligibility_error'] = payload.get('eligibility_error')
        debug['client_registry_error'] = payload.get('client_registry_error')
        print(
            f"[SHA DEBUG] lookup success found={payload.get('found')} "
            f"dependents={debug['dependents_count']} patient={payload.get('patient')}"
        )
        return JsonResponse({
            'success': True,
            'found': payload['found'],
            'id_number': payload['id_number'],
            'patient': payload['patient'],
            'dependents': payload.get('dependents') or [],
            'raw': payload['raw'],
            'eligibility_error': payload.get('eligibility_error'),
            'client_registry_error': payload.get('client_registry_error'),
            'debug': debug,
        })
    except ValueError as exc:
        debug['step'] = 'value_error'
        debug['error'] = str(exc)
        print(f"[SHA DEBUG] ValueError: {exc}")
        return JsonResponse({'success': False, 'error': str(exc), 'debug': debug}, status=400)
    except ShaHieConfigError as exc:
        debug['step'] = 'config_error'
        debug['error'] = str(exc)
        print(f"[SHA DEBUG] ConfigError: {exc}")
        return JsonResponse({'success': False, 'error': str(exc), 'debug': debug}, status=503)
    except ShaHieRequestError as exc:
        debug['step'] = 'request_error'
        debug['error'] = str(exc)
        print(f"[SHA DEBUG] RequestError: {exc}")
        return JsonResponse({'success': False, 'error': str(exc), 'debug': debug}, status=502)
    except Exception as exc:
        debug['step'] = 'unexpected_error'
        debug['error'] = str(exc)
        debug['traceback'] = traceback.format_exc()
        print(f"[SHA DEBUG] UnexpectedError: {exc}")
        print(debug['traceback'])
        return JsonResponse(
            {'success': False, 'error': f'Unexpected SHA lookup error: {exc}', 'debug': debug},
            status=500,
        )


@login_required
@user_passes_test(can_query_sha_client_registry)
def sha_eligibility_page(request):
    """UI to check SHA patient eligibility by national ID."""
    from .sha_diagnostics import DHA_SUPPORT_EMAIL
    from .models import Service

    services = Service.objects.filter(
        is_active=True,
        name__in=['OPD Consultation', 'MCH'],
    ).order_by('name')
    # Fallback: any active OPD-ish services if named ones missing
    if not services.exists():
        services = Service.objects.filter(is_active=True).order_by('name')[:20]

    return render(request, 'accounts/sha_eligibility_check.html', {
        'title': 'SHA Eligibility Check',
        'base_url': getattr(settings, 'SHA_HIE_BASE_URL', ''),
        'eligibility_path': getattr(
            settings,
            'SHA_HIE_ELIGIBILITY_PATH',
            '/v2/eligibility',
        ),
        'dha_support_email': DHA_SUPPORT_EMAIL,
        'services': services,
        'facility_code': getattr(settings, 'SHA_HIE_FACILITY_FR_CODE', '') or '15627',
    })


@login_required
@require_POST
def sha_create_visit_from_eligibility(request):
    """
    POST /accounts/api/sha/create-visit/
    Create a SHA visit from the eligibility page after a successful check.
    Expects JSON: {patient_id, cr_id, id_number, consultation_id, ...}
    If patient_id is empty, attempts to find/create patient by id_number.
    """
    from home.models import PatientQue, Departments
    from .models import Service, Invoice, InvoiceItem
    from .utils import get_or_create_invoice

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)

    cr_id = (data.get('cr_id') or '').strip()
    id_number = (data.get('id_number') or '').strip()
    patient_id = data.get('patient_id')
    consultation_id = data.get('consultation_id')
    first_name = (data.get('first_name') or '').strip()
    last_name = (data.get('last_name') or '').strip()
    gender = (data.get('gender') or '').strip().lower() or 'unknown'
    dob = (data.get('date_of_birth') or '').strip()
    phone = (data.get('phone') or '').strip()

    if not consultation_id:
        return JsonResponse({'success': False, 'error': 'Select a consultation type.'}, status=400)

    service = Service.objects.filter(pk=consultation_id, is_active=True).first()
    if not service:
        return JsonResponse({'success': False, 'error': 'Service not found.'}, status=400)

    # Resolve patient
    patient = None
    if patient_id:
        patient = Patient.objects.filter(pk=patient_id).first()

    if not patient and id_number:
        patient = Patient.objects.filter(
            Q(national_id=id_number) | Q(id_number=id_number)
        ).first()

    if not patient:
        if not first_name or not last_name:
            return JsonResponse({
                'success': False,
                'error': 'Patient not found locally. Register them on Add patient first, then retry.',
                'needs_registration': True,
            }, status=400)
        from datetime import date as _date
        parsed_dob = None
        if dob:
            try:
                parsed_dob = _date.fromisoformat(str(dob)[:10])
            except (ValueError, TypeError):
                parsed_dob = None
        if not parsed_dob:
            parsed_dob = _date(2000, 1, 1)
        gender_mapped = gender
        if gender_mapped.startswith('m'):
            gender_mapped = 'male'
        elif gender_mapped.startswith('f'):
            gender_mapped = 'female'
        elif gender_mapped not in ('male', 'female', 'other', 'unknown'):
            gender_mapped = 'unknown'
        patient = Patient.objects.create(
            first_name=first_name,
            last_name=last_name,
            date_of_birth=parsed_dob,
            gender=gender_mapped,
            phone=phone or None,
            id_type='NATIONAL_ID',
            id_number=id_number or None,
            national_id=id_number or None,
            cr_id=cr_id or None,
            location=data.get('county') or 'Unknown',
            created_by=request.user,
        )

    # Update CR ID on patient if missing
    if cr_id and not patient.cr_id:
        patient.cr_id = cr_id
        patient.save(update_fields=['cr_id'])
    if id_number and not patient.national_id:
        patient.national_id = id_number
        patient.id_number = id_number
        patient.save(update_fields=['national_id', 'id_number'])

    # Close active visits
    Visit.objects.filter(patient=patient, is_active=True).update(is_active=False)

    # Create SHA visit
    visit = Visit.objects.create(
        patient=patient,
        visit_type='OUT-PATIENT',
        visit_mode='Walk In',
        payment_method='SHA',
        by_nurse=False,
    )

    # Billing
    service_upper = service.name.upper()
    is_mch = 'MCH' in service_upper

    if not is_mch:
        invoice = get_or_create_invoice(visit=visit, user=request.user)
        opd_book = Service.objects.filter(name__icontains='OPD Book', is_active=True).first()
        if opd_book:
            InvoiceItem.objects.create(
                invoice=invoice, service=opd_book,
                name=opd_book.name, unit_price=opd_book.price, quantity=1,
            )
        InvoiceItem.objects.create(
            invoice=invoice, service=service,
            name=service.name, unit_price=300, quantity=1,
        )
        invoice.refresh_from_db()
        from .models import Payment
        if invoice.total_amount > 0:
            insurance_amount = min(invoice.total_amount, 300)
            Payment.objects.create(
                invoice=invoice, amount=insurance_amount,
                payment_method='Insurance',
                notes='SHA insurance portion (auto)',
                created_by=request.user,
            )

    # Queue to Triage (or MCH)
    reception_dept, _ = Departments.objects.get_or_create(name='Reception', defaults={'abbreviation': 'REC'})
    if is_mch:
        dest_dept, _ = Departments.objects.get_or_create(name='MCH', defaults={'abbreviation': 'MCH'})
    else:
        dest_dept, _ = Departments.objects.get_or_create(name='Triage', defaults={'abbreviation': 'TRI'})

    PatientQue.objects.create(
        visit=visit, qued_from=reception_dept,
        sent_to=dest_dept, created_by=request.user,
    )

    # Create SHA claim session
    from .sha_claims_service import get_or_create_claim_session
    try:
        session = get_or_create_claim_session(visit, user=request.user)
        if cr_id:
            session.patient_cr_id = cr_id
            session.patient_id_number = id_number
            session.save(update_fields=['patient_cr_id', 'patient_id_number', 'updated_at'])
    except Exception:
        pass

    return JsonResponse({
        'success': True,
        'message': f'{patient.full_name} admitted (SHA) for {service.name}. Queued to {dest_dept.name}.',
        'visit_id': visit.pk,
        'patient_id': patient.pk,
        'claims_desk_url': f'/accounts/sha/claims/{visit.pk}/',
    })


@login_required
@user_passes_test(can_query_sha_client_registry)
def sha_diagnostics_api(request):
    """GET /accounts/api/sha/diagnostics/ — AfyaLink connectivity report for DHA escalation."""
    from .sha_diagnostics import format_sha_diagnostics_report, run_sha_connectivity_diagnostics

    sample_id = (request.GET.get('sample_id') or '2897398').strip()
    id_type = (request.GET.get('identification_type') or 'National ID').strip()
    data = run_sha_connectivity_diagnostics(
        sample_id=sample_id or '2897398',
        identification_type=id_type or 'National ID',
    )
    return JsonResponse({
        'success': True,
        'report': format_sha_diagnostics_report(data),
        'summary': data.get('summary'),
        'recommendation': data.get('recommendation'),
        'dha_support_email': data.get('dha_support_email'),
        'auth_ok': data.get('auth_ok'),
        'eligibility_ok': data.get('eligibility_ok'),
        'client_registry_ok': data.get('client_registry_ok'),
        'checks': data.get('checks'),
    })


@login_required
@user_passes_test(can_query_sha_client_registry)
def sha_facility_search_page(request):
    """Small UI to look up a facility by registry / registration code."""
    return render(request, 'accounts/sha_facility_search.html', {
        'title': 'SHA Facility Search',
        'base_url': getattr(settings, 'SHA_HIE_BASE_URL', ''),
        'facility_search_path': getattr(
            settings,
            'SHA_HIE_FACILITY_SEARCH_PATH',
            '/v2/facility-search',
        ),
    })


@login_required
@user_passes_test(can_query_sha_client_registry)
def sha_facility_by_code(request):
    """
    GET /accounts/api/sha/facility-by-code/?facility_code=XXXX

    Proxies AfyaLink:
        GET {{base_url}}/v2/facility-search?facility_code={{facility_code}}
    """
    import logging
    import traceback

    logger = logging.getLogger(__name__)
    facility_code = (
        request.GET.get('facility_code')
        or request.GET.get('registration_number')
        or request.GET.get('code')
        or ''
    ).strip()
    debug = {
        'step': 'start',
        'facility_code': facility_code,
        'user': getattr(request.user, 'username', None),
        'base_url': getattr(settings, 'SHA_HIE_BASE_URL', None),
        'facility_search_path': getattr(
            settings,
            'SHA_HIE_FACILITY_SEARCH_PATH',
            '/v2/facility-search',
        ),
        'has_username': bool(getattr(settings, 'SHA_HIE_USERNAME', '')),
        'has_password': bool(getattr(settings, 'SHA_HIE_PASSWORD', '')),
        'has_consumer_key': bool(getattr(settings, 'SHA_HIE_CONSUMER_KEY', '')),
        'agent_id': getattr(settings, 'SHA_HIE_AGENT_ID', '') or None,
    }
    print(f"[SHA DEBUG] facility search requested by={debug['user']} code={facility_code}")
    logger.info("SHA facility search start: %s", debug)

    if not facility_code:
        debug['step'] = 'validation_failed'
        return JsonResponse(
            {'success': False, 'error': 'facility_code is required.', 'debug': debug},
            status=400,
        )

    try:
        debug['step'] = 'calling_hie'
        payload = get_facility_by_code(facility_code)
        debug['step'] = 'success'
        debug['found'] = payload.get('found')
        return JsonResponse({
            'success': True,
            'found': payload['found'],
            'facility_code': payload['facility_code'],
            'facility': payload['facility'],
            'raw': payload['raw'],
            'debug': debug,
        })
    except ValueError as exc:
        debug['step'] = 'value_error'
        debug['error'] = str(exc)
        return JsonResponse({'success': False, 'error': str(exc), 'debug': debug}, status=400)
    except ShaHieConfigError as exc:
        debug['step'] = 'config_error'
        debug['error'] = str(exc)
        return JsonResponse({'success': False, 'error': str(exc), 'debug': debug}, status=503)
    except ShaHieRequestError as exc:
        debug['step'] = 'request_error'
        debug['error'] = str(exc)
        return JsonResponse({'success': False, 'error': str(exc), 'debug': debug}, status=502)
    except Exception as exc:
        debug['step'] = 'unexpected_error'
        debug['error'] = str(exc)
        debug['traceback'] = traceback.format_exc()
        print(f"[SHA DEBUG] facility UnexpectedError: {exc}")
        print(debug['traceback'])
        return JsonResponse(
            {
                'success': False,
                'error': f'Unexpected SHA facility search error: {exc}',
                'debug': debug,
            },
            status=500,
        )


@login_required
@user_passes_test(is_billing_staff)
def get_discharge_code(request, visit_id):
    visit = get_object_or_404(Visit, pk=visit_id)
    payload = get_or_create_discharge_code_payload(visit.id)
    return JsonResponse({
        'success': True,
        'visit_id': visit.id,
        **payload,
    })

@login_required
@user_passes_test(is_billing_staff)
def get_invoice_items(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)
    items_data = []
    for item in invoice.items.all().order_by('created_at'):
        # Get delivery info safely
        delivery_id = None
        if item.invoice.visit:
            try:
                delivery_id = item.invoice.visit.labor_delivery.id
            except:
                delivery_id = None
        
        items_data.append({
            'id': item.id,
            'name': item.name,
            'quantity': item.quantity,
            'unit_price': float(item.unit_price),
            'amount': float(item.amount),
            'paid_amount': float(item.paid_amount),
            'balance': float(item.balance),
            'is_settled': item.is_settled,
            'delivery': delivery_id,  # Add delivery info
        })
    
    per_diem = _get_ipd_per_diem_info(invoice)
    admission_info = None
    if per_diem:
        admission_info = {
            'days': per_diem['days'],
            'per_diem_rate': float(per_diem['per_diem_rate']),
            'per_diem_total': float(per_diem['per_diem_total']),
            'total_billed': float(per_diem['total_billed']),
            'normal_delivery_total': float(per_diem['normal_delivery_total']),
            'total_billed_for_per_diem': float(per_diem['total_billed_for_per_diem']),
            'adjustment': float(per_diem['adjustment']),
            'current_adjustment': float(invoice.insurance_adjustment),
        }

    maternity_rebate = _get_maternity_sha_rebate_info(invoice)

    return JsonResponse({
        'items': items_data,
        'admission_info': admission_info,
        'maternity_rebate': maternity_rebate,
        'is_maternity': _is_maternity_invoice(invoice),
        'is_sha': _is_sha_visit(invoice),
    })

@login_required
@user_passes_test(is_billing_staff)
@require_POST
def process_insurance_claim(request):
    try:
        data = json.loads(request.body)
        invoice_id = data.get('invoice_id')
        item_ids = data.get('item_ids')
        claim_id = data.get('claim_id', '')
        custom_amount = data.get('amount')
        adjustment = data.get('adjustment', 0)

        invoice = get_object_or_404(Invoice, id=invoice_id)
        selected_items = invoice.items.filter(id__in=item_ids)
        if not selected_items.exists():
            return JsonResponse({'success': False, 'error': 'Select at least one invoice item.'})

        per_diem = _get_ipd_per_diem_info(invoice)
        maternity_rebate = _get_maternity_sha_rebate_info(invoice)
        tol = Decimal('0.01')

        if per_diem:
            # Server-side per-diem: loss/gain via adjustment, claim = SHA cap (days × 2240)
            invoice.insurance_adjustment = per_diem['adjustment']
            invoice.save()
            invoice.distribute_payments()
            invoice.refresh_from_db()
            claim_amount = per_diem['per_diem_total']
        elif maternity_rebate:
            # SHA maternity: package amount is edited on the delivery line separately.
            # Optional adjustment from claim UI still allowed, but default is 0 (not a write-off of 10k).
            rebate_amt = Decimal(str(adjustment)) if adjustment not in (None, '') else Decimal('0')
            if rebate_amt < 0:
                return JsonResponse({'success': False, 'error': 'Adjustment cannot be negative.'}, status=400)
            if rebate_amt > invoice.total_amount:
                rebate_amt = invoice.total_amount
            invoice.insurance_adjustment = rebate_amt
            invoice.save()
            invoice.distribute_payments()
            invoice.refresh_from_db()
            selected_total = selected_items.aggregate(total=Sum('amount'))['total'] or Decimal('0')
            claim_amount = (
                Decimal(str(custom_amount)) if custom_amount is not None else selected_total
            )
            if claim_amount > invoice.balance + tol:
                claim_amount = max(invoice.balance, Decimal('0'))
        else:
            if adjustment is not None:
                invoice.insurance_adjustment = Decimal(str(adjustment))
                invoice.save()
                invoice.distribute_payments()
                invoice.refresh_from_db()

            selected_total = selected_items.aggregate(total=Sum('amount'))['total'] or Decimal('0')
            claim_amount = (
                Decimal(str(custom_amount)) if custom_amount is not None else selected_total
            )

        if claim_amount <= 0:
            return JsonResponse({
                'success': False,
                'error': f'Claim amount must be greater than zero (received Ksh {claim_amount}).',
            })

        if per_diem:
            # After adjustment, collectible total = effective_amount (per-diem when loss/gain applied)
            if claim_amount > invoice.effective_amount + tol:
                loss_gain = 'loss' if per_diem['adjustment'] > 0 else 'gain'
                return JsonResponse({
                    'success': False,
                    'error': (
                        f'Claim amount (Ksh {claim_amount}) exceeds effective invoice amount '
                        f'(Ksh {invoice.effective_amount}) after per-diem {loss_gain} adjustment.'
                    ),
                })
            if claim_amount > invoice.balance + tol:
                if invoice.balance <= 0:
                    return JsonResponse({
                        'success': False,
                        'error': 'Nothing left to collect on this invoice after prior payments.',
                    })
                claim_amount = invoice.balance
        elif claim_amount > invoice.balance + tol:
            return JsonResponse({
                'success': False,
                'error': (
                    f'Claim amount (Ksh {claim_amount}) exceeds remaining balance '
                    f'(Ksh {invoice.balance}).'
                ),
            })

        # Create Payment
        payment = Payment.objects.create(
            invoice=invoice,
            amount=claim_amount,
            payment_method='Insurance',
            transaction_reference=claim_id,
            notes=f"Insurance claim for items: {', '.join([item.name for item in selected_items])}",
            created_by=request.user
        )

        dha_result = None
        from django.conf import settings as django_settings
        if getattr(django_settings, 'SHA_HIE_AUTO_SUBMIT_ON_INSURANCE', False) and invoice.visit_id:
            try:
                from accounts.sha_claims_service import (
                    get_or_create_claim_session,
                    submit_claim,
                )
                session = get_or_create_claim_session(invoice.visit, request.user)
                if session.consent_token:
                    session = submit_claim(
                        session,
                        invoice=invoice,
                        notes=f'Local insurance payment #{payment.id}',
                    )
                    dha_result = {
                        'status': session.status,
                        'claim_id': session.claim_id,
                        'workflow_state': session.workflow_state,
                    }
                    if session.claim_id and not claim_id:
                        payment.transaction_reference = session.claim_id
                        payment.save(update_fields=['transaction_reference'])
            except Exception as dha_exc:  # noqa: BLE001
                dha_result = {'error': str(dha_exc)}
        
        return JsonResponse({
            'success': True, 
            'payment_id': payment.id,
            'amount': float(claim_amount),
            'adjustment': float(invoice.insurance_adjustment),
            'dha': dha_result,
        })
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        error_msg = (
            f"An internal server error occurred:\n"
            f"Error message: {str(e)}\n\n"
            f"Traceback:\n{tb}"
        )
        return JsonResponse({'success': False, 'error': error_msg})

def export_accountant_csv(payments, invoices, total_revenue, total_expenses, payment_methods):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="fms_report_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['FMS FINANCIAL REPORT'])
    writer.writerow(['Generated:', timezone.now().strftime('%Y-%m-%d %H:%M')])
    writer.writerow([])
    
    writer.writerow(['SUMMARY'])
    writer.writerow(['Total Revenue', total_revenue])
    writer.writerow(['Total Expenses', total_expenses])
    writer.writerow(['Net Profit', total_revenue - total_expenses])
    writer.writerow([])
    
    writer.writerow(['PAYMENT RECONCILIATION'])
    for pm in payment_methods:
        writer.writerow([pm['payment_method'], pm['total'], f"{pm['count']} txns"])
    writer.writerow([])

    writer.writerow(['RECENT TRANSACTIONS'])
    writer.writerow(['Date', 'Receipt #', 'Patient', 'Method', 'Amount', 'Cashier'])
    for p in payments.order_by('-payment_date')[:50]:
        writer.writerow([
            p.payment_date.strftime('%Y-%m-%d %H:%M'),
            p.transaction_reference or f"PAY-{p.id}",
            p.invoice.patient.full_name,
            p.payment_method,
            p.amount,
            p.created_by.id_number if p.created_by else 'System'
        ])
        
    return response

@login_required
@user_passes_test(can_view_invoice)
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    
    # Check for active admission/morgue admission linked to this invoice
    can_authorize = False
    admission_type = None
    
    if invoice.status == 'Paid':
        if invoice.patient and invoice.visit:
            if Admission.objects.filter(visit=invoice.visit, status='Admitted').exists():
                can_authorize = True
                admission_type = 'IPD'
        elif invoice.deceased:
            if MorgueAdmission.objects.filter(deceased=invoice.deceased, status='ADMITTED').exists():
                can_authorize = True
                admission_type = 'Morgue'
                
    is_delivery = _is_maternity_invoice(invoice)
    is_sha = _is_sha_visit(invoice)
    can_edit_maternity_sha = is_delivery and is_sha and (
        request.user.is_superuser
        or request.user.role in ['SHA Manager', 'Accountant', 'Admin', 'Receptionist']
    )

    context = {
        'invoice': invoice,
        'can_authorize': can_authorize,
        'admission_type': admission_type,
        'can_record_payment': is_receptionist(request.user) and not is_sha,
        'is_delivery': is_delivery,
        'is_sha_visit': is_sha,
        'can_edit_maternity_sha': can_edit_maternity_sha,
        'maternity_sha_rebate': MATERNITY_SHA_REBATE,
    }
    return render(request, 'accounts/invoice_detail.html', context)

@login_required
@user_passes_test(is_billing_staff)
@require_POST
def record_payment(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if _is_sha_visit(invoice):
        return JsonResponse({
            'success': False,
            'error': 'SHA visits are settled via the SHA claims desk, not cash Record Payment.',
            'claims_desk_url': f'/accounts/sha/claims/{invoice.visit_id}/' if invoice.visit_id else None,
        }, status=400)
    payments_to_create = []
    
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            if 'payments' in data:
                payments_to_create = data['payments']
            else:
                payments_to_create = [{
                    'amount': data.get('amount'),
                    'method': data.get('payment_method'),
                    'reference': data.get('reference')
                }]
        else:
            payments_to_create = [{
                'amount': request.POST.get('amount'),
                'method': request.POST.get('payment_method'),
                'reference': request.POST.get('reference')
            }]

        created_payments = []
        with transaction.atomic():
            for p_data in payments_to_create:
                amount_val = p_data.get('amount')
                if not amount_val or float(amount_val) <= 0:
                    continue
                    
                payment = Payment.objects.create(
                    invoice=invoice,
                    amount=amount_val,
                    payment_method=p_data.get('method') or p_data.get('payment_method'),
                    transaction_reference=p_data.get('reference'),
                    created_by=request.user
                )
                created_payments.append(payment)
        
        if not created_payments:
            return JsonResponse({'success': False, 'error': 'No valid payment amounts provided.'})
            
        return JsonResponse({
            'success': True, 
            'payment_id': created_payments[0].id,
            'all_payment_ids': [p.id for p in created_payments]
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@user_passes_test(is_billing_staff)
def print_receipt(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)
    invoice = payment.invoice
    
    # Deterministic FIFO: Use payment_date AND id for ordering
    prior_payments_filter = Q(payment_date__lt=payment.payment_date) | Q(payment_date=payment.payment_date, id__lt=payment.id)
    prior_payments = invoice.payments.filter(prior_payments_filter).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    start_value = prior_payments
    end_value = prior_payments + payment.amount
    
    covered_items = []
    current_cumulative_item_amount = Decimal('0')
    
    for item in invoice.items.all().order_by('created_at'):
        item_start = current_cumulative_item_amount
        item_end = current_cumulative_item_amount + item.amount
        
        overlap_start = max(start_value, item_start)
        overlap_end = min(end_value, item_end)
        
        if overlap_start < overlap_end:
            amount_covered_by_this_payment = overlap_end - overlap_start
            covered_items.append({
                'name': item.name,
                'quantity': item.quantity,
                'unit_price': item.unit_price,
                'subtotal': item.amount,
                'amount_paid_now': amount_covered_by_this_payment
            })
            
        current_cumulative_item_amount = item_end
        if current_cumulative_item_amount >= end_value:
            break
            
    # Sister payments (split parts)
    sister_payments = invoice.payments.filter(
        payment_date__gte=payment.payment_date - timedelta(seconds=2),
        payment_date__lte=payment.payment_date + timedelta(seconds=2),
        created_by=payment.created_by
    ).exclude(id=payment.id)
    
    # Calculate grand total if there's a split
    grand_total = payment.amount
    if sister_payments.exists():
        grand_total += sister_payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    context = {
        'payment': payment,
        'invoice': invoice,
        'covered_items': covered_items,
        'sister_payments': sister_payments,
        'has_split': sister_payments.exists(),
        'grand_total': grand_total,
        'hospital_name': "Hospital Management System",
        'hospital_address': "123 Health Street, City",
        'hospital_phone': "+254 700 000 000",
    }
    
    return render(request, 'accounts/receipt_thermal.html', context)

@login_required
@user_passes_test(is_billing_staff)
def delete_invoice(request, pk):
    if request.method == 'POST':
        invoice = get_object_or_404(Invoice, pk=pk)
        
        # Check if the user is the creator
        if invoice.created_by != request.user:
            return JsonResponse({'success': False, 'error': 'Only the person who created this invoice can delete it.'})
        
        # Check if the invoice has any payments
        if invoice.payments.exists():
            return JsonResponse({'success': False, 'error': 'Cannot delete an invoice that has existing payment records.'})
        
        try:
            patient_id = invoice.patient.id if invoice.patient else None
            invoice.delete()
            from django.contrib import messages
            messages.success(request, "Invoice deleted successfully.")
            return JsonResponse({'success': True, 'patient_id': patient_id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    return HttpResponse(status=405)

@login_required
@user_passes_test(is_billing_staff)
def delete_invoice_item(request, item_id):
    if request.method == 'POST':
        item = get_object_or_404(InvoiceItem, pk=item_id)
        invoice = item.invoice
        
        # Permission Check: Admin or Invoice Creator or Item Creator
        if request.user.is_superuser or invoice.created_by == request.user or item.created_by == request.user:
             pass
        else:
            return JsonResponse({'success': False, 'error': 'Only the item creator or invoice creator can delete items.'})
        
        # Dispense Check: Nobody can delete dispensed items
        if item.is_dispensed:
            return JsonResponse({'success': False, 'error': 'This item has already been physically dispensed and cannot be deleted.'})
            
        # Services Check: Check if a lab test associated with this item is completed
        if item.is_completed_service:
            return JsonResponse({'success': False, 'error': 'This service has already been completed and its record cannot be deleted.'})
        
        # State Check: Unpaid only
        if item.paid_amount > 0:
            return JsonResponse({'success': False, 'error': 'Cannot delete an item that has been partially or fully paid.'})
            
        try:
            with transaction.atomic():
                # Handle Inventory Reversal if this is an inventory item
                if item.inventory_item and invoice.visit:
                    from inventory.models import DispensedItem, StockRecord
                    from inpatient.models import InpatientConsumable

                    # 1. Find and cleanup DispensedItem (Physical record)
                    dispensed_record = DispensedItem.objects.filter(
                        visit=invoice.visit,
                        item=item.inventory_item,
                        quantity=item.quantity
                    ).order_by('-dispensed_at').first()

                    if dispensed_record:
                        # Reverse Stock if department was recorded
                        if dispensed_record.department:
                            sr = StockRecord.objects.filter(
                                item=item.inventory_item, 
                                current_location=dispensed_record.department
                            ).first()
                            if sr:
                                sr.quantity += dispensed_record.quantity
                                sr.save()
                        
                        dispensed_record.delete()

                    # 2. Find and cleanup InpatientConsumable (IPD tracking)
                    inpatient_req = InpatientConsumable.objects.filter(
                        admission__visit=invoice.visit,
                        item=item.inventory_item,
                        quantity=item.quantity
                    ).order_by('-prescribed_at').first()

                    if inpatient_req:
                        inpatient_req.delete()

                item.delete()
                invoice.update_totals() # Recalculate invoice totals
            
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    return HttpResponse(status=405)

@login_required
@require_POST
def zero_invoice_item(request, item_id):
    """Sets the unit price to 0 for an invoice item if allowed by SHA or Accountant on a delivery visit."""
    item = get_object_or_404(InvoiceItem, pk=item_id)
    invoice = item.invoice
    
    # Permission condition
    if request.user.role not in ['SHA Manager', 'Accountant', 'Admin'] and not request.user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Only SHA Manager or Accountant can zero invoice items.'})
        
    is_delivery = _is_maternity_invoice(invoice)
        
    if not is_delivery:
        return JsonResponse({'success': False, 'error': 'Zeroing items is strictly for Delivery/Maternity visits.'})
        
    if item.paid_amount > 0:
        return JsonResponse({'success': False, 'error': 'Cannot zero a partially or fully paid item.'})
        
    try:
        item.unit_price = 0
        item.save()
        invoice.update_totals()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
def update_invoice_item_price(request, item_id):
    """
    Edit unit price on a maternity SHA invoice line (unpaid items only).
    POST: unit_price
    """
    item = get_object_or_404(InvoiceItem, pk=item_id)
    invoice = item.invoice

    if request.user.role not in ['SHA Manager', 'Accountant', 'Admin', 'Receptionist'] and not request.user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Not allowed to edit invoice amounts.'}, status=403)

    if not _is_maternity_invoice(invoice) or not _is_sha_visit(invoice):
        return JsonResponse({
            'success': False,
            'error': 'Amount edit is only allowed on maternity invoices for SHA visits.',
        }, status=400)

    if item.paid_amount > 0:
        return JsonResponse({'success': False, 'error': 'Cannot edit a partially or fully paid item.'}, status=400)

    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        data = request.POST

    try:
        new_price = Decimal(str(data.get('unit_price', '')).replace(',', '').strip())
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid unit price.'}, status=400)

    if new_price < 0:
        return JsonResponse({'success': False, 'error': 'Unit price cannot be negative.'}, status=400)

    item.unit_price = new_price
    item.save()
    invoice.update_totals()
    invoice.refresh_from_db()

    return JsonResponse({
        'success': True,
        'item_id': item.id,
        'unit_price': float(item.unit_price),
        'amount': float(item.amount),
        'total_amount': float(invoice.total_amount),
        'balance': float(invoice.balance),
        'insurance_adjustment': float(invoice.insurance_adjustment),
    })


@login_required
@require_POST
def apply_maternity_sha_rebate(request, pk):
    """
    Set SHA maternity package amount on the delivery line (default Ksh 10,000).
    This edits the Normal Delivery / delivery unit price — it does NOT clamp to
    the previous total (that was causing 10000 → 4000).
    """
    invoice = get_object_or_404(Invoice, pk=pk)

    if request.user.role not in ['SHA Manager', 'Accountant', 'Admin', 'Receptionist'] and not request.user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Not allowed to apply maternity SHA rebate.'}, status=403)

    if not _is_maternity_invoice(invoice):
        return JsonResponse({'success': False, 'error': 'Invoice is not linked to maternity.'}, status=400)
    if not _is_sha_visit(invoice):
        return JsonResponse({'success': False, 'error': 'Visit is not SHA. Rebate applies to SHA maternity only.'}, status=400)

    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        data = request.POST

    raw = data.get('amount', None)
    if raw is None or raw == '':
        package_amount = MATERNITY_SHA_REBATE
    else:
        try:
            package_amount = Decimal(str(raw).replace(',', '').strip())
        except Exception:
            return JsonResponse({'success': False, 'error': 'Invalid package amount.'}, status=400)

    if package_amount < 0:
        return JsonResponse({'success': False, 'error': 'Package amount cannot be negative.'}, status=400)

    item = _maternity_package_item(invoice)
    if not item:
        return JsonResponse({
            'success': False,
            'error': 'No delivery / maternity package line found to update. Add Normal Delivery first.',
        }, status=400)

    if item.paid_amount > 0 and item.paid_amount >= item.amount and package_amount < item.unit_price:
        return JsonResponse({
            'success': False,
            'error': 'Cannot reduce a fully paid delivery line. Reverse payments first.',
        }, status=400)

    item.unit_price = package_amount
    item.save()

    # Clear prior facility write-off that was incorrectly used as "rebate"
    if invoice.insurance_adjustment:
        invoice.insurance_adjustment = Decimal('0')
        invoice.save(update_fields=['insurance_adjustment'])

    invoice.update_totals()
    invoice.distribute_payments()
    invoice.refresh_from_db()

    return JsonResponse({
        'success': True,
        'message': (
            f'SHA maternity package set to Ksh {package_amount:,.2f} '
            f'on “{item.name}”.'
        ),
        'item_id': item.id,
        'item_name': item.name,
        'unit_price': float(item.unit_price),
        'insurance_adjustment': float(invoice.insurance_adjustment),
        'effective_amount': float(invoice.effective_amount),
        'total_amount': float(invoice.total_amount),
        'balance': float(invoice.balance),
        'default_rebate': float(MATERNITY_SHA_REBATE),
    })
@login_required
@user_passes_test(is_billing_staff)
def invoice_list(request):
    """List all invoices with filtering options"""
    invoices = Invoice.objects.all().select_related('patient', 'deceased', 'created_by')
    
    # Filter by deceased if specified
    deceased_id = request.GET.get('deceased')
    if deceased_id:
        invoices = invoices.filter(deceased_id=deceased_id)
    
    # Filter by patient if specified
    patient_id = request.GET.get('patient')
    if patient_id:
        invoices = invoices.filter(patient_id=patient_id)
    
    # Filter by status
    status = request.GET.get('status')
    if status:
        invoices = invoices.filter(status=status)
    
    # Search functionality
    search = request.GET.get('search')
    if search:
        invoices = invoices.filter(
            Q(patient__first_name__icontains=search) |
            Q(patient__last_name__icontains=search) |
            Q(deceased__surname__icontains=search) |
            Q(deceased__other_names__icontains=search) |
            Q(id__icontains=search)
        )
    
    # Order by most recent
    invoices = invoices.order_by('-created_at')
    
    context = {
        'invoices': invoices,
        'deceased_filter': deceased_id,
        'patient_filter': patient_id,
        'status_filter': status,
        'search_query': search,
    }
    return render(request, 'accounts/invoice_list.html', context)

@login_required
@user_passes_test(is_billing_staff)
def create_invoice(request):
    """Create a new invoice for patient or deceased"""
    if request.method == 'POST':
        # Check if this is an AJAX request from the modal
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                # Handle modal form submission
                deceased_id = request.POST.get('deceased')
                patient_id = request.POST.get('patient')
                notes = request.POST.get('notes', '')
                due_date = request.POST.get('due_date')
                total_amount = request.POST.get('total_amount', '0')
                
                if deceased_id:
                    deceased = get_object_or_404(Deceased, pk=deceased_id)
                    invoice = get_or_create_invoice(deceased=deceased, user=request.user)
                    
                    # Update fields if provided
                    if notes: invoice.notes = notes
                    if due_date: invoice.due_date = due_date
                    if total_amount: invoice.total_amount = total_amount
                    invoice.save()
                    return JsonResponse({
                        'success': True, 
                        'invoice_id': invoice.id,
                        'message': f'Invoice created for {deceased.full_name}'
                    })
                elif patient_id:
                    patient = get_object_or_404(Patient, pk=patient_id)
                    from home.models import Visit
                    visit = Visit.objects.filter(patient=patient, is_active=True).last()
                    
                    invoice = get_or_create_invoice(visit=visit, user=request.user)
                    if not invoice:
                        # Fallback for visit-less invoice if really needed, though get_or_create_invoice handles visit=None poorly right now
                        invoice = Invoice.objects.create(patient=patient, created_by=request.user, status='Draft')

                    if notes: invoice.notes = notes
                    if due_date: invoice.due_date = due_date
                    if total_amount: invoice.total_amount = total_amount
                    invoice.save()
                    return JsonResponse({
                        'success': True, 
                        'invoice_id': invoice.id,
                        'message': f'Invoice created for {patient.full_name}'
                    })
                else:
                    return JsonResponse({'success': False, 'error': 'No patient or deceased specified'})
                    
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
        
        # Handle regular form submission (original logic)
        invoice_type = request.POST.get('type')
        entity_id = request.POST.get('entity_id')
        
        try:
            if invoice_type == 'deceased':
                deceased = get_object_or_404(Deceased, pk=entity_id)
                invoice = get_or_create_invoice(deceased=deceased, user=request.user)
                messages.success(request, f'Invoice retrieval/creation successful for {deceased.full_name}')
                return redirect('accounts:invoice_detail', pk=invoice.pk)
            elif invoice_type == 'patient':
                patient = get_object_or_404(Patient, pk=entity_id)
                from home.models import Visit
                visit = Visit.objects.filter(patient=patient, is_active=True).last()
                invoice = get_or_create_invoice(visit=visit, user=request.user)
                if not invoice:
                    invoice = Invoice.objects.create(patient=patient, created_by=request.user, status='Draft')
                messages.success(request, f'Invoice retrieval/creation successful for {patient.full_name}')
                return redirect('accounts:invoice_detail', pk=invoice.pk)
        except Exception as e:
            messages.error(request, f'Error creating invoice: {str(e)}')
    
    # If GET request, show the form to select entity
    deceased_id = request.GET.get('deceased')
    patient_id = request.GET.get('patient')
    
    context = {
        'deceased_id': deceased_id,
        'patient_id': patient_id,
    }
    return render(request, 'accounts/create_invoice.html', context)

@login_required
@user_passes_test(is_billing_staff)
def expense_dashboard(request):
    # Filters
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    expenses = Expense.objects.all().select_related('category', 'recorded_by')
    purchases = InventoryPurchase.objects.all().select_related('supplier', 'invoice_ref', 'recorded_by')
    supplier_invoices = SupplierInvoice.objects.all().select_related('supplier', 'recorded_by')
    
    if from_date:
        expenses = expenses.filter(date__gte=from_date)
        purchases = purchases.filter(date__gte=from_date)
        supplier_invoices = supplier_invoices.filter(date__gte=from_date)
    if to_date:
        expenses = expenses.filter(date__lte=to_date)
        purchases = purchases.filter(date__lte=to_date)
        supplier_invoices = supplier_invoices.filter(date__lte=to_date)

    # Metrics
    total_expenses = expenses.aggregate(Sum('amount'))['amount__sum'] or 0
    total_purchases = purchases.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_invoice_debt = supplier_invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_invoice_paid = supplier_invoices.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
    total_payable = total_invoice_debt - total_invoice_paid

    # Category Breakdown
    category_data = expenses.values('category__name').annotate(total=Sum('amount')).order_by('-total')
    
    # Trends (Last 14 days)
    today = timezone.now().date()
    trend_labels = []
    trend_data = []
    for i in range(14, -1, -1):
        date = today - timedelta(days=i)
        trend_labels.append(date.strftime('%b %d'))
        exp_sum = Expense.objects.filter(date=date).aggregate(Sum('amount'))['amount__sum'] or 0
        pur_sum = InventoryPurchase.objects.filter(date=date).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        trend_data.append(float(exp_sum + pur_sum))

    context = {
        'expenses': expenses[:50],
        'purchases': purchases[:50],
        'supplier_invoices': supplier_invoices[:50],
        'total_expenses': total_expenses,
        'total_purchases': total_purchases,
        'total_payable': total_payable,
        'combined_total': total_expenses + total_purchases,
        'category_data': category_data,
        'trend_labels': json.dumps(trend_labels),
        'trend_data': json.dumps(trend_data),
        'categories': ExpenseCategory.objects.all(),
        'suppliers': Supplier.objects.all(),
        'expense_form': ExpenseForm(),
        'purchase_form': InventoryPurchaseForm(),
        'category_form': ExpenseCategoryForm(),
        'invoice_form': SupplierInvoiceForm(),
        'payment_form': SupplierPaymentForm(),
        'supplier_form': SupplierForm(),
        'from_date': from_date,
        'to_date': to_date,
        'today': today,
    }
    return render(request, 'accounts/expense_dashboard.html', context)

@login_required
@user_passes_test(is_accountant)
def add_supplier_invoice(request):
    if request.method == 'POST':
        form = SupplierInvoiceForm(request.POST, request.FILES)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.recorded_by = request.user
            invoice.save()
            messages.success(request, f"Invoice {invoice.invoice_number} recorded.")
        else:
            messages.error(request, f"Error: {form.errors}")
    return redirect('accounts:expense_dashboard')

@login_required
@user_passes_test(is_accountant)
def record_supplier_payment(request):
    if request.method == 'POST':
        form = SupplierPaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.recorded_by = request.user
            payment.save()
            messages.success(request, f"Payment of {payment.amount} recorded for {payment.invoice.invoice_number}.")
        else:
            messages.error(request, f"Error: {form.errors}")
    return redirect('accounts:expense_dashboard')

@login_required
@user_passes_test(is_accountant)
def add_expense(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.recorded_by = request.user
            expense.save()
            messages.success(request, "Expense recorded successfully.")
        else:
            messages.error(request, f"Error recording expense: {form.errors}")
    return redirect('accounts:expense_dashboard')


@login_required
@user_passes_test(is_accountant)
def add_expense_category(request):
    if request.method == 'POST':
        form = ExpenseCategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense category added.")
        else:
            messages.error(request, "Error adding category.")
    return redirect('accounts:expense_dashboard')

@login_required
@user_passes_test(is_accountant)
def add_supplier(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Supplier '{form.cleaned_data['name']}' added successfully.")
        else:
            messages.error(request, f"Error adding supplier: {form.errors}")
    return redirect('accounts:expense_dashboard')

@login_required
@user_passes_test(is_billing_staff)
def discharge_billing_dashboard(request):
    """Dashboard showing IPD and Maternity invoices: discharged with pending bills + active admissions"""
    from maternity.models import LaborDelivery, MaternityDischarge
    
    search_query = request.GET.get('search', '')
    
    def apply_invoice_search(queryset, query):
        if not query:
            return queryset
        search_terms = query.split()
        q_objects = Q()
        for term in search_terms:
            term_q = Q(
                Q(patient__first_name__icontains=term) |
                Q(patient__last_name__icontains=term) |
                Q(patient__id_number__icontains=term) |
                Q(patient__phone__icontains=term) |
                Q(id__icontains=term)
            )
            q_objects &= term_q
        return queryset.filter(q_objects)
    
    # --- IPD INVOICES ---
    # All IN-PATIENT invoices that are NOT maternity (no labor_delivery link)
    ipd_base = Invoice.objects.filter(
        visit__visit_type='IN-PATIENT',
        visit__labor_delivery__isnull=True,
        status__in=['Pending', 'Partial', 'Draft']
    ).annotate(
        balance_check=F('total_amount') - F('insurance_adjustment') - F('paid_amount')
    ).filter(balance_check__gt=0.01).select_related('patient', 'visit').order_by('-created_at')
    
    ipd_base = apply_invoice_search(ipd_base, search_query)
    
    # Split: discharged vs active
    ipd_discharged_invoices = ipd_base.filter(
        visit__admissions__status='Discharged'
    ).distinct()
    
    ipd_active_invoices = ipd_base.filter(
        visit__admissions__status='Admitted'
    ).distinct()
    
    # --- MATERNITY INVOICES ---
    # All IN-PATIENT invoices that ARE maternity (have labor_delivery link)
    mat_base = Invoice.objects.filter(
        visit__visit_type='IN-PATIENT',
        visit__labor_delivery__isnull=False,
        status__in=['Pending', 'Partial', 'Draft']
    ).annotate(
        balance_check=F('total_amount') - F('insurance_adjustment') - F('paid_amount')
    ).filter(balance_check__gt=0.01).select_related(
        'patient', 'visit', 'visit__labor_delivery', 'visit__labor_delivery__pregnancy'
    ).order_by('-created_at')
    
    mat_base = apply_invoice_search(mat_base, search_query)
    
    # Split: discharged (MaternityDischarge exists) vs active
    discharged_pregnancy_ids = MaternityDischarge.objects.values_list('pregnancy_id', flat=True)
    
    mat_discharged_invoices = mat_base.filter(
        visit__labor_delivery__pregnancy_id__in=discharged_pregnancy_ids
    ).distinct()
    
    mat_active_invoices = mat_base.exclude(
        visit__labor_delivery__pregnancy_id__in=discharged_pregnancy_ids
    ).distinct()
    
    # --- MORGUE (keep existing) ---
    morgue_admissions = MorgueAdmission.objects.filter(status='ADMITTED').select_related('deceased')
    
    # Summary counts
    total_discharged_pending = ipd_discharged_invoices.count() + mat_discharged_invoices.count()
    total_active = ipd_active_invoices.count() + mat_active_invoices.count()
    
    context = {
        'ipd_discharged_invoices': ipd_discharged_invoices,
        'ipd_active_invoices': ipd_active_invoices,
        'mat_discharged_invoices': mat_discharged_invoices,
        'mat_active_invoices': mat_active_invoices,
        'morgue_admissions': morgue_admissions,
        'search_query': search_query,
        'total_discharged_pending': total_discharged_pending,
        'total_active': total_active,
    }
    return render(request, 'accounts/discharge_dashboard.html', context)

@login_required
@user_passes_test(is_billing_staff)
def discharge_billing_detail(request, admission_type, admission_id):
    """Detailed billing view for IPD or Morgue discharge"""
    today = timezone.now()
    
    if admission_type == 'ipd':
        admission = get_object_or_404(Admission, pk=admission_id)
        patient = admission.patient
        entity_name = patient.full_name
        admission_date = admission.admitted_at
        
        # Calculate stay days (minimum 1)
        stay_days = max(1, (today - admission_date).days)
        daily_rate = admission.bed.ward.base_charge_per_day if (admission.bed and admission.bed.ward) else 0
        stay_total = stay_days * daily_rate
        
        # Get all services linked to this admission
        admission_services = admission.services.all().select_related('service')
        
    elif admission_type == 'morgue':
        admission = get_object_or_404(MorgueAdmission, pk=admission_id)
        deceased = admission.deceased
        entity_name = deceased.full_name
        admission_date = admission.admission_datetime
        
        # Calculate stay days (minimum 1)
        stay_days = max(1, (today - admission_date).days)
        # Search for a mortuary stay service
        mortuary_service = Service.objects.filter(name__icontains='Mortuary').first()
        daily_rate = mortuary_service.price if mortuary_service else 500 # Default if not found
        stay_total = stay_days * daily_rate
        
        admission_services = deceased.performed_services.all().select_related('service')
    else:
        return redirect('accounts:discharge_dashboard')

    # Get or create active discharge invoice
    if admission_type == 'ipd':
        # Every IPD visit should ideally have one main invoice
        invoice = Invoice.objects.filter(visit=admission.visit).exclude(status='Cancelled').first()
    else:
        # For morgue, we look for an active invoice linked to the deceased
        invoice = Invoice.objects.filter(
            deceased=deceased,
            status__in=['Draft', 'Pending', 'Partial']
        ).first()
    
    if not invoice:
        # Create a new discharge invoice if none exists
        if admission_type == 'ipd':
            invoice = get_or_create_invoice(visit=admission.visit, user=request.user)
            if invoice.notes: invoice.notes += f'\nDISCHARGE BILLING - Admission ID: {admission.id}'
            else: invoice.notes = f'DISCHARGE BILLING - Admission ID: {admission.id}'
            invoice.save()
        else:
            invoice = get_or_create_invoice(deceased=deceased, user=request.user)
            if invoice.notes: invoice.notes += f'\nDISCHARGE BILLING - Morgue Admission ID: {admission.id}'
            else: invoice.notes = f'DISCHARGE BILLING - Morgue Admission ID: {admission.id}'
            invoice.save()

    # REFACTORED SYNC LOGIC: Ensure all services and meds are on the invoice
    existing_items = invoice.items.all()
    existing_service_ids = set(existing_items.filter(service__isnull=False).values_list('service_id', flat=True))
    existing_inventory_ids = set(existing_items.filter(inventory_item__isnull=False).values_list('inventory_item_id', flat=True))
    existing_names = set(existing_items.values_list('name', flat=True))

    # 1. Sync Accommodation/Stay Charges if not already present
    # Check for any item that looks like a stay charge (Daily, Bed, Ward, Accommodation)
    has_stay_charges = existing_items.filter(service__department__name='Inpatient').exists() or any(
        keyword in name.lower() 
        for keyword in ['daily', 'bed', 'ward', 'accommodation', 'stay'] 
        for name in existing_names
    )
    
    if not has_stay_charges:
        stay_service_name = f"Accommodation Charges ({stay_days} Days @ {daily_rate})"
        InvoiceItem.objects.create(
            invoice=invoice,
            name=stay_service_name,
            unit_price=daily_rate,
            quantity=stay_days
        )
    
    # 2. Sync Performed Services (ServiceAdmissionLink)
    for adm_service in admission_services:
        if adm_service.service.id not in existing_service_ids:
            InvoiceItem.objects.create(
                invoice=invoice,
                service=adm_service.service,
                name=adm_service.service.name,
                unit_price=adm_service.service.price,
                quantity=adm_service.quantity
            )
            
    # 3. Sync Administered Medications (IPD only)
    if admission_type == 'ipd':
        administered_meds = MedicationChart.objects.filter(
            admission=admission, 
            is_administered=True
        ).select_related('item')
        
        for med in administered_meds:
            # Create a unique name to track specific medication administration instances
            med_entry_name = f"Medication: {med.item.name} ({med.dosage}) - #{med.id}"
            if med_entry_name not in existing_names:
                InvoiceItem.objects.create(
                    invoice=invoice,
                    inventory_item=med.item,
                    name=med_entry_name,
                    unit_price=med.item.selling_price,
                    quantity=1
                )

    invoice.update_totals()
            
    return redirect('accounts:invoice_detail', pk=invoice.id)

@login_required
@user_passes_test(is_billing_staff)
def authorize_discharge(request, pk):
    """Authorize formal discharge/release once invoice is paid"""
    invoice = get_object_or_404(Invoice, pk=pk)
    
    if invoice.status != 'Paid':
        messages.error(request, "Cannot authorize discharge. Invoice balance is not zero.")
        return redirect('accounts:invoice_detail', pk=pk)
    
    try:
        if invoice.patient and invoice.visit:
            # Handle Inpatient Discharge
            admission = Admission.objects.filter(visit=invoice.visit, status='Admitted').first()
            if admission:
                from inpatient.models import InpatientDischarge
                admission.status = 'Discharged'
                admission.discharged_at = timezone.now()
                admission.discharged_by = request.user
                admission.save()
                
                # Release the bed
                if admission.bed:
                    admission.bed.is_occupied = False
                    admission.bed.save()
                
                # Create formal discharge record if not exists
                InpatientDischarge.objects.get_or_create(
                    admission=admission,
                    defaults={
                        'discharged_by': request.user,
                        'total_bill_at_discharge': invoice.total_amount,
                        'discharge_summary': invoice.notes or "Automatic discharge via billing"
                    }
                )
                messages.success(request, f"Patient {invoice.patient.full_name} has been formally discharged.")
            else:
                messages.warning(request, "Admission record not found or already discharged.")
                
        elif invoice.deceased:
            # Handle Morgue Release
            admission = MorgueAdmission.objects.filter(deceased=invoice.deceased, status='ADMITTED').first()
            if admission:
                from morgue.models import MortuaryDischarge
                admission.status = 'RELEASED'
                admission.release_date = timezone.now()
                admission.save()
                
                # Mark deceased as released
                invoice.deceased.is_released = True
                invoice.deceased.release_date = timezone.now()
                invoice.deceased.save()
                
                # Create formal release record
                MortuaryDischarge.objects.get_or_create(
                    deceased=invoice.deceased,
                    admission=admission,
                    defaults={
                        'authorized_by': request.user,
                        'total_bill_snapshot': invoice.total_amount,
                        'released_to': "See Next of Kin", # Placeholder
                        'relationship': "Family",
                        'receiver_id_number': "N/A"
                    }
                )
                messages.success(request, f"Deceased {invoice.deceased.full_name} has been formally released.")
            else:
                messages.warning(request, "Morgue admission record not found or already released.")
                
    except Exception as e:
        messages.error(request, f"Error during authorization: {str(e)}")
        
    return redirect('accounts:discharge_billing_dashboard')
@login_required
def search_procedures(request):
    """
    JSON API for searching procedures.
    """
    from .models import Service
    query = request.GET.get('q', '')
    if len(query) < 2:
        return JsonResponse({'results': []})
        
    procedures = Service.objects.filter(department__name='Procedure Room', name__icontains=query, is_active=True)[:20]
    results = []
    for proc in procedures:
        results.append({
            'id': proc.id,
            'text': f"{proc.name} (KES {proc.price})",
            'price': str(proc.price)
        })
    return JsonResponse({'results': results})

@login_required
@require_POST
def charge_procedure(request):
    """
    Handle procedure charging via AJAX.
    """
    from .models import Service, Invoice, InvoiceItem
    
    procedure_id = request.POST.get('procedure_id')
    patient_id = request.POST.get('patient_id')
    visit_id = request.POST.get('visit_id')
    notes = request.POST.get('notes', '')

    try:
        service = get_object_or_404(Service, id=procedure_id, department__name='Procedure Room')
        patient = get_object_or_404(Patient, id=patient_id)
        visit = Visit.objects.filter(id=visit_id).first() if visit_id else None

        # Find or Create Active Invoice for this Visit
        invoice = get_or_create_invoice(visit=visit, user=request.user)
        if invoice and not invoice.notes:
             invoice.notes = f"Procedure Charge: {service.name}"
             invoice.save()

        # Create Invoice Item
        InvoiceItem.objects.create(
            invoice=invoice,
            service=service,
            name=service.name,
            unit_price=service.price,
            quantity=1,
            created_by=request.user
        )
        
        # Update Invoice Totals
        invoice.update_totals()
        
        return JsonResponse({
            'status': 'success', 
            'message': f'Successfully charged {service.name}'
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


# ─── Service Management ──────────────────────────────────────────

@login_required
@user_passes_test(is_accountant)
def service_list(request):
    """List all services with search and filter"""
    services = Service.objects.all().select_related('department').order_by('name')

    search = request.GET.get('search', '')
    department_filter = request.GET.get('department', '')
    status_filter = request.GET.get('status', '')

    if search:
        services = services.filter(
            Q(name__icontains=search) | Q(department__name__icontains=search)
        )
    if department_filter:
        services = services.filter(department_id=department_filter)
    if status_filter == 'active':
        services = services.filter(is_active=True)
    elif status_filter == 'inactive':
        services = services.filter(is_active=False)

    from home.models import Departments
    context = {
        'services': services,
        'form': ServiceForm(),
        'search_query': search,
        'department_filter': department_filter,
        'status_filter': status_filter,
        'departments': Departments.objects.all().order_by('name'),
        'total_services': services.count(),
        'active_count': services.filter(is_active=True).count(),
        'inactive_count': services.filter(is_active=False).count(),
    }
    return render(request, 'accounts/service_manager.html', context)


@login_required
@user_passes_test(is_accountant)
@require_POST
def create_service(request):
    """Create a new service"""
    form = ServiceForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, f"Service '{form.cleaned_data['name']}' created successfully.")
    else:
        messages.error(request, f"Error creating service: {form.errors.as_text()}")
    return redirect('accounts:service_list')


@login_required
@user_passes_test(is_accountant)
def edit_service(request, pk):
    """Edit a service — GET returns JSON, POST updates"""
    service = get_object_or_404(Service, pk=pk)

    if request.method == 'GET':
        return JsonResponse({
            'id': service.id,
            'name': service.name,
            'department': service.department_id,
            'price': float(service.price),
            'description': service.description or '',
            'is_active': service.is_active,
        })

    if request.method == 'POST':
        form = ServiceForm(request.POST, instance=service)
        if form.is_valid():
            svc = form.save(commit=False)
            svc.is_updated = True
            svc.save()
            messages.success(request, f"Service '{service.name}' updated successfully.")
        else:
            messages.error(request, f"Error updating service: {form.errors.as_text()}")
        return redirect('accounts:service_list')

    return HttpResponse(status=405)


@login_required
@user_passes_test(is_accountant)
@require_POST
def toggle_service(request, pk):
    """Toggle a service's active status"""
    service = get_object_or_404(Service, pk=pk)
    service.is_active = not service.is_active
    service.save()
    status_text = 'activated' if service.is_active else 'deactivated'
    messages.success(request, f"Service '{service.name}' {status_text}.")
    return redirect('accounts:service_list')


@login_required
@user_passes_test(is_billing_staff)
@require_POST
def set_visit_sha(request):
    """Set the payment method of a patient's latest active visit to SHA."""
    try:
        patient_id = request.POST.get('patient_id')
        patient = get_object_or_404(Patient, pk=patient_id)
        visit = Visit.objects.filter(patient=patient, is_active=True).order_by('-visit_date').first()
        if not visit:
            return JsonResponse({'success': False, 'error': f'No active visit found for {patient.full_name}.'})
        visit.payment_method = 'SHA'
        visit.save()
        return JsonResponse({
            'success': True,
            'message': f'{patient.full_name} (Visit #{visit.id}) updated to SHA.',
            'visit_id': visit.id,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@user_passes_test(is_billing_staff)
@require_POST
def bulk_set_visit_sha(request):
    """Set the payment method of multiple active visits to SHA."""
    try:
        visit_ids = request.POST.getlist('visit_ids[]')
        if not visit_ids:
            return JsonResponse({'success': False, 'error': 'No visits selected.'})
            
        from home.models import Visit
        visits = Visit.objects.filter(id__in=visit_ids, is_active=True)
        updated_count = visits.update(payment_method='SHA')
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully updated {updated_count} visits to SHA.',
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@user_passes_test(can_view_invoice)
def manage_visit_invoices(request, visit_id):
    """Superuser-only page to view and manage invoice items for a visit."""
    from home.models import Visit
    visit = get_object_or_404(Visit, pk=visit_id)
    invoice = Invoice.objects.filter(visit=visit).first()
    
    items = []
    if invoice:
        items = invoice.items.all().order_by('-created_at')
    
    context = {
        'visit': visit,
        'invoice': invoice,
        'items': items,
        'patient': visit.patient,
        'title': f'Manage Invoice — Visit #{visit.id}',
    }
    return render(request, 'accounts/manage_visit_invoices.html', context)

@login_required
def sha_claims_desk(request, visit_id):
    """End-to-end SHA eClaims desk for a visit."""
    from home.models import Visit, Diagnosis, PrescriptionItem
    from accounts.models import ShaClaimSession, Invoice
    from accounts.sha_claims_service import get_or_create_claim_session
    from django.conf import settings as django_settings

    visit = get_object_or_404(Visit, pk=visit_id)
    if request.user.role not in (
        'Admin', 'SHA Manager', 'Accountant', 'Doctor', 'Receptionist'
    ) and not request.user.is_superuser:
        messages.error(request, 'You do not have access to the SHA claims desk.')
        return redirect('home:patient_detail', pk=visit.patient_id)

    session = get_or_create_claim_session(visit, request.user)
    invoice = Invoice.objects.filter(visit=visit).order_by('-id').first()
    diagnoses = Diagnosis.objects.filter(visit=visit).order_by('-id')[:20]
    rx_items = PrescriptionItem.objects.filter(
        prescription__visit=visit
    ).select_related('medication', 'medication__medication')

    return render(request, 'accounts/sha_claims_desk.html', {
        'visit': visit,
        'patient': visit.patient,
        'session': session,
        'invoice': invoice,
        'diagnoses': diagnoses,
        'rx_items': rx_items,
        'facility_fr': getattr(django_settings, 'SHA_HIE_FACILITY_FR_CODE', ''),
        'default_intervention': (session.intervention_codes or [None])[0],
    })


@login_required
@require_POST
def sha_claims_action(request, visit_id):
    """JSON actions: eligibility, start_visit, erx, dispense, preauth, submit, close."""
    from home.models import Visit
    from accounts.sha_claims_service import (
        get_or_create_claim_session,
        refresh_eligibility,
        start_visit_with_otp,
        submit_erx_for_visit,
        submit_erx_dispense,
        create_normal_preauth,
        submit_claim,
    )
    from accounts.sha_hie_service import ShaHieClient, ShaHieError
    from accounts.models import Invoice
    import json as _json

    visit = get_object_or_404(Visit, pk=visit_id)
    if request.user.role not in (
        'Admin', 'SHA Manager', 'Accountant', 'Doctor', 'Receptionist'
    ) and not request.user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Forbidden'}, status=403)

    try:
        data = _json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        data = {}
    action = (data.get('action') or request.POST.get('action') or '').strip()
    session = get_or_create_claim_session(visit, request.user)

    # Allow updating intervention codes / practitioner before start
    if data.get('intervention_codes'):
        codes = data.get('intervention_codes')
        if isinstance(codes, str):
            codes = [c.strip() for c in codes.split(',') if c.strip()]
        session.intervention_codes = codes
        session.save(update_fields=['intervention_codes', 'updated_at'])
    for field in (
        'practitioner_identification_type',
        'practitioner_identification_number',
        'practitioner_regulation_body',
        'service_type',
    ):
        if data.get(field):
            setattr(session, field, str(data.get(field)).strip())
            session.save(update_fields=[field, 'updated_at'])

    try:
        if action == 'eligibility':
            session = refresh_eligibility(session)
        elif action == 'send_otp':
            client = ShaHieClient()
            raw = client.send_claim_otp(
                patient_id=session.patient_cr_id or visit.patient.cr_id or '',
                phone=getattr(visit.patient, 'phone', None),
            )
            session.status = 'otp_sent'
            session.last_error = ''
            session.save(update_fields=['status', 'last_error', 'updated_at'])
            return JsonResponse({'success': True, 'action': action, 'otp_response': raw, 'session': _session_payload(session)})
        elif action == 'start_visit':
            otp = (data.get('otp') or '').strip()
            if not otp:
                return JsonResponse({'success': False, 'error': 'OTP is required.'}, status=400)
            session = start_visit_with_otp(session, otp=otp, practitioner=request.user)
        elif action == 'erx':
            session = submit_erx_for_visit(session, practitioner=request.user)
        elif action == 'dispense':
            session = submit_erx_dispense(session, practitioner=request.user)
        elif action == 'preauth':
            session = create_normal_preauth(
                session,
                unit_price=str(data.get('unit_price') or '0'),
                icd_code=(data.get('icd_code') or '').strip(),
            )
        elif action == 'submit':
            invoice = None
            if data.get('invoice_id'):
                invoice = Invoice.objects.filter(pk=data.get('invoice_id'), visit=visit).first()
            else:
                invoice = Invoice.objects.filter(visit=visit).order_by('-id').first()
            session = submit_claim(
                session,
                otp=(data.get('otp') or None),
                invoice=invoice,
                notes=(data.get('notes') or ''),
            )
        elif action == 'close':
            client = ShaHieClient()
            raw = client.close_virtual_claim(
                consent_token=session.consent_token,
                cancel_reason_type=(data.get('cancel_reason_type') or 'OTHER_REASONS'),
                cancel_reason_text=(data.get('cancel_reason_text') or 'Closed from HMS'),
            )
            session.status = 'closed'
            session.submit_raw = {**(session.submit_raw or {}), 'close': raw}
            session.save()
        elif action == 'status':
            if not session.claim_id:
                return JsonResponse({'success': False, 'error': 'No claim_id yet.'}, status=400)
            raw = ShaHieClient().get_claim_status(session.claim_id)
            return JsonResponse({'success': True, 'action': action, 'status_raw': raw, 'session': _session_payload(session)})
        else:
            return JsonResponse({'success': False, 'error': f'Unknown action: {action}'}, status=400)
    except (ShaHieError, ValueError) as exc:
        return JsonResponse({'success': False, 'error': str(exc), 'session': _session_payload(session)}, status=400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

    return JsonResponse({'success': True, 'action': action, 'session': _session_payload(session)})


def _session_payload(session):
    return {
        'id': session.id,
        'status': session.status,
        'service_type': session.service_type,
        'intervention_codes': session.intervention_codes,
        'patient_cr_id': session.patient_cr_id,
        'eligible': session.eligible,
        'consent_token': session.consent_token,
        'claim_id': session.claim_id,
        'edi_claim_guid': session.edi_claim_guid,
        'workflow_state': session.workflow_state,
        'last_error': session.last_error,
        'practitioner_identification_number': session.practitioner_identification_number,
    }
