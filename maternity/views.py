from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages # Added messages
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
from accounts.models import InvoiceItem, Service
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
    
    context = {
        'active_pregnancies': active_pregnancies[:20],
        'total_active': total_active,
        'high_risk_count': high_risk,
        'overdue_count': overdue,
        'due_this_week_count': due_this_week,
        'recent_deliveries': recent_deliveries,
        'deliveries_this_month': deliveries_this_month,
        'current_newborns': current_newborns,
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
        service_received=False,
        visit_date=today
    ).select_related('pregnancy__patient').order_by('created_at')

    # New Arrivals from Triage (using PatientQue)
    # We now filter by explicit 'ANC' department OR fallback to 'Maternity' (legacy) if needed,
    # but primarily 'ANC'.
    new_arrivals_raw = PatientQue.objects.filter(
        Q(sent_to__name='ANC') | Q(sent_to__name='Maternity'), # Keep Maternity for fallback/legacy
        visit__visit_date__date=today
    ).select_related('visit__patient').prefetch_related('visit__invoices__items').order_by('-created_at')

    new_arrivals = []
    # Identify which are ANC based on Department OR Services (Legacy)
    for que in new_arrivals_raw:
        is_anc = False
        
        # 1. Explicit Department Routing (New Way)
        if que.sent_to and que.sent_to.name == 'ANC':
            is_anc = True
            
        # 2. Service-based fallback (Old Way - for legacy 'Maternity' queue items)
        elif que.sent_to and que.sent_to.name == 'Maternity':
            for inv in que.visit.invoices.all():
                for item in inv.items.all():
                    if item.service and "ANC" in item.service.name.upper():
                        is_anc = True
                        break
                if is_anc: break
        
        if is_anc:
            # Check if an AntenatalVisit already exists for this visit - if so, it's already in anc_queue or completed
            if not AntenatalVisit.objects.filter(pregnancy__patient=que.visit.patient, visit_date=today).exists():
                # Check if patient has an active pregnancy
                que.active_pregnancy = Pregnancy.objects.filter(patient=que.visit.patient, status='Active').first()
                new_arrivals.append(que)

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
    ).select_related('visit__patient').prefetch_related('visit__invoices__items').order_by('-created_at')

    new_pnc_arrivals = []
    for que in new_arrivals_raw:
        is_pnc = False
        
        # 1. Explicit Department Routing
        if que.sent_to and que.sent_to.name == 'PNC':
            is_pnc = True
        
        # 2. Service-based fallback (Legacy)
        elif que.sent_to and que.sent_to.name == 'Maternity':
            for inv in que.visit.invoices.all():
                for item in inv.items.all():
                    if item.service and "PNC" in item.service.name.upper():
                        is_pnc = True
                        break
                if is_pnc: break
        
        if is_pnc:
            patient = que.visit.patient
            # Case 1: Mother arrival
            if patient.gender == 'F' and patient.age >= 12:
                has_mother_visit = PostnatalMotherVisit.objects.filter(delivery__pregnancy__patient=patient, visit_date=today).exists()
                if not has_mother_visit:
                    que.active_pregnancy = Pregnancy.objects.filter(patient=patient, status='Delivered').first()
                    que.arrival_type = 'Mother'
                    new_pnc_arrivals.append(que)
            
            # Case 2: Child arrival (specifically registered as patient)
            elif patient.age < 1:
                has_baby_visit = PostnatalBabyVisit.objects.filter(newborn__patient_profile=patient, visit_date=today).exists()
                if not has_baby_visit:
                    que.linked_newborn = Newborn.objects.filter(patient_profile=patient).first()
                    que.arrival_type = 'Child'
                    new_pnc_arrivals.append(que)

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
        # Create a pending ANC visit record
        # visit_number logic
        last_completed = pregnancy.anc_visits.filter(service_received=True).order_by('-visit_number').first()
        next_visit_number = (last_completed.visit_number + 1) if last_completed else 1
        
        AntenatalVisit.objects.get_or_create(
            pregnancy=pregnancy,
            visit_date=timezone.now().date(),
            defaults={
                'visit_number': next_visit_number,
                'gestational_age': pregnancy.gestational_age_weeks,
                'service_received': False,
                'recorded_by': request.user
            }
        )
    
    return redirect('maternity:anc_dashboard')


@login_required
def receive_pnc_arrival(request, que_id):
    """Transition patient from Triage queue to PNC clinical queue"""
    que = get_object_or_404(PatientQue, id=que_id)
    pregnancy = Pregnancy.objects.filter(patient=que.visit.patient, status='Delivered').first()
    
    if pregnancy:
        # Check for matching delivery
        delivery = LaborDelivery.objects.filter(pregnancy=pregnancy).first()
        if delivery:
            # Create a pending PNC visit record
            PostnatalMotherVisit.objects.get_or_create(
                delivery=delivery,
                visit_date=timezone.now().date(),
                defaults={
                    'service_received': False,
                    'recorded_by': request.user
                }
            )
            
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
    from lab.models import LabResult, LabReport
    lab_results = LabResult.objects.filter(patient=pregnancy.patient).select_related('service', 'requested_by').order_by('-requested_at')
    
    # Get lab reports for this patient
    lab_report_ids = lab_results.values_list('id', flat=True)
    lab_reports = LabReport.objects.filter(lab_result_id__in=lab_report_ids).select_related('lab_result', 'created_by').order_by('-created_at')
    
    # Get maternity specific services for quick billing
    maternity_dept = Departments.objects.filter(name='Maternity').first()
    maternity_services = Service.objects.filter(
        department=maternity_dept,
        is_active=True
    ).order_by('name')

    # Handle Dispense Medication (Widget)
    from home.forms import DispenseInventoryForm
    
    if request.method == 'POST' and 'dispense_medication' in request.POST:
        dispense_form = PrescriptionItemForm(request.POST)
        if dispense_form.is_valid():
            p_item = dispense_form.save(commit=False)
            
            # 1. Find or create active visit
            today = timezone.now().date()
            visit = Visit.objects.filter(
                patient=pregnancy.patient,
                visit_date__date=today,
                is_active=True
            ).last()
            
            if not visit:
                visit = Visit.objects.create(
                    patient=pregnancy.patient,
                    visit_type='Maternity',
                    visit_date=timezone.now(),
                    is_active=True,
                    notes="Auto-created for dispensing"
                )
                
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
            
            # 1. Find or create visit
            today = timezone.now().date()
            visit = Visit.objects.filter(
                patient=pregnancy.patient,
                visit_date__date=today,
                is_active=True
            ).last()
            
            if not visit:
                visit = Visit.objects.create(
                    patient=pregnancy.patient,
                    visit_type='Maternity',
                    visit_date=timezone.now(),
                    is_active=True,
                    notes="Auto-created for dispensing consumables"
                )
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
                
                # 3. Billing (Invoice)
                # Check for pending invoice for this visit or create new
                invoice = Invoice.objects.filter(visit=visit, status='Pending').last()
                if not invoice:
                    invoice = Invoice.objects.create(
                        patient=pregnancy.patient,
                        visit=visit,
                        status='Pending',
                        created_by=request.user,
                        notes="Maternity Consumables"
                    )
                
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
        'maternity_services': maternity_services,
        'dispense_form': dispense_form,
        'inventory_form': inventory_form,
        'medical_tests_data': medical_tests_data,
        'lab_results': lab_results,
        'lab_reports': lab_reports,
    }
    
    return render(request, 'maternity/pregnancy_detail.html', context)


@login_required
def record_anc_visit(request, pregnancy_id):
    """Record ANC visit - handles both new visits and finishing queued/paid visits"""
    from .forms import AntenatalVisitForm
    
    pregnancy = get_object_or_404(Pregnancy, id=pregnancy_id)
    
    # Check if there's a pending visit from the queue (paid but not seen)
    pending_visit = pregnancy.anc_visits.filter(service_received=False).first()
    
    if request.method == 'POST':
        if pending_visit:
            form = AntenatalVisitForm(request.POST, instance=pending_visit)
        else:
            form = AntenatalVisitForm(request.POST)
            
        if form.is_valid():
            anc_visit = form.save(commit=False)
            anc_visit.pregnancy = pregnancy
            anc_visit.recorded_by = request.user
            anc_visit.service_received = True  # Mark as seen by doctor
            anc_visit.save()
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    else:
        # Auto-calculate visit number
        last_completed = pregnancy.anc_visits.filter(service_received=True).order_by('-visit_number').first()
        next_visit_number = (last_completed.visit_number + 1) if last_completed else 1
        
        if pending_visit:
            form = AntenatalVisitForm(instance=pending_visit, initial={
                'visit_number': next_visit_number,
                'visit_date': timezone.now().date(),
                'gestational_age': pregnancy.gestational_age_weeks
            })
        else:
            form = AntenatalVisitForm(initial={
                'visit_number': next_visit_number,
                'visit_date': timezone.now().date(),
                'gestational_age': pregnancy.gestational_age_weeks
            })
    
    context = {
        'form': form,
        'pregnancy': pregnancy,
        'is_queued': pending_visit is not None,
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
            delivery_record.save()
            
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
            newborn.save()
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
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
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
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
            visit.save()
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    else:
        # Calculate visit day
        delivery_date = delivery.delivery_datetime.date()
        today = timezone.now().date()
        visit_day = (today - delivery_date).days
        
        form = PostnatalMotherVisitForm(initial={
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
            visit.save()
            return redirect('maternity:pregnancy_detail', pregnancy_id=pregnancy.id)
    else:
        # Calculate visit day
        delivery_date = newborn.delivery.delivery_datetime.date()
        today = timezone.now().date()
        visit_day = (today - delivery_date).days
        
        form = PostnatalBabyVisitForm(initial={
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
    
    pregnancy = get_object_or_404(Pregnancy, id=pregnancy_id)
    
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
    
    context = {
        'overdue': overdue,
        'due_today': due_today,
        'recent_records': recent_records,
        'today': today,
    }
    return render(request, 'maternity/vaccination_dashboard.html', context)

@login_required
def generate_birth_notification(request, newborn_id):
    """Generate a printable birth notification for a newborn"""
    newborn = get_object_or_404(Newborn.objects.select_related('delivery__pregnancy__patient'), id=newborn_id)
    return render(request, 'maternity/reports/birth_notification.html', {
        'newborn': newborn,
        'today': timezone.now()
    })

@login_required
def generate_referral_letter(request, referral_id):
    """Generate a printable referral letter"""
    referral = get_object_or_404(MaternityReferral.objects.select_related('pregnancy__patient', 'referred_by'), id=referral_id)
    return render(request, 'maternity/reports/referral_letter.html', {
        'referral': referral,
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
