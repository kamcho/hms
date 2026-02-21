from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.urls import reverse
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from .models import (
    Pregnancy, AntenatalVisit, LaborDelivery, Newborn, 
    PostnatalMotherVisit, PostnatalBabyVisit, MaternityDischarge, MaternityReferral,
    Vaccine, ImmunizationRecord
)
from .forms import (
    PregnancyRegistrationForm, AntenatalVisitForm, LaborDeliveryForm, NewbornForm,
    PostnatalMotherVisitForm, PostnatalBabyVisitForm, MaternityDischargeForm, 
    MaternityReferralForm, ImmunizationRecordForm
)
from accounts.models import InvoiceItem, Service, Invoice
from accounts.utils import get_or_create_invoice
from home.models import PatientQue, Departments, Visit, Prescription, PrescriptionItem # Added Visit, Prescription, PrescriptionItem
from home.forms import PrescriptionItemForm # Added PrescriptionItemForm


@login_required
def maternity_dashboard(request):
    """Maternity ward overview dashboard (Ward Management focal point)"""
    
    # Active pregnancies
    active_pregnancies = Pregnancy.objects.filter(status='Active').select_related('patient')
    
    # Statistics
    total_active = active_pregnancies.count()
    high_risk = active_pregnancies.filter(risk_level='High').count()
    
    # Overdue pregnancies (EDD passed)
    today = timezone.now().date()
    overdue = active_pregnancies.filter(edd__lt=today).count()
    
    # Due this week
    week_from_now = today + timedelta(days=7)
    due_this_week = active_pregnancies.filter(edd__gte=today, edd__lte=week_from_now).count()
    
    # Recent deliveries (last 7 days)
    week_ago = timezone.now() - timedelta(days=7)
    recent_deliveries = LaborDelivery.objects.filter(
        delivery_datetime__gte=week_ago
    ).select_related('pregnancy__patient').order_by('-delivery_datetime')[:10]
    
    # Total deliveries this month
    month_start = today.replace(day=1)
    deliveries_this_month = LaborDelivery.objects.filter(
        delivery_datetime__gte=month_start
    ).count()
    
    # Current Newborns in facility
    current_newborns = Newborn.objects.filter(
        birth_datetime__gte=week_ago,
        status__in=['Alive', 'NICU']
    ).select_related('delivery__pregnancy__patient')
    
    # Delivery Queue (Mothers delivered but not discharged)
    maternity_arrivals = Pregnancy.objects.filter(             # Only check delivered pregnancies
        delivery__isnull=False,             # Has delivered
        maternity_discharge__isnull=True    # Has not been discharged
    ).select_related('patient', 'delivery').order_by('-delivery__delivery_datetime')
    
    context = {
        'active_pregnancies': active_pregnancies[:20],
        'total_active': total_active,
        'high_risk_count': high_risk,
        'overdue_count': overdue,
        'due_this_week_count': due_this_week,
        'recent_deliveries': recent_deliveries,
        'deliveries_this_month': deliveries_this_month,
        'current_newborns': current_newborns,
        'maternity_arrivals': maternity_arrivals,
        'today': today,
    }
    
    return render(request, 'maternity/dashboard.html', context)


@login_required
def anc_dashboard(request):
    """Dedicated Antenatal Care Dashboard"""
    today = timezone.now().date()
    
    # Recent ANC Visits (last 20)
    recent_anc_visits = AntenatalVisit.objects.select_related('pregnancy__patient').order_by('-visit_date')[:20]
    
    # Weekly Activity Trends (Last 8 weeks)
    trends = []
    for i in range(8):
        start = today - timedelta(days=(i+1)*7)
        end = today - timedelta(days=i*7)
        anc_count = AntenatalVisit.objects.filter(visit_date__gte=start, visit_date__lte=end).count()
        trends.append({
            'label': f"{start.strftime('%d %b')}",
            'anc': anc_count
        })
    trends.reverse()
    
    # Statistics for ANC
    total_anc_this_month = AntenatalVisit.objects.filter(visit_date__gte=today.replace(day=1)).count()
    active_count = Pregnancy.objects.filter(status='Active').count()
    anc_coverage = int((total_anc_this_month / (active_count * 1.0)) * 100) if active_count > 0 else 0

    # ANC Receiving Queue (Existing Visits)
    search_query = request.GET.get('q', '')
    anc_queue = AntenatalVisit.objects.filter(
        is_closed=False,
        visit_date=today
    ).select_related('pregnancy__patient').order_by('created_at')

    # New Arrivals (using PatientQue)
    # Filter by 'ANC' department OR 'Maternity' fallback
    new_arrivals_raw = PatientQue.objects.filter(
        Q(sent_to__name__iexact='ANC') | Q(sent_to__name__iexact='Maternity'),
        visit__visit_date__date=today,
        visit__is_active=True,
        status__iexact='PENDING'
    ).select_related('visit__patient').prefetch_related('visit__invoice__items').order_by('-created_at')
 
    new_arrivals = []
    seen_patients = set()
    
    for que in new_arrivals_raw:
        if que.visit.patient.id in seen_patients:
            continue
            
        # Determine if it's registration or follow-up
        que.is_anc_registration = True
        if hasattr(que.visit, 'invoice'):
            for item in que.visit.invoice.items.all():
                if item.service and "ANC" in item.service.name.upper():
                    if any(x in item.service.name.upper() for x in ["FOLLOW", "REVISIT"]):
                        que.is_anc_registration = False
                    break
        
        que.active_pregnancy = Pregnancy.objects.filter(patient=que.visit.patient, status='Active').first()
        que.linked_anc_visit = AntenatalVisit.objects.filter(visit=que.visit).first()
        if que.active_pregnancy:
            que.active_anc_visit = AntenatalVisit.objects.filter(
                pregnancy=que.active_pregnancy, 
                is_closed=False, 
                visit_date=today
            ).first()
        new_arrivals.append(que)
        seen_patients.add(que.visit.patient.id)

    if search_query:
        anc_queue = anc_queue.filter(
            Q(pregnancy__patient__first_name__icontains=search_query) |
            Q(pregnancy__patient__last_name__icontains=search_query) |
            Q(pregnancy__id__icontains=search_query)
        )
        new_arrivals = [n for n in new_arrivals if search_query.lower() in n.visit.patient.full_name.lower()]
    
    # Attach alerts to each visit object for the template
    for visit in anc_queue:
        visit.alerts = visit.pregnancy.get_active_alerts()
        visit.is_high_risk = any(a['type'] == 'danger' for a in visit.alerts)

    context = {
        'recent_anc_visits': recent_anc_visits,
        'trends': trends,
        'total_anc_month': total_anc_this_month,
        'anc_coverage': min(anc_coverage, 100),
        'anc_queue': anc_queue,
        'new_arrivals': new_arrivals,
        'search_query': search_query,
        'today': today,
    }
    return render(request, 'maternity/anc_dashboard.html', context)


@login_required
def pnc_dashboard(request):
    """Dedicated Postnatal Care Dashboard"""
    today = timezone.now().date()
    
    # Recent PNC Visits
    recent_mother_pnc = PostnatalMotherVisit.objects.select_related('delivery__pregnancy__patient').order_by('-visit_date')[:15]
    recent_baby_pnc = PostnatalBabyVisit.objects.select_related('newborn__delivery__pregnancy__patient').order_by('-visit_date')[:15]
    
    # Weekly Activity Trends (Last 8 weeks)
    trends = []
    for i in range(8):
        start = today - timedelta(days=(i+1)*7)
        end = today - timedelta(days=i*7)
        pnc_m_count = PostnatalMotherVisit.objects.filter(visit_date__gte=start, visit_date__lte=end).count()
        pnc_b_count = PostnatalBabyVisit.objects.filter(visit_date__gte=start, visit_date__lte=end).count()
        trends.append({
            'label': f"{start.strftime('%d %b')}",
            'pnc_m': pnc_m_count,
            'pnc_b': pnc_b_count
        })
    trends.reverse()
    
    # Statistics for PNC
    total_pnc_this_month = PostnatalMotherVisit.objects.filter(visit_date__gte=today.replace(day=1)).count() + \
                           PostnatalBabyVisit.objects.filter(visit_date__gte=today.replace(day=1)).count()
    
    # PNC Receiving Queues
    search_query = request.GET.get('q', '')
    mother_queue = PostnatalMotherVisit.objects.filter(
        service_received=False,
        visit_date=today
    ).select_related('delivery__pregnancy__patient').order_by('created_at')
    
    baby_queue = PostnatalBabyVisit.objects.filter(
        service_received=False,
        visit_date=today
    ).select_related('newborn__delivery__pregnancy__patient').order_by('created_at')

    # New Arrivals from Triage (using PatientQue)
    # Filter by explicit 'PNC' or fallback to 'Maternity' (legacy)
    new_arrivals_raw = PatientQue.objects.filter(
        Q(sent_to__name='PNC') | Q(sent_to__name='Maternity'), 
        visit__visit_date__date=today
    ).select_related('visit__patient').prefetch_related('visit__invoice__items').order_by('-created_at')

    new_pnc_arrivals = []
    seen_patients_pnc = set()
    
    for que in new_arrivals_raw:
        is_pnc = False
        
        # 1. Explicit Department Routing
        if que.sent_to and que.sent_to.name == 'PNC':
            is_pnc = True
        
        # 2. Service-based fallback (Legacy)
        elif que.sent_to and que.sent_to.name == 'Maternity':
            if hasattr(que.visit, 'invoice') and que.visit.invoice:
                for item in que.visit.invoice.items.all():
                    if item.service and "PNC" in item.service.name.upper():
                        is_pnc = True
                        break
        
        if is_pnc:
            if que.visit.patient.id in seen_patients_pnc:
                continue

            patient = que.visit.patient
            # Case 1: Mother arrival
            if patient.gender == 'F' and patient.age >= 12:
                has_mother_visit = PostnatalMotherVisit.objects.filter(delivery__pregnancy__patient=patient, visit_date=today).exists()
                if not has_mother_visit:
                    que.active_pregnancy = Pregnancy.objects.filter(patient=patient, status='Delivered').first()
                    que.arrival_type = 'Mother'
                    new_pnc_arrivals.append(que)
                    seen_patients_pnc.add(patient.id)
            
            # Case 2: Child arrival (specifically registered as patient)
            elif patient.age <= 5:
                has_baby_visit = PostnatalBabyVisit.objects.filter(newborn__patient_profile=patient, visit_date=today).exists()
                if not has_baby_visit:
                    linked_newborn = Newborn.objects.filter(patient_profile=patient).first()
                    
                    if not linked_newborn:
                        # Fallback: Try to find by name match if not directly linked
                        # This is a bit fuzzy but helps if link is missing
                        linked_newborn = Newborn.objects.filter(
                            delivery__pregnancy__patient__last_name__iexact=patient.last_name,
                            birth_datetime__date=patient.date_of_birth
                        ).first()
                    
                    if linked_newborn:
                        que.linked_newborn = linked_newborn
                    
                    # Always add child to queue, even if no linked newborn record (External)
                    que.arrival_type = 'Child'
                    new_pnc_arrivals.append(que)
                    seen_patients_pnc.add(patient.id)

    if search_query:
        mother_queue = mother_queue.filter(
            Q(delivery__pregnancy__patient__first_name__icontains=search_query) |
            Q(delivery__pregnancy__patient__last_name__icontains=search_query)
        )
        baby_queue = baby_queue.filter(
            Q(newborn__delivery__pregnancy__patient__first_name__icontains=search_query) |
            Q(newborn__delivery__pregnancy__patient__last_name__icontains=search_query)
        )
        new_pnc_arrivals = [n for n in new_pnc_arrivals if search_query.lower() in n.visit.patient.full_name.lower()]

    # Attach alerts to mother queue items
    for visit in mother_queue:
        visit.alerts = visit.delivery.pregnancy.get_active_alerts()
        visit.is_high_risk = any(a['type'] == 'danger' for a in visit.alerts)

    context = {
        'recent_mother_pnc': recent_mother_pnc,
        'recent_baby_pnc': recent_baby_pnc,
        'trends': trends,
        'total_pnc_month': total_pnc_this_month,
        'mother_queue': mother_queue,
        'baby_queue': baby_queue,
        'new_pnc_arrivals': new_pnc_arrivals,
        'search_query': search_query,
        'today': today,
    }
    return render(request, 'maternity/pnc_dashboard.html', context)


@login_required
def register_pregnancy(request):
    """Register new pregnancy"""
    from .forms import PregnancyRegistrationForm
    patient_id = request.GET.get('patient_id')
    
    if request.method == 'POST':
        form = PregnancyRegistrationForm(request.POST)
        if form.is_valid():
            pregnancy = form.save(commit=False)
            
            # Deactivate all previous active pregnancies for this patient
            Pregnancy.objects.filter(
                patient=pregnancy.patient, 
                status='Active'
            ).update(status='Delivered')
            
            pregnancy.created_by = request.user
            pregnancy.save()
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    else:
        initial = {}
        if patient_id:
            initial['patient'] = patient_id
        form = PregnancyRegistrationForm(initial=initial)
    
    return render(request, 'maternity/register_pregnancy.html', {'form': form})


@login_required
def register_external_delivery(request):
    """Register a delivery that happened outside the facility for PNC follow-up"""
    from .forms import ExternalDeliveryForm
    from datetime import timedelta
    
    patient_id = request.GET.get('patient_id')
    child_patient_id = request.GET.get('child_patient_id')
    
    if request.method == 'POST':
        form = ExternalDeliveryForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            
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
                created_by=request.user
            )
            
            # 2. Create LaborDelivery record
            delivery = LaborDelivery.objects.create(
                pregnancy=pregnancy,
                delivery_datetime=data['delivery_datetime'],
                delivery_mode=data['delivery_mode'],
                gestational_age_at_delivery=40,
                labor_onset='Spontaneous'
            )
            
            # 2b. Create Inpatient Visit and Invoice for External Delivery
            from home.models import Visit
            from accounts.models import Service, InvoiceItem
            from accounts.utils import get_or_create_invoice
            
            visit = Visit.objects.create(
                patient=data['patient'],
                visit_type='IN-PATIENT',
                visit_date=timezone.now()
            )
            delivery.visit = visit
            delivery.save()
            
            invoice = get_or_create_invoice(visit=visit, user=request.user)
            service, _ = Service.objects.get_or_create(
                name='Normal Delivery',
                defaults={'price': 10000} # Provide a default valid price
            )
            InvoiceItem.objects.create(
                invoice=invoice,
                service=service,
                name=service.name,
                unit_price=service.price,
                quantity=1
            )
            
            # 3. Create Newborn record(s)
            num_babies = data.get('number_of_babies', 1)
            child_patient = data.get('child_patient')
            
            for i in range(num_babies):
                # Link the first baby to the child_patient profile if provided
                profile = child_patient if i == 0 else None
                
                Newborn.objects.create(
                    delivery=delivery,
                    patient_profile=profile,
                    baby_number=i+1,
                    gender='A',
                    birth_datetime=data['delivery_datetime'],
                    birth_weight=0,
                    apgar_1min=9,
                    apgar_5min=10,
                    status=data['outcome'],
                    created_by=request.user
                )
            
            return redirect('maternity:pnc_dashboard')
    else:
        form = ExternalDeliveryForm(patient_id=patient_id, child_patient_id=child_patient_id)
        
    return render(request, 'maternity/register_external_delivery.html', {'form': form})


@login_required
def receive_anc_arrival(request, que_id):
    """Transition patient from Triage queue to ANC clinical queue"""
    que = get_object_or_404(PatientQue, id=que_id)
    pregnancy = Pregnancy.objects.filter(patient=que.visit.patient, status='Active').first()
    
    if pregnancy:
        # Check for existing OPEN ANC visit today (closed ones don't block a new visit)
        existing_visit = AntenatalVisit.objects.filter(
            pregnancy=pregnancy,
            visit_date=timezone.now().date(),
            is_closed=False
        ).first()
        
        if not existing_visit:
            AntenatalVisit.objects.create(
                pregnancy=pregnancy,
                visit=que.visit,
                visit_date=timezone.now().date(),
                visit_number=(pregnancy.anc_visits.count() + 1),
                gestational_age=pregnancy.gestational_age_weeks,
                service_received=False,
                is_closed=False,
                recorded_by=request.user
            )
    
    # Mark ALL pending queue entries for this visit/patient as completed to prevent duplicates in list
    PatientQue.objects.filter(
        visit=que.visit,
        status='PENDING',
        sent_to__name__in=['ANC', 'Maternity']
    ).update(status='COMPLETED')
    
    messages.success(request, f'{que.visit.patient.full_name} has been received and queued for ANC.')
    
    return redirect('maternity:anc_dashboard')


@login_required
def close_anc_visit(request, visit_id):
    """Close an ANC visit — marks it as completed so it leaves the clinical queue"""
    anc_visit = get_object_or_404(AntenatalVisit, id=visit_id)
    anc_visit.is_closed = True
    anc_visit.service_received = True
    anc_visit.save()
    
    messages.success(request, f'ANC Visit #{anc_visit.visit_number} for {anc_visit.pregnancy.patient.full_name} has been closed.')
    
    return redirect('maternity:pregnancy_detail', pregnancy_id=anc_visit.pregnancy.id)


@login_required
def receive_pnc_arrival(request, que_id):
    """Transition patient from Triage queue to PNC clinical queue"""
    que = get_object_or_404(PatientQue, id=que_id)
    patient = que.visit.patient
    
    # Case 1: Child Arrival
    if patient.age <= 5:
        # Try to find linked newborn
        newborn = Newborn.objects.filter(patient_profile=patient).first()
        
        # Fuzzy match fallback
        if not newborn:
            newborn = Newborn.objects.filter(
                delivery__pregnancy__patient__last_name__iexact=patient.last_name,
                birth_datetime__date=patient.date_of_birth
            ).first()
            
        if newborn:
            # Create a pending PNC visit record for baby
            PostnatalBabyVisit.objects.get_or_create(
                newborn=newborn,
                visit=que.visit,
                visit_date=timezone.now().date(),
                defaults={
                    'service_received': False,
                    'recorded_by': request.user
                }
            )
            
            # Clean up queue
            PatientQue.objects.filter(
                visit=que.visit,
                status='PENDING',
                sent_to__name__in=['PNC', 'Maternity']
            ).update(status='COMPLETED')
            
            return redirect('maternity:pnc_dashboard')
        else:
            # No newborn record found - redirect to external delivery registration
            return redirect(f"{reverse('maternity:register_external_delivery')}?child_patient_id={patient.id}")

    # Case 2: Mother Arrival (Existing logic)
    pregnancy = Pregnancy.objects.filter(patient=patient, status='Delivered').first()
    
    if pregnancy:
        # Check for matching delivery
        delivery = LaborDelivery.objects.filter(pregnancy=pregnancy).first()
        if delivery:
            # Create a pending PNC visit record
            PostnatalMotherVisit.objects.get_or_create(
                delivery=delivery,
                visit=que.visit,
                visit_date=timezone.now().date(),
                defaults={
                    'visit_day': (timezone.now().date() - delivery.delivery_datetime.date()).days,
                    'service_received': False,
                    'recorded_by': request.user
                }
            )
    
    # Clean up queue (for mother too)
    PatientQue.objects.filter(
        visit=que.visit,
        status='PENDING',
        sent_to__name__in=['PNC', 'Maternity']
    ).update(status='COMPLETED')
            
    return redirect('maternity:pnc_dashboard')


@login_required
def pregnancy_detail(request, pregnancy_id):
    """Detailed pregnancy record view"""
    import json
    
    pregnancy = get_object_or_404(
        Pregnancy.objects.select_related('patient', 'created_by'),
        id=pregnancy_id
    )
    
    # Get all ANC visits
    anc_visits = pregnancy.anc_visits.all().order_by('visit_number')
    
    # Check if delivered
    has_delivery = hasattr(pregnancy, 'delivery')
    delivery = pregnancy.delivery if has_delivery else None
    newborns = delivery.newborns.all() if has_delivery else []
    
    # Postnatal visits
    mother_pnc_visits = pregnancy.delivery.mother_pnc_visits.all() if has_delivery else []
    
    # Discharge & Referral
    discharge = getattr(pregnancy, 'maternity_discharge', None)
    referrals = pregnancy.referrals.all().order_by('-referral_date')
    
    # Get medical tests services for the Next Action section
    medical_tests = Service.objects.filter(
        is_active=True,
        department__isnull=False
    ).select_related('department').order_by('department__name', 'name')
    
    # Prepare medical tests data as JSON for JavaScript
    medical_tests_data = []
    for test in medical_tests:
        medical_tests_data.append({
            'id': test.pk,
            'name': test.name,
            'department_id': test.department.id,
            'department_name': test.department.name,
            'price': str(test.price) if test.price else None
        })
    
    # Lab results and reports
    # Get lab results and organize them by date
    from lab.models import LabResult, LabReport
    from home.models import PrescriptionItem
    lab_results = LabResult.objects.filter(patient=pregnancy.patient).select_related('service', 'requested_by').order_by('-requested_at')
    
    # Get prescriptions and organize them by date
    prescriptions = PrescriptionItem.objects.filter(prescription__patient=pregnancy.patient).select_related('medication', 'prescription').order_by('-prescription__prescribed_at')
    
    # Group results and prescriptions by date for easy linking
    lab_results_by_date = {}
    for result in lab_results:
        date_key = result.requested_at.date()
        if date_key not in lab_results_by_date:
            lab_results_by_date[date_key] = []
        lab_results_by_date[date_key].append(result)

    prescriptions_by_date = {}
    for item in prescriptions:
        date_key = item.prescription.prescribed_at.date()
        if date_key not in prescriptions_by_date:
            prescriptions_by_date[date_key] = []
        prescriptions_by_date[date_key].append(item)

    # Attach lab results and prescriptions to ANC visits
    for visit in anc_visits:
        if visit.visit:
             # Exact match via Visit object
             visit.related_lab_results = lab_results.filter(invoice__visit=visit.visit)
             visit.related_prescriptions = prescriptions.filter(prescription__visit=visit.visit)
        else:
             # Fallback to date grouping if no direct link exists
             visit.related_lab_results = lab_results_by_date.get(visit.visit_date, [])
             visit.related_prescriptions = prescriptions_by_date.get(visit.visit_date, [])
        
    # Attach lab results and prescriptions to Mother PNC visits
    for visit in mother_pnc_visits:
        if visit.visit:
             visit.related_lab_results = lab_results.filter(invoice__visit=visit.visit)
             visit.related_prescriptions = prescriptions.filter(prescription__visit=visit.visit)
        else:
             visit.related_lab_results = lab_results_by_date.get(visit.visit_date, [])
             visit.related_prescriptions = prescriptions_by_date.get(visit.visit_date, [])
    
    # Get lab reports for this patient
    lab_report_ids = lab_results.values_list('id', flat=True)
    lab_reports = LabReport.objects.filter(lab_result_id__in=lab_report_ids).select_related('lab_result', 'created_by').order_by('-created_at')
    
    # Get maternity specific services for quick billing
    maternity_dept = Departments.objects.filter(name='Maternity').first()
    maternity_services = Service.objects.filter(
        department=maternity_dept,
        is_active=True
    ).order_by('name')

    # Get dispensed items history (Normalized from both InvoiceItem and DispensedItem)
    from inventory.models import DispensedItem, StockRecord, StockAdjustment
    from accounts.models import Invoice, InvoiceItem
    
    today = timezone.now().date()
    latest_visit = Visit.objects.filter(
        patient=pregnancy.patient,
        visit_date__date=today,
        is_active=True
    ).last()
    
    # 1. Fetch physical dispensations (Stock deducted)
    if latest_visit:
        d_items = DispensedItem.objects.filter(visit=latest_visit).select_related('item', 'dispensed_by').order_by('-dispensed_at')
    else:
        d_items = DispensedItem.objects.filter(patient=pregnancy.patient).order_by('-dispensed_at')[:20]
        
    # 2. Fetch billed items (Requested by doctor but might not be dispensed yet)
    if latest_visit:
        billed_items = InvoiceItem.objects.filter(
            invoice__visit=latest_visit,
            inventory_item__isnull=False
        ).select_related('inventory_item', 'invoice__created_by').order_by('-created_at')
    else:
        billed_items = InvoiceItem.objects.filter(
            invoice__patient=pregnancy.patient,
            inventory_item__isnull=False
        ).select_related('inventory_item', 'invoice__created_by').order_by('-created_at')[:20]
        
    # 3. Combine and Normalize
    dispensed_history = []
    
    # Add physically dispensed items
    for d in d_items:
        dispensed_history.append({
            'item_name': d.item.name,
            'quantity': d.quantity,
            'at': d.dispensed_at,
            'by': d.dispensed_by,
            'status': 'Dispensed',
            'status_class': 'bg-emerald-50 text-emerald-700'
        })
        
    # Add billed items (only if NOT already in physically dispensed to avoid duplicates)
    dispensed_keys = {(d.item.name, d.quantity) for d in d_items}
    
    for b in billed_items:
        key = (b.inventory_item.name, b.quantity)
        if key not in dispensed_keys:
            dispensed_history.append({
                'item_name': b.inventory_item.name,
                'quantity': b.quantity,
                'at': b.created_at,
                'by': b.invoice.created_by,
                'status': 'Billed/Pending',
                'status_class': 'bg-amber-50 text-amber-700'
            })
            
    # Sort combined history by timestamp
    dispensed_history.sort(key=lambda x: x['at'], reverse=True)
    dispensed_items = dispensed_history[:30] # Limit to 30 items

    # Handle Dispense Medication (Widget)
    from home.forms import DispenseInventoryForm
    
    if request.method == 'POST' and 'dispense_medication' in request.POST:
        dispense_form = PrescriptionItemForm(request.POST)
        if dispense_form.is_valid():
            p_item = dispense_form.save(commit=False)
            
            # 1. Use the latest active visit
            visit = latest_visit
            
            if not visit:
                messages.error(request, "No active visit found for today. Please create a new visit before dispensing medication.")
                return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
                
            # 2. Find or create active prescription for this visit
            prescription = Prescription.objects.filter(
                patient=pregnancy.patient,
                visit=visit,
                status='Active',
                prescribed_by=request.user
            ).last()
            
            if not prescription:
                prescription = Prescription.objects.create(
                    patient=pregnancy.patient,
                    visit=visit,
                    prescribed_by=request.user,
                    status='Active',
                    diagnosis="Maternity Care"
                )
            
            p_item.prescription = prescription
            p_item.save()
            
            messages.success(request, f"Dispensed {p_item.medication.name} successfully.")
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
        else:
            messages.error(request, "Error dispensing medication. Please check the form.")
            # Re-initialize other forms to avoid errors in context
            inventory_form = DispenseInventoryForm()

    # Handle Dispense Inventory (Consumables)
    elif request.method == 'POST' and 'dispense_inventory' in request.POST:
        
        inventory_form = DispenseInventoryForm(request.POST)
        dispense_form = PrescriptionItemForm() # Reset the other form
        
        if inventory_form.is_valid():
            d_item = inventory_form.save(commit=False)
            d_item.patient = pregnancy.patient
            d_item.dispensed_by = request.user
            
            # 1. Use the latest active visit
            visit = latest_visit
            
            if not visit:
                messages.error(request, "No active visit found for today. Please create a new visit before dispensing items.")
                return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
            d_item.visit = visit
            
            # 2. Check Stock
            # Simple stock check for now (Finding any stock record with enough quantity)
            # ideally we should implement FIFO/FEFO but for now let's just find *a* record
            stock_record = StockRecord.objects.filter(
                item=d_item.item,
                quantity__gte=d_item.quantity
            ).order_by('expiry_date').first()
            
            if stock_record:
                # Deduct Stock
                stock_record.quantity -= d_item.quantity
                stock_record.save()
                
                # Create Stock Adjustment
                StockAdjustment.objects.create(
                    item=d_item.item,
                    quantity=-d_item.quantity,
                    adjustment_type='Usage',
                    reason=f"Dispensed to {pregnancy.patient.full_name} (Maternity)",
                    adjusted_by=request.user,
                    adjusted_from=stock_record.current_location
                )
                
                d_item.department = stock_record.current_location
                d_item.save()
                
                # Create DispensedItem for history tracking
                DispensedItem.objects.create(
                    item=d_item.item,
                    patient=pregnancy.patient,
                    visit=visit,
                    quantity=d_item.quantity,
                    dispensed_by=request.user,
                    department=stock_record.current_location
                )
                
                # 3. Billing (Invoice)
                # Get or Create Visit Invoice (Consolidated)
                invoice = get_or_create_invoice(visit=visit, user=request.user)
                
                InvoiceItem.objects.create(
                    invoice=invoice,
                    inventory_item=d_item.item,
                    name=d_item.item.name,
                    unit_price=d_item.item.selling_price,
                    quantity=d_item.quantity
                )
                
                messages.success(request, f"Dispensed {d_item.item.name} successfully.")
                return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
            else:
                messages.error(request, f"Insufficient stock for {d_item.item.name}.")
        else:
            messages.error(request, "Error dispensing item. Please check the form.")

    else:
        dispense_form = PrescriptionItemForm()
        inventory_form = DispenseInventoryForm()

    context = {
        'pregnancy': pregnancy,
        'anc_visits': anc_visits,
        'delivery': delivery,
        'newborns': newborns,
        'mother_pnc': mother_pnc_visits,
        'discharge': discharge,
        'referrals': referrals,
        'available_departments': Departments.objects.all().order_by('name'),
        'dispensing_departments': Departments.objects.all().order_by('name'),
        'maternity_services': maternity_services,
        'dispense_form': dispense_form,
        'inventory_form': inventory_form,
        'medical_tests_data': medical_tests_data,
        'lab_results': lab_results,
        'lab_reports': lab_reports,
        'dispensed_items': dispensed_items,
        'latest_visit': latest_visit,
    }
    
    return render(request, 'maternity/pregnancy_detail.html', context)


@login_required
def update_pregnancy_blood_group(request, pregnancy_id):
    """AJAX view to update pregnancy blood group"""
    if request.method == 'POST':
        pregnancy = get_object_or_404(Pregnancy, id=pregnancy_id)
        blood_group = request.POST.get('blood_group')
        
        if blood_group in dict(Pregnancy.BLOOD_GROUP_CHOICES).keys() or blood_group == '':
            pregnancy.blood_group = blood_group
            pregnancy.save()
            return JsonResponse({'status': 'success', 'blood_group': pregnancy.blood_group})
            
    return JsonResponse({'status': 'error'}, status=400)


@login_required
def record_anc_visit(request, pregnancy_id, visit_id=None):
    """Record ANC visit - handles new visits, queued visits, and updating existing visits"""
    from .forms import AntenatalVisitForm
    
    pregnancy = get_object_or_404(Pregnancy, id=pregnancy_id)
    
    # Identify which visit record to use/edit
    if visit_id:
        # Explicitly updating a specific visit
        visit_instance = get_object_or_404(AntenatalVisit, id=visit_id, pregnancy=pregnancy)
    else:
        # Check if there's a pending visit from the queue (paid but not seen)
        visit_instance = pregnancy.anc_visits.filter(service_received=False).first()
    
    if request.method == 'POST':
        if visit_instance:
            form = AntenatalVisitForm(request.POST, instance=visit_instance)
        else:
            form = AntenatalVisitForm(request.POST)
            
        if form.is_valid():
            anc_visit = form.save(commit=False)
            anc_visit.pregnancy = pregnancy
            anc_visit.recorded_by = request.user
            anc_visit.service_received = True  # Mark as seen by doctor
            
            # Link to active hospital visit if not already set
            if not anc_visit.visit:
                latest_hosp_visit = Visit.objects.filter(patient=pregnancy.patient, is_active=True).last()
                anc_visit.visit = latest_hosp_visit
                
            anc_visit.save()
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    else:
        # For non-POST, prepare the form
        today = timezone.now().date()
        latest_hosp_visit = Visit.objects.filter(patient=pregnancy.patient, is_active=True).last()
        
        # Calculate suggested gestational age based on FIRST visit (Anchor)
        # Fallback to LMP-based if no previous visit exists
        first_visit = pregnancy.anc_visits.filter(service_received=True, gestational_age__isnull=False).order_by('visit_number', 'visit_date').first()
        if first_visit:
            days_passed = (today - first_visit.visit_date).days
            calc_ga = first_visit.gestational_age + (days_passed // 7)
        else:
            calc_ga = pregnancy.gestational_age_weeks

        if visit_instance:
            # Editing existing or queued visit
            form = AntenatalVisitForm(instance=visit_instance)
            # If it's a queued visit (not yet filled), apply some defaults
            if not visit_instance.service_received:
                last_completed = pregnancy.anc_visits.filter(service_received=True).order_by('-visit_number').first()
                next_visit_num = (last_completed.visit_number + 1) if last_completed else 1
                
                form.initial.update({
                    'visit': latest_hosp_visit,
                    'visit_number': next_visit_num,
                    'visit_date': today,
                    'gestational_age': calc_ga
                })
        else:
            # Brand new visit from scratch
            last_completed = pregnancy.anc_visits.filter(service_received=True).order_by('-visit_number').first()
            next_visit_number = (last_completed.visit_number + 1) if last_completed else 1
            
            form = AntenatalVisitForm(initial={
                'visit': latest_hosp_visit,
                'visit_number': next_visit_number,
                'visit_date': today,
                'gestational_age': calc_ga
            })
    
    context = {
        'form': form,
        'pregnancy': pregnancy,
        'is_queued': visit_instance is not None and not visit_instance.service_received,
        'is_edit': visit_id is not None,
    }
    
    return render(request, 'maternity/record_anc_visit.html', context)


@login_required
def record_delivery(request, pregnancy_id):
    """Record labor and delivery"""
    from .forms import LaborDeliveryForm
    
    pregnancy = get_object_or_404(Pregnancy, id=pregnancy_id)
    
    # Check if delivery already exists
    if hasattr(pregnancy, 'delivery'):
        delivery = pregnancy.delivery
        is_new = False
    else:
        delivery = None
        is_new = True
    
    if request.method == 'POST':
        if delivery:
            form = LaborDeliveryForm(request.POST, instance=delivery)
        else:
            form = LaborDeliveryForm(request.POST)
        
        if form.is_valid():
            delivery_record = form.save(commit=False)
            delivery_record.pregnancy = pregnancy
            delivery_record.delivery_by = request.user
            
            # Auto-create Visit and Invoice if this is a new delivery
            if is_new:
                from home.models import Visit
                from accounts.models import Service, InvoiceItem
                from accounts.utils import get_or_create_invoice
                
                visit = Visit.objects.create(
                    patient=pregnancy.patient,
                    visit_type='IN-PATIENT',
                    visit_date=timezone.now()
                )
                delivery_record.visit = visit
            
            delivery_record.save()
            
            if is_new:
                # Bill for Normal Delivery
                invoice = get_or_create_invoice(visit=visit, user=request.user)
                service, _ = Service.objects.get_or_create(
                    name='Normal Delivery',
                    defaults={'price': 10000}
                )
                InvoiceItem.objects.create(
                    invoice=invoice,
                    service=service,
                    name=service.name,
                    unit_price=service.price,
                    quantity=1
                )
            
            # Update pregnancy status
            pregnancy.status = 'Delivered'
            pregnancy.save()
            
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    else:
        # Calculate current gestational age
        current_ga = pregnancy.gestational_age_weeks or 40
        
        if delivery:
            form = LaborDeliveryForm(instance=delivery)
        else:
            form = LaborDeliveryForm(initial={
                'admission_date': timezone.now(),
                'delivery_datetime': timezone.now(),
                'gestational_age_at_delivery': current_ga,
                'mother_condition': 'Stable',
                'placenta_delivery': 'Complete',
            })
    
    context = {
        'form': form,
        'pregnancy': pregnancy,
        'is_new': is_new,
    }
    
    return render(request, 'maternity/record_delivery.html', context)


@login_required
def register_newborn(request, pregnancy_id):
    """Register newborn baby - supports multiple births"""
    from .forms import NewbornForm
    
    pregnancy = get_object_or_404(Pregnancy, id=pregnancy_id)
    
    # Ensure delivery exists
    if not hasattr(pregnancy, 'delivery'):
        return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    
    delivery = pregnancy.delivery
    
    if request.method == 'POST':
        form = NewbornForm(request.POST)
        if form.is_valid():
            newborn = form.save(commit=False)
            newborn.delivery = delivery
            newborn.created_by = request.user
            
            # Link/Create Patient Profile if named
            first_name = form.cleaned_with_defaults.get('first_name')
            last_name = form.cleaned_with_defaults.get('last_name')
            
            if first_name and last_name:
                patient = Patient.objects.create(
                    first_name=first_name,
                    last_name=last_name,
                    date_of_birth=newborn.birth_datetime.date(),
                    gender=newborn.gender,
                    phone=pregnancy.patient.phone,
                    location=pregnancy.patient.location,
                    created_by=request.user
                )
                newborn.patient_profile = patient
            
            newborn.save()
            return redirect(f"{reverse('maternity:pregnancy_detail', args=[pregnancy.id])}#delivery-section")
    else:
        # Auto-populate baby number (count existing + 1)
        existing_babies = delivery.newborns.count()
        next_baby_number = existing_babies + 1
        
        form = NewbornForm(initial={
            'baby_number': next_baby_number,
            'birth_datetime': delivery.delivery_datetime,
            'status': 'Alive',
        })
    
    context = {
        'form': form,
        'pregnancy': pregnancy,
        'delivery': delivery,
    }
    
    return render(request, 'maternity/register_newborn.html', context)


@login_required
def edit_newborn(request, newborn_id):
    """Edit existing newborn record"""
    from .forms import NewbornForm
    
    newborn = get_object_or_404(Newborn, id=newborn_id)
    pregnancy = newborn.delivery.pregnancy
    
    if request.method == 'POST':
        form = NewbornForm(request.POST, instance=newborn)
        if form.is_valid():
            form.save()
            from django.urls import reverse
            return redirect(f"{reverse('maternity:pregnancy_detail', args=[pregnancy.id])}#delivery-section")
    else:
        form = NewbornForm(instance=newborn)
    
    context = {
        'form': form,
        'pregnancy': pregnancy,
        'delivery': newborn.delivery,
        'newborn': newborn,
        'is_edit': True,
    }
    
    return render(request, 'maternity/register_newborn.html', context)


@login_required
def record_mother_pnc_visit(request, pregnancy_id):
    """Record postnatal visit for the mother"""
    from .forms import PostnatalMotherVisitForm
    
    pregnancy = get_object_or_404(Pregnancy, id=pregnancy_id)
    
    # Ensure delivery exists
    if not hasattr(pregnancy, 'delivery'):
        return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    
    delivery = pregnancy.delivery
    
    if request.method == 'POST':
        form = PostnatalMotherVisitForm(request.POST)
        if form.is_valid():
            visit = form.save(commit=False)
            visit.delivery = delivery
            visit.recorded_by = request.user
            
            # Link to active hospital visit if not already set
            if not visit.visit:
                latest_hosp_visit = Visit.objects.filter(patient=pregnancy.patient, is_active=True).last()
                visit.visit = latest_hosp_visit
                
            visit.save()
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    else:
        # Calculate visit day
        delivery_date = delivery.delivery_datetime.date()
        today = timezone.now().date()
        visit_day = (today - delivery_date).days
        latest_hosp_visit = Visit.objects.filter(patient=pregnancy.patient, is_active=True).last()
        
        form = PostnatalMotherVisitForm(initial={
            'visit': latest_hosp_visit,
            'visit_date': today,
            'visit_day': max(0, visit_day),
        })
    
    context = {
        'form': form,
        'pregnancy': pregnancy,
        'delivery': delivery,
    }
    
    return render(request, 'maternity/record_mother_pnc_visit.html', context)


@login_required
def record_baby_pnc_visit(request, newborn_id):
    """Record postnatal visit for a specific baby"""
    from .forms import PostnatalBabyVisitForm
    
    newborn = get_object_or_404(Newborn, id=newborn_id)
    pregnancy = newborn.delivery.pregnancy
    
    if request.method == 'POST':
        form = PostnatalBabyVisitForm(request.POST)
        if form.is_valid():
            visit = form.save(commit=False)
            visit.newborn = newborn
            visit.recorded_by = request.user
            
            # Link to active hospital visit if not already set
            if not visit.visit:
                latest_hosp_visit = Visit.objects.filter(patient=newborn.patient_profile, is_active=True).last()
                visit.visit = latest_hosp_visit
                
            visit.save()
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    else:
        # Calculate visit day
        delivery_date = newborn.birth_datetime.date()
        today = timezone.now().date()
        visit_day = (today - delivery_date).days
        latest_hosp_visit = Visit.objects.filter(patient=newborn.patient_profile, is_active=True).last()
        
        form = PostnatalBabyVisitForm(initial={
            'visit': latest_hosp_visit,
            'visit_date': today,
            'visit_day': max(0, visit_day),
            'weight': newborn.birth_weight,
            'length': newborn.birth_length,
            'head_circumference': newborn.head_circumference,
        })
    
    context = {
        'form': form,
        'newborn': newborn,
        'pregnancy': pregnancy,
        'delivery': newborn.delivery,
    }
    
    return render(request, 'maternity/record_baby_pnc_visit.html', context)

@login_required
def record_maternity_discharge(request, pregnancy_id):
    """Formal clinical closure for mother and baby"""
    from .forms import MaternityDischargeForm
    from django.contrib import messages
    
    pregnancy = get_object_or_404(Pregnancy, id=pregnancy_id)
    
    # Payment Validation: Check for pending delivery invoice
    if hasattr(pregnancy, 'delivery') and pregnancy.delivery.visit:
        if hasattr(pregnancy.delivery.visit, 'invoice'):
            invoice = pregnancy.delivery.visit.invoice
            if invoice.status != 'Paid':
                messages.error(request, f"Cannot discharge patient. There is an unpaid invoice for the delivery visit (Invoice #{invoice.id}). Please clear it first.")
                return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    
    # Check if already discharged
    if hasattr(pregnancy, 'maternity_discharge'):
        discharge = pregnancy.maternity_discharge
    else:
        discharge = None
        
    if request.method == 'POST':
        if discharge:
            form = MaternityDischargeForm(request.POST, instance=discharge)
        else:
            form = MaternityDischargeForm(request.POST)
            
        if form.is_valid():
            discharge_record = form.save(commit=False)
            discharge_record.pregnancy = pregnancy
            discharge_record.discharged_by = request.user
            discharge_record.save()
            
            # Ensure pregnancy status is updated
            if pregnancy.status == 'Active':
                pregnancy.status = 'Delivered'
                pregnancy.save()
                
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    else:
        if discharge:
            form = MaternityDischargeForm(instance=discharge)
        else:
            # Pre-population logic
            mother_cond = 'Stable'
            if hasattr(pregnancy, 'delivery'):
                mother_cond = pregnancy.delivery.mother_condition
                
            baby_cond = "Healthy"
            if hasattr(pregnancy, 'delivery'):
                newborns = pregnancy.delivery.newborns.all()
                if newborns.exists():
                    baby_cond = ", ".join([f"Baby {b.baby_number}: {b.status}" for b in newborns])
            
            form = MaternityDischargeForm(initial={
                'discharge_date': timezone.now(),
                'mother_condition_at_discharge': mother_cond,
                'baby_condition_at_discharge': baby_cond,
            })
            
    context = {
        'form': form,
        'pregnancy': pregnancy,
        'is_edit': discharge is not None,
    }
    return render(request, 'maternity/record_maternity_discharge.html', context)


@login_required
def record_maternity_referral(request, pregnancy_id):
    """Formal referral out for specialized care"""
    from .forms import MaternityReferralForm
    
    pregnancy = get_object_or_404(Pregnancy, id=pregnancy_id)
    
    if request.method == 'POST':
        form = MaternityReferralForm(request.POST)
        if form.is_valid():
            referral = form.save(commit=False)
            referral.pregnancy = pregnancy
            referral.referred_by = request.user
            referral.save()
            
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    else:
        form = MaternityReferralForm(initial={
            'referral_date': timezone.now(),
        })
        
    context = {
        'form': form,
        'pregnancy': pregnancy,
    }
    return render(request, 'maternity/record_maternity_referral.html', context)

@login_required
def record_vaccination(request, newborn_id):
    """Record a vaccination for a newborn"""
    newborn = get_object_or_404(Newborn, id=newborn_id)
    visit_id = request.GET.get('visit_id')
    visit = get_object_or_404(PostnatalBabyVisit, id=visit_id) if visit_id else None
    
    if request.method == 'POST':
        form = ImmunizationRecordForm(request.POST)
        if form.is_valid():
            vaccination = form.save(commit=False)
            vaccination.newborn = newborn
            vaccination.administered_by = request.user
            if visit:
                vaccination.visit = visit
                vaccination.date_administered = visit.visit_date
            
            vaccination.save()
            
            # Update newborn model flags if it's BCG or OPV 0
            if vaccination.vaccine.abbreviation == 'BCG':
                newborn.bcg_given = True
                newborn.save()
            elif vaccination.vaccine.abbreviation == 'OPV' and vaccination.dose_number == 0:
                newborn.opv_0_given = True
                newborn.save()
                
            return redirect('pregnancy_detail', pregnancy_id=newborn.delivery.pregnancy.id)
    else:
        initial = {}
        if visit:
            initial['date_administered'] = visit.visit_date
        form = ImmunizationRecordForm(initial=initial)
        
    return render(request, 'maternity/record_vaccination.html', {
        'form': form,
        'newborn': newborn,
        'visit': visit,
        'pregnancy': newborn.delivery.pregnancy
    })

@login_required
def vaccination_dashboard(request):
    """Dashboard for tracking due/overdue vaccinations"""
    today = timezone.now().date()
    # Simplified logic: show newborns born in the last 15 months
    recent_newborns = Newborn.objects.select_related('delivery__pregnancy__patient').filter(
        birth_datetime__gte=timezone.now() - timedelta(days=450)
    )
    
    # We want to find newborns who are "Due" for something
    # This is a bit complex for a single query, so we'll do some Python-side filtering
    # for a more robust enterprise app, we'd have a 'ScheduledVaccine' model
    
    overdue = []
    due_today = []
    
    for baby in recent_newborns:
        # Birth doses (BCG, OPV 0) - should be given in first week
        if not baby.bcg_given or not baby.opv_0_given:
            age_days = (timezone.now() - baby.birth_datetime).days
            if age_days > 7:
                overdue.append(baby)
            else:
                due_today.append(baby)
        
        # Check next_dose_due in ImmunizationRecord
        pending = baby.vaccinations.filter(next_dose_due__isnull=False).order_by('next_dose_due')
        for record in pending:
            if record.next_dose_due < today:
                if baby not in overdue: overdue.append(baby)
            elif record.next_dose_due == today:
                if baby not in due_today and baby not in overdue: due_today.append(baby)

    # Recent activity
    recent_records = ImmunizationRecord.objects.select_related('newborn__delivery__pregnancy__patient', 'vaccine').order_by('-date_administered')[:10]
    
    # --- CWC Queue Logic ---
    # Get Queued Patients for CWC
    cwc_queue = PatientQue.objects.filter(
        sent_to__name='CWC',
        visit__visit_date__date=today,
        status='PENDING'
    ).select_related('visit__patient').order_by('created_at')

    # Resolve Pregnancy/Newborn context for each queue item
    # This ensures we direct them to the right Pregnancy Detail page
    processed_queue = []
    
    for que in cwc_queue:
        patient = que.visit.patient
        linked_pregnancy = None
        
        # Case 1: Patient is a Baby (linked via Newborn profile)
        # Note: We use hasattr because of OneToOne reverse relation default name or related_name
        if hasattr(patient, 'newborn_clinical_record'):
            linked_pregnancy = patient.newborn_clinical_record.delivery.pregnancy
            
        # Case 2: Patient is the Mother
        else:
            # Try to find a recent pregnancy (Active or Delivered)
            linked_pregnancy = Pregnancy.objects.filter(patient=patient).order_by('-created_at').first()
            
        if linked_pregnancy:
            que.linked_pregnancy = linked_pregnancy
            processed_queue.append(que)
        else:
            # Fallback: Still show them but maybe link to generic profile or show warning?
            # For now, we'll just include them and handle None in template if needed
            processed_queue.append(que)

    context = {
        'overdue': overdue,
        'due_today': due_today,
        'recent_records': recent_records,
        'today': today,
        'cwc_queue': processed_queue,
    }
    return render(request, 'maternity/vaccination_dashboard.html', context)

@login_required
def administer_vaccine(request, que_id):
    """
    Consolidated view for administering vaccines and dispensing consumables.
    This replaces the simple 'record_vaccination' view for queue processing.
    """
    from home.forms import DispenseInventoryForm, PrescriptionItemForm
    from inventory.models import StockRecord, StockAdjustment, DispensedItem
    from home.models import PatientQue
    
    que = get_object_or_404(PatientQue, id=que_id)
    patient = que.visit.patient
    visit = que.visit
    
    # Identify context: Newborn or Just Patient
    newborn = Newborn.objects.filter(patient_profile=patient).first()
    
    if request.method == 'POST':
        if 'administer_vaccine' in request.POST:
            form = ImmunizationRecordForm(request.POST)
            if form.is_valid():
                vaccination = form.save(commit=False)
                
                # Always link to patient
                vaccination.patient = patient
                vaccination.administered_by = request.user
                
                # Link to newborn if available (for detailed tracking)
                if newborn:
                    vaccination.newborn = newborn
                    
                    # Update flags
                    if vaccination.vaccine.abbreviation == 'BCG':
                        newborn.bcg_given = True
                        newborn.save()
                    elif vaccination.vaccine.abbreviation == 'OPV' and vaccination.dose_number == 0:
                        newborn.opv_0_given = True
                        newborn.save()
                
                vaccination.save()
                messages.success(request, f"Administered {vaccination.vaccine.name}")

                return redirect('maternity:administer_vaccine', que_id=que_id)
                
        elif 'dispense_item' in request.POST:
            inventory_form = DispenseInventoryForm(request.POST)
            if inventory_form.is_valid():
                d_item = inventory_form.save(commit=False)
                d_item.patient = patient
                d_item.visit = visit
                d_item.dispensed_by = request.user
                d_item.department = que.sent_to # CWC
                
                # Deduct Stock
                stock_record = StockRecord.objects.filter(
                    item=d_item.item,
                    quantity__gte=d_item.quantity
                ).order_by('expiry_date').first()
                
                if stock_record:
                    stock_record.quantity -= d_item.quantity
                    stock_record.save()
                    
                    # Record Adjustment
                    StockAdjustment.objects.create(
                        item=d_item.item,
                        quantity=-d_item.quantity,
                        adjustment_type='Usage',
                        reason=f"Administered at CWC to {patient.full_name}",
                        adjusted_by=request.user,
                        adjusted_from=stock_record.current_location
                    )
                    
                    d_item.save()
                    
                    # Create Invoice Item (Billable?)
                    # Generally vaccines/syringes might be billable.
                    invoice = get_or_create_invoice(visit=visit, user=request.user)
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        inventory_item=d_item.item,
                        name=d_item.item.name,
                        unit_price=d_item.item.selling_price,
                        quantity=d_item.quantity
                    )
                    
                    messages.success(request, f"Dispensed {d_item.item.name}")
                else:
                    messages.error(request, f"Insufficient stock for {d_item.item.name}")
            return redirect('maternity:administer_vaccine', que_id=que_id)

        elif 'finish_visit' in request.POST:
            que.status = 'COMPLETED'
            que.save()
            messages.success(request, "Visit marked as completed.")
            return redirect('maternity:vaccination_dashboard')

    # GET
    vaccine_form = ImmunizationRecordForm(initial={'date_administered': timezone.now().date()})
    inventory_form = DispenseInventoryForm()
    
    # Calculate Due Vaccines (Simple logic based on age)
    due_vaccines = []
    
    # Fetch history (Newborn OR Patient)
    if newborn:
        history = ImmunizationRecord.objects.filter(
            Q(newborn=newborn) | Q(patient=patient)
        ).distinct().order_by('-date_administered')
        
        # Use newborn birth datetime for precision if available
        birth_date = newborn.birth_datetime.date() if newborn.birth_datetime else patient.date_of_birth
        
        # Check flags first
        bcg_given = newborn.bcg_given
        opv0_given = newborn.opv_0_given
    else:
        history = ImmunizationRecord.objects.filter(patient=patient).order_by('-date_administered')
        birth_date = patient.date_of_birth
        
        # Check history for flags equivalent
        bcg_given = history.filter(vaccine__abbreviation__icontains='BCG').exists()
        opv0_given = history.filter(vaccine__abbreviation__icontains='OPV', dose_number=0).exists()

    if birth_date:
        age_days = (timezone.now().date() - birth_date).days
        age_weeks = age_days // 7
        
        # KEPI Schedule Logic (Simplified)
        if not bcg_given: due_vaccines.append("BCG")
        if not opv0_given: due_vaccines.append("OPV 0")
        
        if age_weeks >= 6:
            # Check 6 week vaccines
            if not history.filter(vaccine__abbreviation__icontains='OPV', dose_number=1).exists(): due_vaccines.append("OPV 1")
            if not history.filter(vaccine__abbreviation__icontains='Penta', dose_number=1).exists(): due_vaccines.append("Penta 1")
            if not history.filter(vaccine__abbreviation__icontains='PCV', dose_number=1).exists(): due_vaccines.append("PCV 1")
            if not history.filter(vaccine__abbreviation__icontains='Rota', dose_number=1).exists(): due_vaccines.append("Rota 1")

        if age_weeks >= 10:
                if not history.filter(vaccine__abbreviation__icontains='OPV', dose_number=2).exists(): due_vaccines.append("OPV 2")
                if not history.filter(vaccine__abbreviation__icontains='Penta', dose_number=2).exists(): due_vaccines.append("Penta 2")
                if not history.filter(vaccine__abbreviation__icontains='PCV', dose_number=2).exists(): due_vaccines.append("PCV 2")
                if not history.filter(vaccine__abbreviation__icontains='Rota', dose_number=2).exists(): due_vaccines.append("Rota 2")
                
        if age_weeks >= 14:
                if not history.filter(vaccine__abbreviation__icontains='OPV', dose_number=3).exists(): due_vaccines.append("OPV 3")
                if not history.filter(vaccine__abbreviation__icontains='Penta', dose_number=3).exists(): due_vaccines.append("Penta 3")
                if not history.filter(vaccine__abbreviation__icontains='PCV', dose_number=3).exists(): due_vaccines.append("PCV 3")
                if not history.filter(vaccine__abbreviation__icontains='IPV').exists(): due_vaccines.append("IPV")

        if age_days >= 270: # 9 months
                if not history.filter(vaccine__abbreviation__icontains='Measles', dose_number=1).exists(): due_vaccines.append("Measles 1")
                if not history.filter(vaccine__abbreviation__icontains='Yellow').exists(): due_vaccines.append("Yellow Fever")
                 
    # Get dispensed items for this visit
    dispensed_items = DispensedItem.objects.filter(visit=visit).select_related('item', 'dispensed_by')

    context = {
        'patient': patient,
        'newborn': newborn,
        'vaccine_form': vaccine_form,
        'inventory_form': inventory_form,
        'due_vaccines': due_vaccines,
        'history': history,
        'dispensed_items': dispensed_items,
        'que': que,
    }
    
    return render(request, 'maternity/administer_vaccine.html', context)



@login_required
def generate_referral_letter(request, referral_id):
    """Generate a printable referral letter"""
    from home.models import TriageEntry
    referral = get_object_or_404(MaternityReferral.objects.select_related('pregnancy__patient', 'referred_by'), id=referral_id)
    latest_triage = TriageEntry.objects.filter(visit__patient=referral.pregnancy.patient).order_by('-entry_date').first()
    
    return render(request, 'maternity/reports/referral_letter.html', {
        'referral': referral,
        'latest_triage': latest_triage,
        'today': timezone.now()
    })

@login_required
def generate_discharge_summary(request, pregnancy_id):
    """Generate a printable discharge summary"""
    pregnancy = get_object_or_404(Pregnancy.objects.select_related('patient', 'maternity_discharge'), id=pregnancy_id)
    discharge = pregnancy.maternity_discharge
    delivery = getattr(pregnancy, 'delivery', None)
    newborns = delivery.newborns.all() if delivery else []
    
    return render(request, 'maternity/reports/discharge_summary.html', {
        'pregnancy': pregnancy,
        'discharge': discharge,
        'delivery': delivery,
        'newborns': newborns,
        'today': timezone.now()
    })
