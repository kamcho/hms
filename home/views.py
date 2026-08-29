from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy, reverse
from django.db import transaction
from django.db.models import Q, Count, Sum, Avg, Prefetch, F
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
import json
from datetime import timedelta, datetime, time, date
from decimal import Decimal
from .models import Patient, Visit, TriageEntry, EmergencyContact, Consultation, PatientQue, ConsultationNotes, Departments, Prescription, PrescriptionItem, Referral, Appointments, Symptoms, Impression, Diagnosis, ProcedureCompletion, Problem, ProblemHistory
from accounts.models import Invoice, InvoiceItem, Service, Payment
from accounts.utils import get_or_create_invoice
from lab.models import LabResult
from lab.forms import AmbulanceRouteForm
from inpatient.models import Admission
from morgue.models import MorgueAdmission
from .forms import EmergencyContactForm, PatientForm, ReferralForm, AppointmentForm
from django.db.models import Q
from inventory.models import DispensedItem, InventoryRequest


def can_use_sha_coverage_check(user):
    """SHA Coverage Check on patient add — superuser or Insurance Manager (SHA Manager)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return getattr(user, 'role', None) == 'SHA Manager'


def _parse_dob(value):
    """Parse common SHA date formats into a date, or None."""
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    # ISO date / datetime
    m = text[:10]
    try:
        return datetime.strptime(m, '%Y-%m-%d').date()
    except ValueError:
        pass
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _map_gender(value):
    from .knhts_demographics import map_gender_to_knhts
    return map_gender_to_knhts(value)


def _upsert_patient_from_sha_profile(profile, *, created_by, default_location=''):
    """
    Create or update a Patient from a normalized SHA/CR profile.
    Match priority: cr_id → id_number → create new.
    """
    from .knhts_demographics import map_sha_identification_type

    if not isinstance(profile, dict):
        raise ValueError('Invalid patient profile.')

    cr_id = (profile.get('cr_id') or '').strip() or None
    id_number = (profile.get('id_number') or '').strip() or None
    id_type = map_sha_identification_type(profile.get('identification_type'))

    first_name = (profile.get('first_name') or '').strip()
    last_name = (profile.get('last_name') or '').strip()
    if (not first_name or not last_name) and profile.get('full_name'):
        parts = str(profile['full_name']).strip().split()
        first_name = first_name or (parts[0] if parts else '')
        last_name = last_name or (' '.join(parts[1:]) if len(parts) > 1 else first_name or 'Unknown')
    first_name = first_name or 'Unknown'
    last_name = last_name or first_name

    dob = _parse_dob(profile.get('date_of_birth'))
    gender = _map_gender(profile.get('gender') or profile.get('sex'))
    phone = (profile.get('phone') or '').strip() or None
    email = (profile.get('email') or '').strip() or None
    county = (profile.get('county') or '').strip()
    sub_county = (profile.get('sub_county') or '').strip()
    location = (
        ', '.join(x for x in [sub_county, county] if x)
        or default_location
        or 'Not specified'
    )

    patient = None
    created = False
    if cr_id:
        patient = Patient.objects.filter(cr_id=cr_id).first()
    if patient is None and id_number:
        patient = Patient.objects.filter(id_number=id_number).first()

    def _apply_id_docs(p):
        if not id_number:
            return
        if id_type == 'NATIONAL_ID' and not p.national_id:
            p.national_id = id_number
        elif id_type == 'PASSPORT' and not p.passport_number:
            p.passport_number = id_number
        elif id_type == 'BIRTH_CERTIFICATE' and not p.birth_certificate_number:
            p.birth_certificate_number = id_number

    if patient is None:
        if not dob:
            # Dependents sometimes omit DOB — use a safe placeholder adults reception can edit
            dob = date(2000, 1, 1)
        patient = Patient(
            first_name=first_name,
            last_name=last_name,
            id_type=id_type,
            id_number=id_number,
            cr_id=cr_id,
            date_of_birth=dob,
            phone=phone,
            email=email,
            location=location,
            county=county,
            sub_county=sub_county,
            country='Kenya',
            gender=gender,
            created_by=created_by,
        )
        _apply_id_docs(patient)
        patient.save()
        created = True
    else:
        changed = False
        if cr_id and patient.cr_id != cr_id:
            patient.cr_id = cr_id
            changed = True
        if id_number and not patient.id_number:
            patient.id_number = id_number
            patient.id_type = id_type
            changed = True
        if id_type and patient.id_type != id_type and id_number:
            patient.id_type = id_type
            changed = True
        if first_name and patient.first_name != first_name:
            patient.first_name = first_name
            changed = True
        if last_name and patient.last_name != last_name:
            patient.last_name = last_name
            changed = True
        if phone and not patient.phone:
            patient.phone = phone
            changed = True
        if email and not patient.email:
            patient.email = email
            changed = True
        if dob and patient.date_of_birth != dob:
            patient.date_of_birth = dob
            changed = True
        if county and not patient.county:
            patient.county = county
            changed = True
        if sub_county and not patient.sub_county:
            patient.sub_county = sub_county
            changed = True
        if location and (not patient.location or patient.location == 'Not specified'):
            patient.location = location
            changed = True
        if gender and gender != 'unknown' and patient.gender in ('unknown', '', None):
            patient.gender = gender
            changed = True
        before_docs = (patient.national_id, patient.passport_number, patient.birth_certificate_number)
        _apply_id_docs(patient)
        if (patient.national_id, patient.passport_number, patient.birth_certificate_number) != before_docs:
            changed = True
        if changed:
            patient.save()

    return patient, created


@login_required
@require_http_methods(['POST'])
def create_sha_household_patients(request):
    """
    Create/update Patient records for a SHA principal + selected dependents.

    POST JSON:
      {
        "principal": {...normalized profile...},
        "dependents": [{...}, ...],   # only selected visitors that are dependents
        "include_principal": true,    # whether principal is also visiting / should be created
        "selected_keys": ["principal", "0", "1"]  # optional audit
      }
    Always creates/updates the principal (account holder) plus selected dependents.
    """
    if not can_use_sha_coverage_check(request.user):
        return JsonResponse({
            'success': False,
            'error': 'Only Insurance Manager or superuser can create patients from SHA check.',
        }, status=403)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON body.'}, status=400)

    principal = payload.get('principal') or {}
    dependents = payload.get('dependents') or []
    include_principal = payload.get('include_principal', True)
    if not isinstance(dependents, list):
        return JsonResponse({'success': False, 'error': 'dependents must be a list.'}, status=400)
    if not isinstance(principal, dict) or not (
        principal.get('cr_id') or principal.get('id_number') or principal.get('full_name')
        or principal.get('first_name')
    ):
        return JsonResponse({'success': False, 'error': 'principal profile is required.'}, status=400)

    created_patients = []
    existing_patients = []

    with transaction.atomic():
        # Always ensure principal account exists when dependents visit under their cover.
        principal_patient, was_created = _upsert_patient_from_sha_profile(
            principal,
            created_by=request.user,
        )
        row = {
            'id': principal_patient.pk,
            'full_name': principal_patient.full_name,
            'cr_id': principal_patient.cr_id,
            'id_number': principal_patient.id_number,
            'role': 'principal',
            'created': was_created,
            'visiting': bool(include_principal),
        }
        (created_patients if was_created else existing_patients).append(row)

        for dep in dependents:
            if not isinstance(dep, dict):
                continue
            patient, was_created = _upsert_patient_from_sha_profile(
                dep,
                created_by=request.user,
                default_location=principal_patient.location,
            )
            row = {
                'id': patient.pk,
                'full_name': patient.full_name,
                'cr_id': patient.cr_id,
                'id_number': patient.id_number,
                'role': 'dependent',
                'relationship': dep.get('relationship'),
                'created': was_created,
                'visiting': True,
            }
            (created_patients if was_created else existing_patients).append(row)

    all_rows = created_patients + existing_patients
    visiting = [r for r in all_rows if r.get('visiting') or r.get('role') == 'dependent']
    # Prefer a visiting dependent as the active form patient; else principal
    focus = next((r for r in all_rows if r.get('role') == 'dependent'), None)
    if include_principal and not focus:
        focus = next((r for r in all_rows if r.get('role') == 'principal'), None)
    elif include_principal:
        # Multiple visitors — keep principal in list; form will show first selected dependent then user can switch
        pass
    if focus is None and all_rows:
        focus = all_rows[0]

    return JsonResponse({
        'success': True,
        'created_count': len(created_patients),
        'existing_count': len(existing_patients),
        'patients': all_rows,
        'focus_patient_id': focus['id'] if focus else None,
        'message': (
            f"Registered {len(created_patients)} new patient(s)"
            + (f", linked {len(existing_patients)} existing" if existing_patients else "")
            + "."
        ),
    })


def _is_nurse_user(user):
    return user.is_authenticated and getattr(user, 'role', None) == 'Nurse'


def _nurse_visit_q(user, prefix=''):
    """When viewer is Nurse, restrict to visits with by_nurse=True."""
    if _is_nurse_user(user):
        key = f'{prefix}by_nurse' if prefix else 'by_nurse'
        return Q(**{key: True})
    return Q()


def _visit_ok_for_user(visit, user):
    if not visit:
        return False
    if _is_nurse_user(user):
        return visit.by_nurse
    return True


def _can_edit_pharmacy_consumable(user):
    return user.is_superuser or getattr(user, 'role', None) in ('Pharmacist', 'Admin')


def _can_edit_visit_consumable(user):
    """Doctors/nurses may edit pending consumables on a visit; pharmacists/admins too."""
    return user.is_superuser or getattr(user, 'role', None) in (
        'Pharmacist', 'Admin', 'Doctor', 'Nurse',
    )


def _get_editable_visit_consumables(visit):
    """Split visit invoice consumable lines into pending vs already dispensed."""
    from accounts.models import InvoiceItem

    if not visit:
        return [], []

    pending = []
    dispensed = []
    invoice_items = InvoiceItem.objects.filter(
        invoice__visit=visit,
        inventory_item__isnull=False,
    ).select_related('inventory_item', 'invoice').order_by('-created_at')

    for item in invoice_items:
        if not _invoice_item_is_consumable_line(item):
            continue
        qty_dispensed = _consumable_dispensed_qty(visit, item.inventory_item_id)
        row = {
            'id': item.id,
            'name': item.name or item.inventory_item.name,
            'quantity': item.quantity,
            'inventory_item_id': item.inventory_item_id,
        }
        if qty_dispensed > 0 or item.is_dispensed:
            row['dispensed_qty'] = qty_dispensed or item.quantity
            dispensed.append(row)
        else:
            pending.append(row)
    return pending, dispensed


def _consumable_dispensed_qty(visit, inventory_item_id):
    if not visit or not inventory_item_id:
        return 0
    return (
        DispensedItem.objects.filter(visit=visit, item_id=inventory_item_id)
        .aggregate(t=Sum('quantity'))['t']
        or 0
    )


def _invoice_item_is_consumable_line(invoice_item):
    """True when this invoice line is a consumable, not a pending prescription medication."""
    visit = invoice_item.invoice.visit if invoice_item.invoice_id else None
    if not visit or not invoice_item.inventory_item_id:
        return False
    for pi in PrescriptionItem.objects.filter(
        prescription__visit=visit,
        medication_id=invoice_item.inventory_item_id,
        dispensed=False,
    ):
        if pi.quantity == invoice_item.quantity:
            return False
    return True


class PatientListView(LoginRequiredMixin, ListView):
    model = Patient
    template_name = 'home/patient_list.html'
    context_object_name = 'patients'
    
    def get_queryset(self):
        queryset = Patient.objects.all().order_by('-created_at')
        search_query = self.request.GET.get('search')
        if search_query:
            # Split search query into individual terms
            search_terms = search_query.strip().split()
            
            # Start with base queryset
            base_queryset = Patient.objects.all()
            
            # Build Q objects for each search term
            term_q_objects = []
            for term in search_terms:
                if term.strip():
                    term_q = Q() | Q(id_number__icontains=term) | Q(first_name__icontains=term) | Q(last_name__icontains=term) | Q(phone__icontains=term)
                    
                    # Check if term is a number for ID lookup
                    if term.isdigit():
                        term_q = term_q | Q(pk=int(term))
                    
                    term_q_objects.append(term_q)
            
            # Combine all term queries with AND (all terms must match somewhere)
            combined_q = Q()
            for term_q in term_q_objects:
                combined_q = combined_q & term_q
            
            queryset = base_queryset.filter(combined_q)
            
            # Rank results by relevance
            # Higher priority for exact matches in first_name or last_name
            # Then partial matches, then other fields
            ranked_patients = []
            for patient in queryset:
                relevance_score = 0
                
                for term in search_terms:
                    term_lower = term.lower()
                    
                    # Exact match in first_name or last_name gets highest score
                    if patient.first_name.lower() == term_lower or patient.last_name.lower() == term_lower:
                        relevance_score += 100
                    # Starts with gets high score
                    elif patient.first_name.lower().startswith(term_lower) or patient.last_name.lower().startswith(term_lower):
                        relevance_score += 50
                    # Contains gets medium score
                    elif term_lower in patient.first_name.lower() or term_lower in patient.last_name.lower():
                        relevance_score += 25
                    # ID or phone match gets lower score
                    elif term_lower in str(patient.id_number).lower() or term_lower in str(patient.phone).lower():
                        relevance_score += 10
                    # PK match gets highest score
                    elif term.isdigit() and patient.pk == int(term):
                        relevance_score += 200
                
                ranked_patients.append((relevance_score, patient))
            
            # Sort by relevance score (descending) then by creation date
            ranked_patients.sort(key=lambda x: (-x[0], x[1].created_at))
            
            # Extract just the patient objects
            queryset = [patient for score, patient in ranked_patients]
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add statistics
        today = timezone.localdate()
        all_patients = Patient.objects.all()
        from datetime import datetime, time
        start_of_day = timezone.make_aware(datetime.combine(today, time.min))
        end_of_day = timezone.make_aware(datetime.combine(today, time.max))
        
        context['stats'] = {
            'total': all_patients.count(),
            'new_today': all_patients.filter(created_at__range=(start_of_day, end_of_day)).count(),
            'male': all_patients.filter(gender='male').count(),
            'female': all_patients.filter(gender='female').count(),
        }
        
        # Add last visit information for each patient
        patients_with_last_visit = []
        for patient in context['patients']:
            last_visit = Visit.objects.filter(patient=patient).order_by('-visit_date').first()
            patients_with_last_visit.append({
                'patient': patient,
                'last_visit': last_visit
            })
        
        context['patients_with_last_visit'] = patients_with_last_visit

        # Add services for the quick action modals (Consultation and Quick Invoice)
        context['services'] = Service.objects.filter(is_active=True).select_related('department').order_by('department__name', 'name')
        context['user_role'] = self.request.user.role
        
        return context

class PatientCreateView(LoginRequiredMixin, CreateView):
    model = Patient
    form_class = PatientForm
    template_name = 'home/patient_form.html'
    success_url = reverse_lazy('home:patient_list')

    def get_initial(self):
        initial = super().get_initial()
        id_number = (self.request.GET.get('id_number') or '').strip()
        if id_number:
            initial['id_number'] = id_number
            initial['national_id'] = id_number
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['show_sha_coverage_check'] = can_use_sha_coverage_check(self.request.user)
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        
        # First save the patient to get the instance and set self.object
        self.object = form.save()
        
        # Handle integrated billing
        selected_service = form.cleaned_data.get('consultation_type')
        payment_method = form.cleaned_data.get('payment_method')
        
        # Define which services create a Visit + Queue
        VISIT_SERVICES = {'OPD Consultation', 'ANC', 'PNC Visit (Mother)', 'PNC Visit (Baby)', 'CWC', 'MCH'}
        creates_visit = selected_service and selected_service.name in VISIT_SERVICES
        
        if creates_visit:
            # Create a visit for the new patient
            visit = Visit.objects.create(
                patient=self.object,
                visit_type='OUT-PATIENT',
                visit_mode='Walk In',
                payment_method='SHA' if payment_method == 'Insurance' else 'CASH',
                by_nurse=_is_nurse_user(self.request.user),
            )
            
            if selected_service and payment_method:
                # Get or Create Visit Invoice
                invoice = get_or_create_invoice(visit=visit, user=self.request.user)
                
                if selected_service.name == 'OPD Consultation' and payment_method != 'Free Visit':
                    # Custom logic for OPD Consultation selection
                    bill_book = form.cleaned_data.get('bill_opd_book')
                    bill_consult = form.cleaned_data.get('bill_opd_consultation')
                    
                    # Process OPD Book
                    if bill_book:
                        opd_book_service = Service.objects.filter(name__icontains='OPD Book', is_active=True).first()
                        if opd_book_service:
                            InvoiceItem.objects.create(
                                invoice=invoice,
                                service=opd_book_service,
                                name=opd_book_service.name,
                                unit_price=opd_book_service.price,
                                quantity=1
                            )
                    
                    # Process OPD Consultation
                        if payment_method == 'Insurance':
                            price = 300  # Fixed at 300 for SHA/Insurance portion
                        else:
                            price = 100  # Default 100 for non-insurance consultation
                        
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            service=selected_service,
                            name=selected_service.name,
                            unit_price=price,
                            quantity=1
                        )
                        
                        if payment_method == 'Insurance':
                            # Automatically record the 300 Ksh Insurance portion
                            # Automated Insurance portion (300)
                            Payment.objects.create(
                                invoice=invoice,
                                amount=300,
                                payment_method='Insurance',
                                notes='Automated insurance portion (SHA)',
                                created_by=self.request.user
                            )
                            
                    # Record the patient's portion (any remaining balance like the 50 book fee)
                            patient_method = form.cleaned_data.get('patient_payment_method')
                            remaining_to_pay = invoice.total_amount - 300
                            if remaining_to_pay > 0 and patient_method:
                                Payment.objects.create(
                                    invoice=invoice,
                                    amount=remaining_to_pay,
                                    payment_method=patient_method,
                                    notes='Patient portion (Book fee)',
                                    created_by=self.request.user
                                )
                else:
                    # Standard logic for other services or Free Visit
                    # Handle Free Visit logic
                    unit_price = selected_service.price
                    if payment_method == 'Free Visit':
                        unit_price = 0
                    elif "Consultation" in selected_service.name:
                        unit_price = 100 # Default for non-insurance if not caught by OPD specific logic

                    # Create InvoiceItem
                    item = InvoiceItem.objects.create(
                        invoice=invoice,
                        service=selected_service,
                        name=selected_service.name,
                        unit_price=unit_price,
                        quantity=1
                    )
                
                # Update invoice totals before recording payment
                invoice.update_totals()

                # Record Payment (unless it's a Free Visit or already handled for Insurance)
                if payment_method != 'Free Visit' and payment_method != 'Insurance' and invoice.total_amount > 0:
                    Payment.objects.create(
                        invoice=invoice,
                        amount=invoice.total_amount,
                        payment_method=payment_method,
                        created_by=self.request.user
                    )
                
                if payment_method == 'Free Visit':
                    messages.success(self.request, f"Patient registered with a Free Visit for {selected_service.name}.")
                else:
                    messages.success(self.request, f"Patient registered and billing processed via {payment_method}.")

            
            # --- Smart Routing ---
            reception_dept, _ = Departments.objects.get_or_create(
                name='Reception', defaults={'abbreviation': 'REC'}
            )
            
            service_name_upper = selected_service.name.upper() if selected_service else ''
            
            if 'ANC' in service_name_upper:
                dest_dept, _ = Departments.objects.get_or_create(name='ANC', defaults={'abbreviation': 'ANC'})
            elif 'PNC' in service_name_upper:
                dest_dept, _ = Departments.objects.get_or_create(name='PNC', defaults={'abbreviation': 'PNC'})
            elif 'CWC' in service_name_upper:
                dest_dept, _ = Departments.objects.get_or_create(name='CWC', defaults={'abbreviation': 'CWC'})
            elif 'MCH' in service_name_upper:
                dest_dept, _ = Departments.objects.get_or_create(name='MCH', defaults={'abbreviation': 'MCH'})
            else:
                # OPD Consultation → Triage
                dest_dept, _ = Departments.objects.get_or_create(name='Triage', defaults={'abbreviation': 'TRI'})
            
            PatientQue.objects.create(
                visit=visit,
                qued_from=reception_dept,
                sent_to=dest_dept,
                created_by=self.request.user,
                status='PENDING',
                queue_type='INITIAL'
            )
        
        else:
            # Non-visit service: create Invoice directly without a Visit
            if selected_service and payment_method:
                invoice = Invoice.objects.create(
                    patient=self.object,
                    status='Pending',
                    created_by=self.request.user
                )
                # Handle Free Visit logic
                unit_price = selected_service.price
                if payment_method == 'Free Visit':
                    unit_price = 0

                item = InvoiceItem.objects.create(
                    invoice=invoice,
                    service=selected_service,
                    name=selected_service.name,
                    unit_price=unit_price,
                    quantity=1
                )
                
                if payment_method != 'Free Visit':
                    Payment.objects.create(
                        invoice=invoice,
                        amount=item.amount,
                        payment_method=payment_method,
                        created_by=self.request.user
                    )
                
                if payment_method == 'Free Visit':
                    messages.success(self.request, f"Patient registered with a Free Visit for {selected_service.name}.")
                else:
                    messages.success(self.request, f"Patient registered and {selected_service.name} billed via {payment_method}.")
            else:
                messages.success(self.request, "Patient registered successfully.")
        
        # Now redirect to success URL
        return redirect(self.get_success_url())

class PatientUpdateView(LoginRequiredMixin, UpdateView):
    model = Patient
    form_class = PatientForm
    template_name = 'home/patient_form.html'
    success_url = reverse_lazy('home:patient_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['show_sha_coverage_check'] = False
        return context

class PatientDeleteView(LoginRequiredMixin, DeleteView):
    model = Patient
    template_name = 'home/patient_confirm_delete.html'
    success_url = reverse_lazy('home:patient_list')

class PatientDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = Patient
    template_name = 'home/patient_detail.html'
    context_object_name = 'patient'
    
    def test_func(self):
        return self.request.user.role in ['Admin', 'Doctor', 'Nurse']
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = self.get_object()
        from inpatient.models import Admission

        # Get all visits for the filter dropdown
        all_visits = Visit.objects.filter(patient=patient).order_by('-visit_date').prefetch_related(
            'prescriptions',
            'tb_screening',
        )
        latest_visit = all_visits.first()

        # Get visit filter from GET parameters
        visit_id = self.request.GET.get('visit_id', None)
        selected_visit = None
        
        if visit_id == 'all':
            selected_visit = None
        elif visit_id:
            try:
                selected_visit = Visit.objects.get(id=visit_id, patient=patient)
            except Visit.DoesNotExist:
                selected_visit = latest_visit
        else:
            # Default to latest visit if no parameter passed
            selected_visit = latest_visit

        
        context['visits'] = all_visits
        context['selected_visit'] = selected_visit
        context['latest_visit'] = latest_visit
        context['visit_id_param'] = visit_id  # useful for template logic
        
        # Filter data based on selected visit
        if selected_visit:
            triage_filter = {'visit': selected_visit}
            consultation_filter = {'visit': selected_visit}
            notes_filter = {'consultation__visit': selected_visit}
            queue_filter = {'visit': selected_visit}
            lab_filter = {'invoice__visit': selected_visit}
            prescription_filter = {'visit': selected_visit}
        else:
            # Show all data
            triage_filter = {'visit__patient': patient}
            consultation_filter = {'visit__patient': patient}
            notes_filter = {'consultation__visit__patient': patient}
            queue_filter = {'visit__patient': patient}
            lab_filter = {'patient': patient}
            prescription_filter = {'patient': patient}
        
        active_adm = Admission.objects.filter(patient=patient, status='Admitted').first()
        context['active_admission'] = active_adm
        
        # TB Screening context
        from .forms import TBScreeningForm
        from .models import TBScreening
        from .clinical_gates import tb_screening_required_for_patient_view
        if latest_visit:
            context['current_tb_screening'] = TBScreening.objects.filter(visit=latest_visit).first()
        context['tb_screening_form'] = TBScreeningForm(
            instance=context.get('current_tb_screening'),
            show_failure_to_thrive=patient.age is not None and patient.age < 15,
        )
        context['tb_screening_required'] = tb_screening_required_for_patient_view(
            self.request.user, latest_visit, selected_visit,
        )
        context['tb_screening_visit_id'] = (
            latest_visit.pk if context['tb_screening_required'] and latest_visit else None
        )
        context['tb_screening_map'] = {
            str(v.pk): {
                'has_cough': v.tb_screening.has_cough,
                'has_chest_pain': v.tb_screening.has_chest_pain,
                'has_night_sweats': v.tb_screening.has_night_sweats,
                'has_unexplained_fever': v.tb_screening.has_unexplained_fever,
                'has_weight_loss': v.tb_screening.has_weight_loss,
                'failure_to_thrive': v.tb_screening.failure_to_thrive,
            }
            for v in all_visits
            if getattr(v, 'tb_screening', None)
        }
        
        if active_adm:
            context['active_medications'] = active_adm.medications.all().order_by('-prescribed_at')
            context['active_services'] = active_adm.services.all().order_by('-date_provided')
            from inpatient.forms import MedicationChartForm, ServiceAdmissionLinkForm
            context['medication_form'] = MedicationChartForm()
            context['service_form'] = ServiceAdmissionLinkForm()
            
        from .models import Symptoms, Impression, Diagnosis
        
        # Filter new clinical data
        if selected_visit:
            symptoms = Symptoms.objects.filter(visit=selected_visit).order_by('-created_at')
            impressions = Impression.objects.filter(visit=selected_visit).order_by('-created_at')
            diagnoses = Diagnosis.objects.filter(visit=selected_visit).order_by('-created_at')
        else:
            symptoms = Symptoms.objects.filter(visit__patient=patient).order_by('-created_at')
            impressions = Impression.objects.filter(visit__patient=patient).order_by('-created_at')
            diagnoses = Diagnosis.objects.filter(visit__patient=patient).order_by('-created_at')
            
        context['symptoms'] = symptoms
        context['impressions'] = impressions
        context['diagnoses'] = diagnoses
        
        # Get latest diagnosis for pre-filling admission
        latest_diag_obj = diagnoses.first()
        context['latest_diagnosis'] = latest_diag_obj.data if latest_diag_obj else ""
            
        context['triage_entries'] = TriageEntry.objects.filter(**triage_filter).order_by('-entry_date')
        context['consultations'] = Consultation.objects.filter(**consultation_filter).order_by('-checkin_date')
        context['consultation_notes'] = ConsultationNotes.objects.filter(**notes_filter).order_by('-created_at')
        context['queue_entries'] = PatientQue.objects.filter(**queue_filter).order_by('-created_at')
        context['emergency_contacts'] = EmergencyContact.objects.filter(patient=patient).order_by('-is_primary', 'name')

        from .knhts_conditions import ACTIVE_CLINICAL_STATUSES
        all_problems = Problem.objects.filter(patient=patient).exclude(
            verification_status='entered-in-error',
        ).select_related('icd11_entry', 'recorded_by').prefetch_related('history')
        context['active_problems'] = [
            p for p in all_problems if p.clinical_status in ACTIVE_CLINICAL_STATUSES
        ]
        context['resolved_problems'] = [
            p for p in all_problems if p.clinical_status not in ACTIVE_CLINICAL_STATUSES
        ]
        context['problem_history_entries'] = ProblemHistory.objects.filter(
            problem__patient=patient,
        ).select_related('problem', 'changed_by').order_by('-changed_at')[:40]
        from .forms import ProblemForm, DiagnosisForm, PatientMedicationForm, PatientAllergyForm, FamilyHistoryForm
        context['problem_form'] = ProblemForm()
        context['diagnosis_form'] = DiagnosisForm()
        context['medication_list_form'] = PatientMedicationForm()
        context['allergy_form'] = PatientAllergyForm()
        context['family_history_form'] = FamilyHistoryForm()

        from .models import PatientMedication, PatientAllergy, PatientMedicationHistory, PatientAllergyHistory
        all_meds = PatientMedication.objects.filter(patient=patient).exclude(
            status='entered-in-error',
        ).select_related('recorded_by')
        context['active_patient_medications'] = [m for m in all_meds if m.status == 'active']
        context['historical_patient_medications'] = [m for m in all_meds if m.status != 'active'][:20]
        context['medication_history_entries'] = PatientMedicationHistory.objects.filter(
            medication__patient=patient,
        ).select_related('medication', 'changed_by').order_by('-changed_at')[:40]

        all_allergies = PatientAllergy.objects.filter(patient=patient).exclude(
            clinical_status='entered-in-error',
        ).select_related('recorded_by')
        context['active_patient_allergies'] = [a for a in all_allergies if a.clinical_status == 'active']
        context['historical_patient_allergies'] = [a for a in all_allergies if a.clinical_status != 'active'][:20]
        context['allergy_history_entries'] = PatientAllergyHistory.objects.filter(
            allergy__patient=patient,
        ).select_related('allergy', 'changed_by').order_by('-changed_at')[:40]

        from .models import FamilyHistory
        context['family_history'] = list(
            FamilyHistory.objects.filter(patient=patient, status='active')
        )

        # BMI / growth chart series (triage + CWC)
        from .bmi_growth import build_growth_series, calc_bmi, bmi_category
        growth_records = []
        try:
            from maternity.models import CwcGrowthRecord
            growth_records.extend(
                CwcGrowthRecord.objects.filter(patient=patient).order_by('measured_date')[:40]
            )
        except Exception:  # noqa: BLE001
            pass
        triage_anthro = (
            TriageEntry.objects.filter(visit__patient=patient)
            .exclude(weight__isnull=True)
            .order_by('entry_date')[:40]
        )
        # Normalize triage rows for build_growth_series
        class _TriagePoint:
            def __init__(self, entry):
                self.measured_date = entry.entry_date.date() if entry.entry_date else None
                self.weight_kg = entry.weight
                self.height_cm = entry.height

        growth_records.extend(_TriagePoint(e) for e in triage_anthro if e.weight)
        context['growth_chart'] = build_growth_series(patient, growth_records)
        latest_triage = (
            TriageEntry.objects.filter(visit__patient=patient)
            .order_by('-entry_date')
            .first()
        )
        context['latest_bmi'] = None
        context['latest_bmi_category'] = ''
        if latest_triage and latest_triage.bmi:
            context['latest_bmi'] = latest_triage.bmi
            context['latest_bmi_category'] = latest_triage.bmi_category
        elif context['growth_chart']['points']:
            last = context['growth_chart']['points'][-1]
            context['latest_bmi'] = last.get('bmi')
            context['latest_bmi_category'] = last.get('bmi_category') or ''

        from .models import ClinicalSummary
        context['clinical_summaries'] = ClinicalSummary.objects.filter(
            patient=patient,
        ).select_related('visit', 'generated_by').order_by('-generated_at')[:10]
        if selected_visit:
            context['visit_clinical_summary'] = ClinicalSummary.objects.filter(
                visit=selected_visit,
            ).order_by('-generated_at').first()
        else:
            context['visit_clinical_summary'] = context['clinical_summaries'][0] if context['clinical_summaries'] else None

        # Clinical Decision Support (uses problem list, HPT, allergies, demographics, labs, vitals)
        from .clinical_decision_support import evaluate_cds
        visit_for_cds = selected_visit or latest_visit
        try:
            context['cds'] = evaluate_cds(patient, visit=visit_for_cds)
        except Exception:  # noqa: BLE001 — never break chart on CDS failure
            context['cds'] = {
                'success': False,
                'alerts': [],
                'summary': {'total': 0, 'critical': 0, 'high': 0, 'moderate': 0, 'blocking': 0},
                'inputs_used': {},
            }
        
        # Get lab results and reports for this patient
        from lab.models import LabResult, LabReport
        lab_results = LabResult.objects.filter(**lab_filter).select_related('service', 'requested_by', 'invoice_item__procedure_completion').order_by('-requested_at')
        context['lab_results'] = lab_results
        
        # Get lab reports for this patient
        lab_report_ids = lab_results.values_list('id', flat=True)
        context['lab_reports'] = LabReport.objects.filter(lab_result_id__in=lab_report_ids).select_related('lab_result', 'created_by').order_by('-created_at')
        
        # Get prescriptions for this patient
        prescriptions = Prescription.objects.filter(**prescription_filter).select_related('prescribed_by', 'visit').order_by('-id')
        context['prescriptions'] = prescriptions
        
        # Get medical tests services for the Next Action section
        # FILTERED BY DEPARTMENT: Lab, Imaging, Procedure, etc.
        medical_tests = Service.objects.filter(
            is_active=True,
            department__isnull=False
        ).select_related('department').order_by('department__name', 'name')
        context['medical_tests'] = medical_tests
        
        # Prepare medical tests data as JSON for JavaScript
        medical_tests_data = []
        for test in medical_tests:
            medical_tests_data.append({
                'id': test.pk,
                'name': test.name,
                'department_id': test.department.id,
                'department_name': test.department.name.lower(),
                'price': str(test.price) if test.price else None,
                'sha_intervention_code': test.sha_intervention_code or '',
                'sha_intervention_name': test.sha_intervention_name or '',
            })
        context['medical_tests_data'] = medical_tests_data
        context['medical_tests_json'] = json.dumps(medical_tests_data)
        try:
            context['sha_visit_billed'] = bool(
                selected_visit
                and (
                    (selected_visit.payment_method or '').upper() in ('SHA', 'INSURANCE', 'SHIF', 'UHC')
                    or getattr(selected_visit, 'sha_claim_session', None)
                )
            )
            context['sha_preauth_check_url'] = reverse('home:sha_preauth_check_api')
        except Exception:
            context['sha_visit_billed'] = False
            context['sha_preauth_check_url'] = ''
        
        # Get departments for the "Send To" options (only Lab, Imaging, Procedure Room)
        context['available_departments'] = Departments.objects.filter(
            name__in=['Lab', 'Imaging', 'Procedure Room']
        ).order_by('name')
        
        # Get dispensed items history (Normalized)
        context['dispensed_items'] = _get_normalized_history(selected_visit, patient)
        
        # Get procedures (billed services specifically in clinical departments)
        # Avoid showing items that are already tracked by the LabResult ordering system
        if selected_visit:
            existing_lab_item_ids = LabResult.objects.filter(invoice__visit=selected_visit, invoice_item__isnull=False).values_list('invoice_item_id', flat=True)
            procedures = InvoiceItem.objects.filter(
                invoice__visit=selected_visit,
                service__isnull=False,
                service__department__name__in=['Procedure Room', 'Imaging', 'Lab']
            ).exclude(id__in=existing_lab_item_ids).select_related('service', 'procedure_completion').order_by('-created_at')
        else:
            existing_lab_item_ids = LabResult.objects.filter(invoice__visit__patient=patient, invoice_item__isnull=False).values_list('invoice_item_id', flat=True)
            procedures = InvoiceItem.objects.filter(
                invoice__patient=patient,
                service__isnull=False,
                service__department__name__in=['Procedure Room', 'Imaging', 'Lab']
            ).exclude(id__in=existing_lab_item_ids).select_related('service', 'procedure_completion').order_by('-created_at')
        
        context['procedures'] = procedures
        
        # Get departments for dispensing widget
        context['dispensing_departments'] = Departments.objects.all().order_by('name')
        
        return context

@login_required
def quick_triage_entry(request):
    if request.method == 'POST':
        try:
            patient_id = request.POST.get('patient_id')
            priority = request.POST.get('priority')
            category = request.POST.get('category')
            send_to = request.POST.get('send_to')
            triage_notes = request.POST.get('triage_notes', '')
            
            # Get vital signs
            temperature = request.POST.get('temperature')
            bp_systolic = request.POST.get('bp_systolic')
            bp_diastolic = request.POST.get('bp_diastolic')
            heart_rate = request.POST.get('heart_rate')
            respiratory_rate = request.POST.get('respiratory_rate')
            oxygen_saturation = request.POST.get('oxygen_saturation')
            
            # Get patient and create visit if needed
            patient = get_object_or_404(Patient, pk=patient_id)
            
            # Create or get the most recent visit for this patient
            visit, created = Visit.objects.get_or_create(
                patient=patient,
                visit_type='OUT-PATIENT',
                visit_mode='Walk In'
            )
            
            # Create triage entry
            triage_entry = TriageEntry.objects.create(
                visit=visit,
                triage_nurse=request.user,
                priority=priority,
                category=category,
                triage_notes=triage_notes,
                temperature=float(temperature) if temperature else None,
                blood_pressure_systolic=int(bp_systolic) if bp_systolic else None,
                blood_pressure_diastolic=int(bp_diastolic) if bp_diastolic else None,
                heart_rate=int(heart_rate) if heart_rate else None,
                respiratory_rate=int(respiratory_rate) if respiratory_rate else None,
                oxygen_saturation=int(oxygen_saturation) if oxygen_saturation else None,
            )
            
            # Determine department name and abbreviation
            if send_to == "Maternity":
                # Fallback purely for legacy
                dept_name = "Maternity"
                dept_abbr = "MAT"
            elif send_to == "ANC":
                dept_name = "ANC"
                dept_abbr = "ANC"
            elif send_to == "PNC":
                dept_name = "PNC"
                dept_abbr = "PNC"
            elif send_to.isdigit():
                dept_name = f'Consultation Room {send_to}'
                dept_abbr = f'CR{send_to}'
            else:
                dept_name = send_to
                dept_abbr = send_to[:10].upper()

            # Create or get consultation room department
            consultation_room, created = Departments.objects.get_or_create(
                name=dept_name,
                defaults={'abbreviation': dept_abbr}
            )
            
            # Create patient queue entry
            PatientQue.objects.create(
                visit=visit,
                qued_from=None,  # From triage
                sent_to=consultation_room,
                created_by=request.user
            )
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
def add_consultation_note(request):
    if request.user.role != 'Doctor':
        return JsonResponse({'success': False, 'error': 'Only doctors can record clinical notes.'})
    
    if request.method == 'POST':
        try:
            from .clinical_gates import doctor_requires_tb_screening, TB_SCREENING_MESSAGE
            patient_id = request.POST.get('patient_id')
            consultation_id = request.POST.get('consultation_id')
            doctor_id = request.POST.get('doctor_id')
            note_content = request.POST.get('note_content')
            note_type = request.POST.get('note_type', 'GENERAL')
            note_type_detail = request.POST.get('note_type_detail', '').strip()
            
            # Append focus area to note content if provided
            if note_type_detail:
                note_content = f"{note_content}\n\nFocus Area: {note_type_detail}"
            
            # Get patient
            patient = get_object_or_404(Patient, pk=patient_id)
            
            # Identify the latest visit
            latest_visit = Visit.objects.filter(patient=patient).order_by('-visit_date').first()
            
            if not latest_visit:
                return JsonResponse({'success': False, 'error': 'No active visit found for this patient.'})

            if not latest_visit.is_active:
                return JsonResponse({'success': False, 'error': f'Visit for {patient.full_name} is already closed. Please create a new visit to record notes.'})

            if doctor_requires_tb_screening(request.user, latest_visit):
                return JsonResponse({'success': False, 'error': TB_SCREENING_MESSAGE})

            # Handle consultation
            consultation = None
            
            # If a specific consultation is provided, use it
            if consultation_id and consultation_id != 'new':
                consultation = get_object_or_404(Consultation, pk=consultation_id)
                # Ensure this consultation belongs to the latest visit
                if consultation.visit != latest_visit:
                    return JsonResponse({'success': False, 'error': 'Cannot add notes to a previous visit. Please select the latest visit.'})
            else:
                # We are creating a new note, it MUST be for the latest visit
                # Find or create a consultation for the latest visit
                consultation = Consultation.objects.filter(visit=latest_visit, doctor=request.user).first()
                if not consultation:
                    # If no consultation exists for the latest visit, we create one
                    consultation = Consultation.objects.create(
                        visit=latest_visit,
                        doctor=request.user,
                    )
            
            # Create consultation note
            note = ConsultationNotes.objects.create(
                consultation=consultation,
                notes=note_content,
                created_by=request.user
            )
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
def submit_next_action(request):
    allowed_roles = ['Doctor', 'Nurse', 'Receptionist', 'Triage Nurse', 'Admin']
    if request.user.role not in allowed_roles:
        return JsonResponse({'success': False, 'error': 'You are not authorized to perform this action.'})
    
    if request.method == 'POST':
        try:
            patient_id = request.POST.get('patient_id')
            send_to_departments = request.POST.getlist('send_to')
            selected_tests = request.POST.getlist('tests')
            
            patient = get_object_or_404(Patient, pk=patient_id)
            
            # Identify the latest visit
            latest_visit = Visit.objects.filter(patient=patient).order_by('-visit_date').first()
            
            # Block if no visit or if visit is already closed
            if not latest_visit or not latest_visit.is_active:
                return JsonResponse({'success': False, 'error': f'Visit for {patient.full_name} is not active. Clinical actions cannot be performed without an active visit.'})

            visit = latest_visit

            from .clinical_gates import doctor_requires_tb_screening, TB_SCREENING_MESSAGE
            if doctor_requires_tb_screening(request.user, visit):
                return JsonResponse({'success': False, 'error': TB_SCREENING_MESSAGE})
            
            # Process department routing
            for dept in send_to_departments:
                # Create or get destination department
                if dept == 'pharmacy':
                    dept_name = 'Pharmacy'
                    dept_abbr = 'PHR'
                elif dept == 'ANC':
                    dept_name = 'ANC'
                    dept_abbr = 'ANC'
                elif dept == 'PNC':
                    dept_name = 'PNC'
                    dept_abbr = 'PNC'
                else:
                    # Use the actual service type name
                    try:
                        dept_name = dept.replace('_', ' ').title()
                        dept_abbr = dept[:3].upper()
                    except:
                        dept_name = dept.title()
                        dept_abbr = dept[:3].upper()
                
                destination_dept, created = Departments.objects.get_or_create(
                    name=dept_name,
                    defaults={'abbreviation': dept_abbr}
                )
                
                # Identify the consultation department we are moving FROM
                current_consultation_entry = PatientQue.objects.filter(
                    visit=visit,
                    sent_to__name__icontains='Consultation',
                    status='PENDING'
                ).first()
                
                from_dept = current_consultation_entry.sent_to if current_consultation_entry else None

                # Mark the entry the patient is currently in as COMPLETED
                if current_consultation_entry:
                    current_consultation_entry.status = 'COMPLETED'
                    current_consultation_entry.save()

                # Create queue entry ONLY if a visit exists
                if visit:
                    PatientQue.objects.create(
                        visit=visit,
                        qued_from=from_dept, # Record that we came from this consultation room
                        sent_to=destination_dept,
                        created_by=request.user,
                        status='PENDING',
                        queue_type='INITIAL'
                    )
            
            # Process selected tests and create service invoices
            if selected_tests:
                # Get or Create Visit Invoice (Consolidated)
                invoice = get_or_create_invoice(visit=visit, user=request.user)
                invoice_id = invoice.id

                # ANC Profile Bundle Automation
                anc_profile_service = Service.objects.filter(pk__in=selected_tests, name__icontains='ANC Profile').first()
                bundled_tests_names = [
                    "Haemoglobin level (HB)",
                    "Rhesus",
                    "Random Blood Sugar (RBS)",
                    "Urinalysis",
                    "Hepatitis B Surface Antigen (HBsAg)",
                    "Blood grouping"
                ]

                if anc_profile_service:
                    # Add bundled tests if not already in selection
                    bundled_services_ids = Service.objects.filter(name__in=bundled_tests_names).values_list('id', flat=True)
                    for b_id in bundled_services_ids:
                        if str(b_id) not in selected_tests:
                            selected_tests.append(str(b_id))
                
                items_created = 0
                ordered_services = []
                for test_id in selected_tests:
                    try:
                        service = Service.objects.get(pk=test_id)
                        ordered_services.append(service)
                        
                        # Determine Price (Free if part of ANC Profile bundle)
                        unit_price = service.price
                        if anc_profile_service and service.name in bundled_tests_names:
                            unit_price = 0

                        item = InvoiceItem.objects.create(
                            invoice=invoice,
                            service=service,
                            name=service.name,
                            unit_price=unit_price,
                            quantity=1
                        )

                        # Automatically create LabResult for Lab/Imaging/Procedure tests
                        if service.department.name in ['Lab', 'Imaging', 'Procedure Room']:
                            test_notes = request.POST.get(f'test_notes_{test_id}', '')
                            test_specimen = request.POST.get(f'test_specimen_{test_id}', '')
                            LabResult.objects.create(
                                patient=patient,
                                service=service,
                                invoice=invoice,
                                invoice_item=item,
                                requested_by=request.user,
                                clinical_notes=test_notes,
                                specimen=test_specimen if test_specimen else None,
                                status='Pending'
                            )

                        items_created += 1
                    except Service.DoesNotExist:
                        continue
                
                if items_created == 0:
                    invoice.delete() # Don't keep empty invoices
                    invoice_id = None

                try:
                    from accounts.sha_preauth_check import check_services_preauth
                    preauth_advisory = check_services_preauth(visit, ordered_services)
                except Exception:
                    preauth_advisory = None
            else:
                preauth_advisory = None

            msg = (
                f'Next action processed for {patient.first_name} {patient.last_name}. '
                f'Patient routed to {len(send_to_departments)} department(s) and '
                f'{len(selected_tests)} test(s) ordered.'
            )
            if preauth_advisory and preauth_advisory.get('inform_patient'):
                msg += (
                    f" SHA preauth: {len(preauth_advisory['inform_patient'])} item(s) "
                    "require pre-authorization — inform the patient."
                )

            return JsonResponse({
                'success': True,
                'invoice_id': invoice_id if selected_tests else None,
                'message': msg,
                'preauth': preauth_advisory,
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)})


# Emergency Contact Views
class EmergencyContactCreateView(LoginRequiredMixin, CreateView):
    """View for creating emergency contact records"""
    model = EmergencyContact
    form_class = EmergencyContactForm
    template_name = 'home/emergency_contact_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient_id = self.kwargs['patient_pk']
        context['patient'] = get_object_or_404(Patient, pk=patient_id)
        return context
    
    def form_valid(self, form):
        patient_id = self.kwargs['patient_pk']
        patient = get_object_or_404(Patient, pk=patient_id)
        form.instance.patient = patient
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Emergency contact {form.instance.name} has been added for {patient.full_name}.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('home:patient_detail', kwargs={'pk': self.kwargs['patient_pk']})


class EmergencyContactUpdateView(LoginRequiredMixin, UpdateView):
    """View for updating emergency contact records"""
    model = EmergencyContact
    form_class = EmergencyContactForm
    template_name = 'home/emergency_contact_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['patient'] = self.object.patient
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Emergency contact {form.instance.name} has been updated.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('home:patient_detail', kwargs={'pk': self.object.patient.pk})


class EmergencyContactDeleteView(LoginRequiredMixin, DeleteView):
    """View for deleting emergency contact records"""
    model = EmergencyContact
    template_name = 'home/emergency_contact_confirm_delete.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['patient'] = self.object.patient
        return context
    
    def delete(self, request, *args, **kwargs):
        contact = self.get_object()
        patient_name = contact.patient.full_name
        contact_name = contact.name
        messages.success(request, f'Emergency contact {contact_name} has been removed for {patient_name}.')
        return super().delete(request, *args, **kwargs)
    
    def get_success_url(self):
        return reverse_lazy('home:patient_detail', kwargs={'pk': self.object.patient.pk})


@login_required
def set_primary_emergency_contact(request, patient_pk, contact_pk):
    """Set an emergency contact as primary"""
    patient = get_object_or_404(Patient, pk=patient_pk)
    contact = get_object_or_404(EmergencyContact, pk=contact_pk, patient=patient)
    
    # Remove primary status from all other contacts
    EmergencyContact.objects.filter(patient=patient).exclude(pk=contact_pk).update(is_primary=False)
    
    # Set this contact as primary
    contact.is_primary = True
    contact.save()
    
    messages.success(request, f'{contact.name} has been set as the primary emergency contact for {patient.full_name}.')
    return redirect('home:patient_detail', pk=patient_pk)
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


from django.views.decorators.csrf import ensure_csrf_cookie

@login_required
@ensure_csrf_cookie
def reception_dashboard(request):
    """Reception dashboard view showing different content based on user role"""
    # Get search query for invoices (only for receptionists)
    invoice_search = request.GET.get('invoice_search', '')
    
    # Get search queries for triage (only for triage nurses)
    triage_search = request.GET.get('triage_search', '')
    pending_search = request.GET.get('pending_search', '')
    
    # Get user role
    user_role = request.user.role
    
    # Get today's visits
    today = timezone.localdate()
    start_of_day = timezone.make_aware(datetime.combine(today, time.min))
    end_of_day = timezone.make_aware(datetime.combine(today, time.max))
    today_visits = Visit.objects.filter(
        visit_date__range=(start_of_day, end_of_day),
    ).filter(_nurse_visit_q(request.user)).count()
    
    # Get total patients count
    total_patients = Patient.objects.count()
    
    # Initialize context with common data
    context = {
        'today_visits': today_visits,
        'total_patients': total_patients,
        'triage_search': triage_search,
        'pending_search': pending_search,
        'user_role': user_role,
        'ipd_admissions': Admission.objects.filter(status='Admitted').select_related('patient', 'bed', 'bed__ward'),
        'morgue_admissions': MorgueAdmission.objects.filter(status='ADMITTED').select_related('deceased'),
    }
    
    if user_role == 'Receptionist' or user_role == 'Admin':
        # Receptionist (and Admin) sees invoices for today's visits only
        invoices = Invoice.objects.annotate(
            balance_due=F('total_amount') - F('insurance_adjustment') - F('paid_amount')
        ).filter(
            Q(status__in=['Pending', 'Partial', 'Draft']) & 
            (Q(visit__visit_type='OUT-PATIENT') | Q(visit__visit_type='IN-PATIENT', visit__admissions__isnull=True)) &
            Q(balance_due__gt=0) &
            Q(visit__visit_date__range=(start_of_day, end_of_day))
        ).filter(_nurse_visit_q(request.user, prefix='visit__')).select_related('patient', 'deceased').prefetch_related(
            Prefetch('items', queryset=InvoiceItem.objects.filter(paid_amount__lt=F('amount')).select_related('service'))
        )
        
        if invoice_search:
            invoices = invoices.filter(
                Q(patient__first_name__icontains=invoice_search) |
                Q(patient__last_name__icontains=invoice_search) |
                Q(deceased__surname__icontains=invoice_search) |
                Q(deceased__other_names__icontains=invoice_search) |
                Q(items__name__icontains=invoice_search) |
                Q(id__icontains=invoice_search)
            ).distinct()
        
        invoices = invoices.order_by('-created_at')
        
        # Get unpaid invoices count (today's visits only)
        unpaid_invoices = Invoice.objects.annotate(
            balance_due=F('total_amount') - F('insurance_adjustment') - F('paid_amount')
        ).filter(
            Q(status__in=['Pending', 'Partial', 'Draft']) & 
            (Q(visit__visit_type='OUT-PATIENT') | Q(visit__visit_type='IN-PATIENT', visit__admissions__isnull=True)) &
            Q(balance_due__gt=0) &
            Q(visit__visit_date__range=(start_of_day, end_of_day))
        ).filter(_nurse_visit_q(request.user, prefix='visit__')).count()
        
        # Get active services grouped by department for quick invoicing
        services = Service.objects.filter(is_active=True).select_related('department').order_by('department__name', 'name')
        
        context.update({
            'invoices': invoices,
            'unpaid_invoices': unpaid_invoices,
            'invoice_search': invoice_search,
            'services': services,
        })
        
    elif user_role == 'Triage Nurse' or user_role == 'Nurse':
        # Triage Nurse sees triage entries and visits without triage (today only)
        triage_entries = TriageEntry.objects.filter(
            visit__visit_date__range=(start_of_day, end_of_day),
        ).filter(_nurse_visit_q(request.user, prefix='visit__')).select_related('visit__patient', 'triage_nurse')
        
        if triage_search:
            triage_entries = triage_entries.filter(
                Q(visit__patient__first_name__icontains=triage_search) |
                Q(visit__patient__last_name__icontains=triage_search) |
                Q(visit__patient__phone__icontains=triage_search)
            )
            
        triage_entries = triage_entries.order_by('-entry_date')[:10]
        
        # Get today's visits without triage entries
        visits_with_triage = Visit.objects.filter(
            triage_entries__isnull=False,
            visit_date__range=(start_of_day, end_of_day),
        ).filter(_nurse_visit_q(request.user)).values_list('pk', flat=True)
        visits_without_triage = Visit.objects.filter(
            ~Q(pk__in=visits_with_triage),
            visit_date__range=(start_of_day, end_of_day),
            patient_queue__sent_to__name='Triage',
            patient_queue__status='PENDING',
        ).filter(_nurse_visit_q(request.user)).select_related('patient').prefetch_related('invoice__items__service').distinct()
        
        if pending_search:
            visits_without_triage = visits_without_triage.filter(
                Q(patient__first_name__icontains=pending_search) |
                Q(patient__last_name__icontains=pending_search) |
                Q(patient__phone__icontains=pending_search) |
                Q(invoice__items__service__name__icontains=pending_search) |
                Q(invoice__items__name__icontains=pending_search)
            ).distinct()
            
        visits_without_triage = visits_without_triage.order_by('-visit_date')[:10]

        # Tag maternity visits based on services in recent invoices
        for visit in visits_without_triage:
            visit.is_maternity = False
            visit.services_list = []
            if hasattr(visit, 'invoice') and visit.invoice:
                for item in visit.invoice.items.all():
                    if item.service:
                        visit.services_list.append(item.service.name)
                        if "ANC" in item.service.name.upper() or "PNC" in item.service.name.upper():
                            visit.is_maternity = True
            visit.services_summary = ", ".join(visit.services_list[:3])
        
        # Get triage entries count for today's visits
        today_triage_entries = TriageEntry.objects.filter(
            visit__visit_date__range=(start_of_day, end_of_day),
        ).filter(_nurse_visit_q(request.user, prefix='visit__')).count()
        
        # Get pending triage count (visits without triage)
        pending_triage_count = Visit.objects.filter(
            ~Q(pk__in=visits_with_triage),
            visit_date__range=(start_of_day, end_of_day),
            patient_queue__sent_to__name='Triage',
            patient_queue__status='PENDING',
        ).filter(_nurse_visit_q(request.user)).distinct().count()
        
        context.update({
            'triage_entries': triage_entries,
            'visits_without_triage': visits_without_triage,
            'today_triage_entries': today_triage_entries,
            'pending_triage_count': pending_triage_count,
        })
    
    return render(request, 'home/reception_dashboard.html', context)


@login_required
def add_symptoms(request):
    """Add or update symptoms for a visit (only 1 symptom entry per visit)"""
    if request.method == 'POST':
        try:
            visit_id = request.POST.get('visit_id')
            data = request.POST.get('data')
            days = request.POST.get('days') or 0
            
            visit = get_object_or_404(Visit, pk=visit_id)
            
            # Block if not latest visit or if visit is not active
            latest_visit = Visit.objects.filter(patient=visit.patient).order_by('-visit_date').first()
            if visit != latest_visit:
                return JsonResponse({'success': False, 'error': 'Cannot add symptoms to a previous visit.'})
            
            if not visit.is_active:
                return JsonResponse({'success': False, 'error': 'Cannot add symptoms to a closed visit. Please create a new visit.'})

            from .clinical_gates import doctor_requires_tb_screening, TB_SCREENING_MESSAGE
            if doctor_requires_tb_screening(request.user, visit):
                return JsonResponse({'success': False, 'error': TB_SCREENING_MESSAGE})

            from .models import Symptoms
            
            Symptoms.objects.update_or_create(
                visit=visit,
                defaults={
                    'data': data,
                    'days': days,
                    'created_by': request.user
                }
            )
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
def refer_patient(request, visit_id):
    visit = get_object_or_404(Visit, pk=visit_id)
    patient = visit.patient
    
    # Check if a referral already exists for this visit
    referral = Referral.objects.filter(visit=visit).first()
    
    if request.method == 'POST':
        from .clinical_gates import doctor_requires_tb_screening, TB_SCREENING_MESSAGE
        if doctor_requires_tb_screening(request.user, visit):
            messages.warning(request, TB_SCREENING_MESSAGE)
            return redirect(f"{reverse('home:patient_detail', kwargs={'pk': patient.pk})}?visit_id={visit.pk}#visits")
        form = ReferralForm(request.POST, instance=referral)
        if form.is_valid():
            referral = form.save(commit=False)
            referral.visit = visit
            referral.doctor = request.user
            referral.save()
            messages.success(request, 'Referral generated successfully.')
            return redirect('home:refer_patient', visit_id=visit.id)
    else:
        # Pre-fill clinical summary from existing data if creating new
        initial_data = {}
        if not referral:
            # Aggregate clinical info
            summary_parts = []
            
            # Impressions
            impressions = visit.impressions.all()
            if impressions:
                summary_parts.append("Impressions: " + "; ".join([i.data for i in impressions]))
                
            # Diagnoses
            diagnoses = visit.diagnoses.all()
            if diagnoses:
                summary_parts.append("Diagnoses: " + "; ".join([d.data for d in diagnoses]))
            
            if summary_parts:
                initial_data['clinical_summary'] = "\n\n".join(summary_parts)
                
        form = ReferralForm(instance=referral, initial=initial_data)

    # Gather Context Data
    triage = TriageEntry.objects.filter(visit=visit).first()
    symptoms = visit.symptoms.all() # Correct related_name from Symptoms model
    impressions = visit.impressions.all()
    diagnoses = visit.diagnoses.all()
    
    # Consultation Notes
    consultations = Consultation.objects.filter(visit=visit)
    notes = ConsultationNotes.objects.filter(consultation__in=consultations)
    
    # Lab Results - connected via Invoice
    # Find invoices for this visit
    invoices = Invoice.objects.filter(visit=visit)
    # Find lab results for these invoices
    lab_results = LabResult.objects.filter(invoice__in=invoices)

    # Inpatient data
    admission = None
    if visit.visit_type == 'IN-PATIENT':
        try:
            from inpatient.models import Admission, PatientVitals
            admission = Admission.objects.filter(visit=visit).first()
            if admission and not triage:
                # Try to get vitals from inpatient records if no triage entry
                latest_vitals = PatientVitals.objects.filter(admission=admission).order_by('-recorded_at').first()
                if latest_vitals:
                    # Mock a triage object for template compatibility
                    triage = {
                        'entry_date': latest_vitals.recorded_at,
                        'blood_pressure_systolic': latest_vitals.systolic_bp,
                        'blood_pressure_diastolic': latest_vitals.diastolic_bp,
                        'heart_rate': latest_vitals.pulse_rate,
                        'temperature': latest_vitals.temperature,
                        'oxygen_saturation': latest_vitals.spo2,
                    }
        except ImportError:
            pass

    # Determine back URL
    if admission:
        from django.urls import reverse
        back_url = reverse('inpatient:patient_case_folder', kwargs={'admission_id': admission.id})
    else:
        from django.urls import reverse
        back_url = reverse('home:patient_detail', kwargs={'pk': patient.pk})

    context = {
        'visit': visit,
        'patient': patient,
        'form': form,
        'referral': referral,
        'triage': triage,
        'symptoms': symptoms,
        'impressions': impressions,
        'diagnoses': diagnoses,
        'notes': notes,
        'lab_results': lab_results,
        'today': timezone.now().date(),
        'admission': admission,
        'back_url': back_url,
    }
    
    return render(request, 'home/refer_patient.html', context)

@login_required
def add_impression(request):
    """Add impression to a visit"""
    if request.method == 'POST':
        try:
            visit_id = request.POST.get('visit_id')
            data = request.POST.get('data')
            
            visit = get_object_or_404(Visit, pk=visit_id)
            
            # Block if not latest visit or if visit is not active
            latest_visit = Visit.objects.filter(patient=visit.patient).order_by('-visit_date').first()
            if visit != latest_visit:
                return JsonResponse({'success': False, 'error': 'Cannot add impressions to a previous visit.'})
                
            if not visit.is_active:
                return JsonResponse({'success': False, 'error': 'Cannot add impressions to a closed visit.'})

            from .clinical_gates import doctor_requires_tb_screening, TB_SCREENING_MESSAGE
            if doctor_requires_tb_screening(request.user, visit):
                return JsonResponse({'success': False, 'error': TB_SCREENING_MESSAGE})

            from .models import Impression
            Impression.objects.create(
                visit=visit,
                data=data,
                created_by=request.user
            )
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def update_impression(request, pk):
    """Update an existing impression"""
    if request.method == 'POST':
        try:
            from .models import Impression
            impression = get_object_or_404(Impression, pk=pk)
            visit = impression.visit

            latest_visit = Visit.objects.filter(patient=visit.patient).order_by('-visit_date').first()
            if visit != latest_visit:
                return JsonResponse({'success': False, 'error': 'Cannot edit impressions on a previous visit.'})
            if not visit.is_active:
                return JsonResponse({'success': False, 'error': 'Cannot edit impressions on a closed visit.'})

            from .clinical_gates import doctor_requires_tb_screening, TB_SCREENING_MESSAGE
            if doctor_requires_tb_screening(request.user, visit):
                return JsonResponse({'success': False, 'error': TB_SCREENING_MESSAGE})

            data = request.POST.get('data')
            impression.data = data
            impression.updated_by = request.user
            impression.save()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def add_diagnosis(request):
    """Add ICD-11 coded diagnosis to a visit; optionally promote to problem list."""
    if request.method == 'POST':
        try:
            from django.core.exceptions import ValidationError as DjangoValidationError
            from .icd11_diagnosis import validate_and_resolve_diagnosis

            visit_id = request.POST.get('visit_id')
            data = request.POST.get('data')
            add_to_problem_list = request.POST.get('add_to_problem_list', '1') in ('1', 'true', 'yes', 'on')

            visit = get_object_or_404(Visit, pk=visit_id)

            latest_visit = Visit.objects.filter(patient=visit.patient).order_by('-visit_date').first()
            if visit != latest_visit:
                return JsonResponse({'success': False, 'error': 'Cannot add diagnosis to a previous visit.'})

            if not visit.is_active:
                return JsonResponse({'success': False, 'error': 'Cannot add diagnosis to a closed visit.'})

            from .clinical_gates import doctor_requires_tb_screening, TB_SCREENING_MESSAGE
            if doctor_requires_tb_screening(request.user, visit):
                return JsonResponse({'success': False, 'error': TB_SCREENING_MESSAGE})

            try:
                code, display, entry = validate_and_resolve_diagnosis(data, required=True)
            except DjangoValidationError as exc:
                msg = '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)
                return JsonResponse({'success': False, 'error': msg})

            diagnosis = Diagnosis.objects.create(
                visit=visit,
                data=display,
                icd11_code=code,
                icd11_entry=entry,
                created_by=request.user,
            )

            problem = None
            if add_to_problem_list:
                problem = _upsert_problem_from_diagnosis(
                    diagnosis, recorded_by=request.user, visit=visit,
                )

            return JsonResponse({
                'success': True,
                'diagnosis_id': diagnosis.pk,
                'problem_id': problem.pk if problem else None,
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
def update_diagnosis(request, pk):
    """Update an existing visit diagnosis (ICD-11 coded)."""
    if request.method == 'POST':
        try:
            from django.core.exceptions import ValidationError as DjangoValidationError
            from .icd11_diagnosis import validate_and_resolve_diagnosis

            diagnosis = get_object_or_404(Diagnosis, pk=pk)
            visit = diagnosis.visit

            latest_visit = Visit.objects.filter(patient=visit.patient).order_by('-visit_date').first()
            if visit != latest_visit:
                return JsonResponse({'success': False, 'error': 'Cannot edit diagnosis on a previous visit.'})
            if not visit.is_active:
                return JsonResponse({'success': False, 'error': 'Cannot edit diagnosis on a closed visit.'})

            from .clinical_gates import doctor_requires_tb_screening, TB_SCREENING_MESSAGE
            if doctor_requires_tb_screening(request.user, visit):
                return JsonResponse({'success': False, 'error': TB_SCREENING_MESSAGE})

            data = request.POST.get('data')
            try:
                code, display, entry = validate_and_resolve_diagnosis(data, required=True)
            except DjangoValidationError as exc:
                msg = '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)
                return JsonResponse({'success': False, 'error': msg})

            diagnosis.data = display
            diagnosis.icd11_code = code
            diagnosis.icd11_entry = entry
            diagnosis.updated_by = request.user
            diagnosis.save()

            if request.POST.get('add_to_problem_list', '0') in ('1', 'true', 'yes', 'on'):
                _upsert_problem_from_diagnosis(
                    diagnosis, recorded_by=request.user, visit=visit,
                )

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})


def _parse_optional_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None


def _upsert_problem_from_diagnosis(diagnosis, *, recorded_by, visit=None):
    """Create or refresh a problem-list item from a coded visit diagnosis."""
    code = (diagnosis.icd11_code or '').strip().upper()
    if not code:
        return None

    patient = diagnosis.visit.patient
    problem = (
        Problem.objects.filter(patient=patient, icd11_code__iexact=code)
        .exclude(verification_status='entered-in-error')
        .order_by('-updated_at')
        .first()
    )
    visit = visit or diagnosis.visit

    if problem is None:
        problem = Problem(
            patient=patient,
            visit=visit,
            source_diagnosis=diagnosis,
            display=diagnosis.data,
            icd11_code=code,
            icd11_entry=diagnosis.icd11_entry,
            clinical_status='active',
            verification_status='confirmed',
            category='problem-list-item',
            recorded_by=recorded_by,
            updated_by=recorded_by,
        )
        problem.save()
        problem.record_history(
            action='created',
            changed_by=recorded_by,
            change_summary='Created from visit diagnosis',
        )
        return problem

    changed = False
    if diagnosis.data and problem.display != diagnosis.data:
        problem.display = diagnosis.data
        changed = True
    if diagnosis.icd11_entry_id and problem.icd11_entry_id != diagnosis.icd11_entry_id:
        problem.icd11_entry = diagnosis.icd11_entry
        changed = True
    if visit and problem.visit_id != visit.pk:
        problem.visit = visit
        changed = True
    if not problem.source_diagnosis_id:
        problem.source_diagnosis = diagnosis
        changed = True
    if problem.clinical_status in ('resolved', 'inactive', 'remission'):
        problem.clinical_status = 'recurrence'
        problem.abatement_date = None
        changed = True
        action = 'reactivated'
        summary = 'Reactivated from visit diagnosis'
    else:
        action = 'updated'
        summary = 'Updated from visit diagnosis'

    if changed:
        problem.updated_by = recorded_by
        problem.save()
        problem.record_history(action=action, changed_by=recorded_by, change_summary=summary)
    return problem


@login_required
def add_problem(request, patient_pk):
    """Record a new KNHTS-coded problem list item for a patient."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=405)

    patient = get_object_or_404(Patient, pk=patient_pk)
    from django.core.exceptions import ValidationError as DjangoValidationError
    from .forms import ProblemForm
    from .knhts_conditions import ACTIVE_CLINICAL_STATUSES

    form = ProblemForm(request.POST)
    if not form.is_valid():
        errors = []
        for field, msgs in form.errors.items():
            errors.extend([f'{field}: {m}' for m in msgs])
        return JsonResponse({'success': False, 'error': '; '.join(errors) or 'Invalid data.'})

    code = getattr(form, '_icd11_code', '') or ''
    existing = None
    if code:
        existing = (
            Problem.objects.filter(patient=patient, icd11_code__iexact=code)
            .exclude(verification_status='entered-in-error')
            .filter(clinical_status__in=ACTIVE_CLINICAL_STATUSES)
            .first()
        )
    if existing:
        return JsonResponse({
            'success': False,
            'error': f'An active problem with ICD-11 code {code} already exists. Update that problem instead.',
            'problem_id': existing.pk,
        })

    visit_id = request.POST.get('visit_id')
    visit = None
    if visit_id:
        visit = Visit.objects.filter(pk=visit_id, patient=patient).first()

    problem = form.save(commit=False)
    problem.patient = patient
    problem.visit = visit
    problem.recorded_by = request.user
    problem.updated_by = request.user
    problem.save()
    problem.record_history(
        action='created',
        changed_by=request.user,
        change_summary='Problem recorded on problem list',
    )
    return JsonResponse({'success': True, 'problem_id': problem.pk})


@login_required
def update_problem(request, pk):
    """Update an existing problem list item (status, code, notes, dates)."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=405)

    problem = get_object_or_404(Problem, pk=pk)
    from .forms import ProblemForm

    previous_status = problem.clinical_status
    form = ProblemForm(request.POST, instance=problem)
    if not form.is_valid():
        errors = []
        for field, msgs in form.errors.items():
            errors.extend([f'{field}: {m}' for m in msgs])
        return JsonResponse({'success': False, 'error': '; '.join(errors) or 'Invalid data.'})

    problem = form.save(commit=False)
    problem.updated_by = request.user
    visit_id = request.POST.get('visit_id')
    if visit_id:
        visit = Visit.objects.filter(pk=visit_id, patient=problem.patient).first()
        if visit:
            problem.visit = visit
    problem.save()

    new_status = problem.clinical_status
    if previous_status != new_status:
        if new_status == 'resolved':
            action = 'resolved'
            summary = f'Status changed {previous_status} → resolved'
        elif previous_status in ('resolved', 'inactive', 'remission') and new_status in (
            'active', 'recurrence', 'relapse',
        ):
            action = 'reactivated'
            summary = f'Status changed {previous_status} → {new_status}'
        elif new_status == 'entered-in-error' or problem.verification_status == 'entered-in-error':
            action = 'entered_in_error'
            summary = 'Marked entered in error'
        else:
            action = 'status_changed'
            summary = f'Status changed {previous_status} → {new_status}'
    else:
        action = 'updated'
        summary = 'Problem details updated'

    problem.record_history(action=action, changed_by=request.user, change_summary=summary)
    return JsonResponse({'success': True, 'problem_id': problem.pk})


@login_required
def problem_history(request, patient_pk):
    """Return problem list + history for a patient (JSON)."""
    patient = get_object_or_404(Patient, pk=patient_pk)
    status_filter = (request.GET.get('status') or '').strip()
    problems_qs = Problem.objects.filter(patient=patient).select_related(
        'recorded_by', 'updated_by', 'icd11_entry', 'visit',
    )
    if status_filter == 'active':
        from .knhts_conditions import ACTIVE_CLINICAL_STATUSES
        problems_qs = problems_qs.filter(clinical_status__in=ACTIVE_CLINICAL_STATUSES)
    elif status_filter == 'resolved':
        problems_qs = problems_qs.filter(clinical_status__in=('resolved', 'remission', 'inactive'))
    elif status_filter:
        problems_qs = problems_qs.filter(clinical_status=status_filter)

    problems = []
    for p in problems_qs.order_by('-updated_at')[:200]:
        history = [
            {
                'id': h.pk,
                'action': h.action,
                'action_display': h.get_action_display(),
                'clinical_status': h.clinical_status,
                'verification_status': h.verification_status,
                'display': h.display,
                'icd11_code': h.icd11_code,
                'change_summary': h.change_summary,
                'changed_at': h.changed_at.isoformat() if h.changed_at else None,
                'changed_by': h.changed_by.get_full_name() if h.changed_by else None,
            }
            for h in p.history.all()[:30]
        ]
        problems.append({
            'id': p.pk,
            'display': p.display,
            'icd11_code': p.icd11_code,
            'clinical_status': p.clinical_status,
            'clinical_status_display': p.get_clinical_status_display(),
            'verification_status': p.verification_status,
            'verification_status_display': p.get_verification_status_display(),
            'category': p.category,
            'severity': p.severity,
            'onset_date': p.onset_date.isoformat() if p.onset_date else None,
            'abatement_date': p.abatement_date.isoformat() if p.abatement_date else None,
            'notes': p.notes,
            'is_active': p.is_active,
            'recorded_at': p.recorded_at.isoformat() if p.recorded_at else None,
            'updated_at': p.updated_at.isoformat() if p.updated_at else None,
            'history': history,
        })

    return JsonResponse({
        'success': True,
        'patient_id': patient.pk,
        'count': len(problems),
        'problems': problems,
    })


@login_required
def problem_detail_history(request, pk):
    """History entries for a single problem."""
    problem = get_object_or_404(Problem, pk=pk)
    entries = [
        {
            'id': h.pk,
            'action': h.action,
            'action_display': h.get_action_display(),
            'clinical_status': h.clinical_status,
            'verification_status': h.verification_status,
            'display': h.display,
            'icd11_code': h.icd11_code,
            'severity': h.severity,
            'onset_date': h.onset_date.isoformat() if h.onset_date else None,
            'abatement_date': h.abatement_date.isoformat() if h.abatement_date else None,
            'notes': h.notes,
            'change_summary': h.change_summary,
            'changed_at': h.changed_at.isoformat() if h.changed_at else None,
            'changed_by': (
                h.changed_by.get_full_name() or h.changed_by.username
            ) if h.changed_by else None,
        }
        for h in problem.history.select_related('changed_by').all()[:100]
    ]
    return JsonResponse({
        'success': True,
        'problem_id': problem.pk,
        'display': problem.display,
        'history': entries,
    })


@login_required
def add_patient_medication(request, patient_pk):
    """Add a longitudinal medication to the patient Active Medication List."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=405)

    patient = get_object_or_404(Patient, pk=patient_pk)
    from .forms import PatientMedicationForm
    from .models import PatientMedication

    form = PatientMedicationForm(request.POST)
    if not form.is_valid():
        errors = []
        for field, msgs in form.errors.items():
            errors.extend([f'{field}: {m}' for m in msgs])
        return JsonResponse({'success': False, 'error': '; '.join(errors) or 'Invalid data.'})

    code = (form.cleaned_data.get('generic_concept_code') or '').strip()
    if code:
        existing = PatientMedication.objects.filter(
            patient=patient, generic_concept_code__iexact=code, status='active',
        ).first()
        if existing:
            return JsonResponse({
                'success': False,
                'error': f'An active medication with HPT code {code} already exists. Update or stop that entry instead.',
                'medication_id': existing.pk,
            })

    visit_id = request.POST.get('visit_id')
    visit = Visit.objects.filter(pk=visit_id, patient=patient).first() if visit_id else None

    med = form.save(commit=False)
    med.patient = patient
    med.visit = visit
    med.source = 'manual'
    med.recorded_by = request.user
    med.updated_by = request.user
    if not med.start_date and med.status == 'active':
        from django.utils import timezone
        med.start_date = timezone.localdate()
    med.save()
    med.record_history(
        action='created',
        changed_by=request.user,
        change_summary='Clinician added to Active Medication List',
    )
    return JsonResponse({'success': True, 'medication_id': med.pk})


@login_required
def update_patient_medication(request, pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=405)

    from .forms import PatientMedicationForm
    from .models import PatientMedication

    med = get_object_or_404(PatientMedication, pk=pk)
    previous = med.status
    form = PatientMedicationForm(request.POST, instance=med)
    if not form.is_valid():
        errors = []
        for field, msgs in form.errors.items():
            errors.extend([f'{field}: {m}' for m in msgs])
        return JsonResponse({'success': False, 'error': '; '.join(errors) or 'Invalid data.'})

    med = form.save(commit=False)
    med.updated_by = request.user
    visit_id = request.POST.get('visit_id')
    if visit_id:
        visit = Visit.objects.filter(pk=visit_id, patient=med.patient).first()
        if visit:
            med.visit = visit
    if med.status in ('stopped', 'completed') and not med.end_date:
        from django.utils import timezone
        med.end_date = timezone.localdate()
    med.save()

    if previous != med.status:
        if med.status == 'stopped':
            action, summary = 'stopped', f'Status {previous} → stopped'
        elif med.status == 'completed':
            action, summary = 'completed', f'Status {previous} → completed'
        elif previous != 'active' and med.status == 'active':
            action, summary = 'reactivated', f'Status {previous} → active'
        elif med.status == 'entered-in-error':
            action, summary = 'entered_in_error', 'Marked entered in error'
        else:
            action, summary = 'status_changed', f'Status {previous} → {med.status}'
    else:
        action, summary = 'updated', 'Medication details updated'
    med.record_history(action=action, changed_by=request.user, change_summary=summary)
    return JsonResponse({'success': True, 'medication_id': med.pk})


@login_required
def patient_medication_history(request, patient_pk):
    """JSON: active + historical medications with audit trail."""
    patient = get_object_or_404(Patient, pk=patient_pk)
    from .models import PatientMedication

    status_filter = (request.GET.get('status') or '').strip()
    qs = PatientMedication.objects.filter(patient=patient).select_related(
        'recorded_by', 'updated_by', 'visit',
    ).prefetch_related('history')
    if status_filter == 'active':
        qs = qs.filter(status='active')
    elif status_filter == 'history':
        qs = qs.exclude(status='active')
    elif status_filter:
        qs = qs.filter(status=status_filter)

    rows = []
    for m in qs.order_by('-updated_at')[:200]:
        rows.append({
            'id': m.pk,
            'display_name': m.display_name,
            'generic_concept_code': m.generic_concept_code,
            'generic_concept_display': m.generic_concept_display,
            'actual_product_code': m.actual_product_code,
            'dose_text': m.dose_text,
            'frequency': m.frequency,
            'route': m.route,
            'status': m.status,
            'status_display': m.get_status_display(),
            'source': m.source,
            'start_date': m.start_date.isoformat() if m.start_date else None,
            'end_date': m.end_date.isoformat() if m.end_date else None,
            'notes': m.notes,
            'is_active': m.is_active,
            'history': [
                {
                    'id': h.pk,
                    'action': h.action,
                    'action_display': h.get_action_display(),
                    'status': h.status,
                    'change_summary': h.change_summary,
                    'changed_at': h.changed_at.isoformat() if h.changed_at else None,
                    'changed_by': h.changed_by.get_full_name() if h.changed_by else None,
                }
                for h in m.history.all()[:30]
            ],
        })
    return JsonResponse({'success': True, 'patient_id': patient.pk, 'count': len(rows), 'medications': rows})


@login_required
def add_patient_allergy(request, patient_pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=405)

    patient = get_object_or_404(Patient, pk=patient_pk)
    from .forms import PatientAllergyForm
    from .models import PatientAllergy

    form = PatientAllergyForm(request.POST)
    if not form.is_valid():
        errors = []
        for field, msgs in form.errors.items():
            errors.extend([f'{field}: {m}' for m in msgs])
        return JsonResponse({'success': False, 'error': '; '.join(errors) or 'Invalid data.'})

    hpt = (form.cleaned_data.get('hpt_code') or '').strip()
    name = form.cleaned_data.get('allergen_name') or ''
    if hpt:
        existing = PatientAllergy.objects.filter(
            patient=patient, hpt_code__iexact=hpt, clinical_status='active',
        ).first()
    else:
        existing = PatientAllergy.objects.filter(
            patient=patient, allergen_name__iexact=name, clinical_status='active',
        ).first()
    if existing:
        return JsonResponse({
            'success': False,
            'error': 'An active allergy for this allergen already exists. Update that entry instead.',
            'allergy_id': existing.pk,
        })

    visit_id = request.POST.get('visit_id')
    visit = Visit.objects.filter(pk=visit_id, patient=patient).first() if visit_id else None

    allergy = form.save(commit=False)
    allergy.patient = patient
    allergy.visit = visit
    allergy.recorded_by = request.user
    allergy.updated_by = request.user
    allergy.save()
    allergy.record_history(
        action='created',
        changed_by=request.user,
        change_summary='Allergy recorded on Allergy List',
    )
    return JsonResponse({'success': True, 'allergy_id': allergy.pk})


@login_required
def update_patient_allergy(request, pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=405)

    from .forms import PatientAllergyForm
    from .models import PatientAllergy

    allergy = get_object_or_404(PatientAllergy, pk=pk)
    previous = allergy.clinical_status
    form = PatientAllergyForm(request.POST, instance=allergy)
    if not form.is_valid():
        errors = []
        for field, msgs in form.errors.items():
            errors.extend([f'{field}: {m}' for m in msgs])
        return JsonResponse({'success': False, 'error': '; '.join(errors) or 'Invalid data.'})

    allergy = form.save(commit=False)
    allergy.updated_by = request.user
    visit_id = request.POST.get('visit_id')
    if visit_id:
        visit = Visit.objects.filter(pk=visit_id, patient=allergy.patient).first()
        if visit:
            allergy.visit = visit
    allergy.save()

    if previous != allergy.clinical_status:
        if allergy.clinical_status == 'resolved':
            action, summary = 'resolved', f'Status {previous} → resolved'
        elif previous != 'active' and allergy.clinical_status == 'active':
            action, summary = 'reactivated', f'Status {previous} → active'
        elif allergy.clinical_status == 'entered-in-error':
            action, summary = 'entered_in_error', 'Marked entered in error'
        else:
            action, summary = 'status_changed', f'Status {previous} → {allergy.clinical_status}'
    else:
        action, summary = 'updated', 'Allergy details updated'
    allergy.record_history(action=action, changed_by=request.user, change_summary=summary)
    return JsonResponse({'success': True, 'allergy_id': allergy.pk})


@login_required
def patient_allergy_history(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk)
    from .models import PatientAllergy

    status_filter = (request.GET.get('status') or '').strip()
    qs = PatientAllergy.objects.filter(patient=patient).select_related(
        'recorded_by', 'updated_by',
    ).prefetch_related('history')
    if status_filter == 'active':
        qs = qs.filter(clinical_status='active')
    elif status_filter == 'history':
        qs = qs.exclude(clinical_status='active')
    elif status_filter:
        qs = qs.filter(clinical_status=status_filter)

    rows = []
    for a in qs.order_by('-updated_at')[:200]:
        rows.append({
            'id': a.pk,
            'allergen_name': a.allergen_name,
            'hpt_code': a.hpt_code,
            'hpt_display': a.hpt_display,
            'allergy_type': a.allergy_type,
            'category': a.category,
            'clinical_status': a.clinical_status,
            'clinical_status_display': a.get_clinical_status_display(),
            'criticality': a.criticality,
            'severity': a.severity,
            'reaction': a.reaction,
            'onset_date': a.onset_date.isoformat() if a.onset_date else None,
            'notes': a.notes,
            'is_active': a.is_active,
            'history': [
                {
                    'id': h.pk,
                    'action': h.action,
                    'action_display': h.get_action_display(),
                    'clinical_status': h.clinical_status,
                    'change_summary': h.change_summary,
                    'changed_at': h.changed_at.isoformat() if h.changed_at else None,
                    'changed_by': h.changed_by.get_full_name() if h.changed_by else None,
                }
                for h in a.history.all()[:30]
            ],
        })
    return JsonResponse({'success': True, 'patient_id': patient.pk, 'count': len(rows), 'allergies': rows})


@login_required
def add_family_history(request, patient_pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=405)

    patient = get_object_or_404(Patient, pk=patient_pk)
    from .forms import FamilyHistoryForm
    from .models import FamilyHistory

    form = FamilyHistoryForm(request.POST)
    if not form.is_valid():
        errors = []
        for field, msgs in form.errors.items():
            errors.extend([f'{field}: {m}' for m in msgs])
        return JsonResponse({'success': False, 'error': '; '.join(errors) or 'Invalid data.'})

    row = form.save(commit=False)
    row.patient = patient
    row.recorded_by = request.user
    row.updated_by = request.user
    # If ICD display set without condition text
    if row.icd11_display and not row.condition:
        row.condition = row.icd11_display
    row.save()
    return JsonResponse({'success': True, 'family_history_id': row.pk})


@login_required
def update_family_history(request, pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=405)

    from .forms import FamilyHistoryForm
    from .models import FamilyHistory

    row = get_object_or_404(FamilyHistory, pk=pk)
    form = FamilyHistoryForm(request.POST, instance=row)
    if not form.is_valid():
        errors = []
        for field, msgs in form.errors.items():
            errors.extend([f'{field}: {m}' for m in msgs])
        return JsonResponse({'success': False, 'error': '; '.join(errors) or 'Invalid data.'})

    row = form.save(commit=False)
    row.updated_by = request.user
    if row.icd11_display and (not row.condition or row.condition == form.initial.get('condition')):
        pass
    row.save()
    return JsonResponse({'success': True, 'family_history_id': row.pk})


@login_required
def patient_growth_chart_api(request, patient_pk):
    """JSON growth / BMI series for charting (CWC + triage)."""
    from .bmi_growth import build_growth_series

    patient = get_object_or_404(Patient, pk=patient_pk)
    records = []
    try:
        from maternity.models import CwcGrowthRecord
        records.extend(list(CwcGrowthRecord.objects.filter(patient=patient).order_by('measured_date')[:60]))
    except Exception:  # noqa: BLE001
        pass

    class _TriagePoint:
        def __init__(self, entry):
            self.measured_date = entry.entry_date.date() if entry.entry_date else None
            self.weight_kg = entry.weight
            self.height_cm = entry.height

    for e in TriageEntry.objects.filter(visit__patient=patient).exclude(weight__isnull=True).order_by('entry_date')[:60]:
        records.append(_TriagePoint(e))

    payload = build_growth_series(patient, records)
    payload['success'] = True
    return JsonResponse(payload)


@login_required
def hpt_allergy_search_api(request):
    """GET /home/api/hpt/allergy-search/?q=penicillin — prefer AC* substances."""
    from .medication_registry import search_hpt_allergens

    q = (request.GET.get('q') or request.GET.get('query') or '').strip()
    if len(q) < 2:
        return JsonResponse({
            'success': False,
            'error': 'Enter at least 2 characters.',
            'results': [],
        }, status=400)
    try:
        limit = min(int(request.GET.get('limit') or 25), 50)
    except (TypeError, ValueError):
        limit = 25
    payload = search_hpt_allergens(q, limit=limit)
    status = 200 if payload.get('success') else 502
    return JsonResponse(payload, status=status)


@login_required
def generate_clinical_summary_view(request, visit_id):
    """
    POST: generate Clinical Summary for a visit (human-readable + FHIR).
    Optional care_plan text; optional sync_hie=1 to push to Kenya HIE.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    visit = get_object_or_404(Visit, pk=visit_id)
    if request.user.role not in ('Admin', 'Doctor', 'Nurse'):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    care_plan = (request.POST.get('care_plan') or '').strip()
    sync_hie = request.POST.get('sync_hie', '') in ('1', 'true', 'yes', 'on')

    from .clinical_summary import generate_clinical_summary, sync_clinical_summary_to_hie

    summary = generate_clinical_summary(
        visit, care_plan=care_plan, author=request.user, persist=True,
    )
    sync_result = None
    if sync_hie:
        sync_result = sync_clinical_summary_to_hie(summary)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.POST.get('ajax'):
        return JsonResponse({
            'success': True,
            'summary_id': summary.pk,
            'status': summary.status,
            'hie_sync_status': summary.hie_sync_status,
            'includes': {
                'biodata': summary.includes_biodata,
                'clinical': summary.includes_clinical,
                'medications': summary.includes_medications,
                'prescriptions': summary.includes_prescriptions,
                'care_plan': summary.includes_care_plan,
            },
            'print_url': reverse('home:clinical_summary_print', kwargs={'pk': summary.pk}),
            'view_url': reverse('home:clinical_summary_detail', kwargs={'pk': summary.pk}),
            'sync_result': sync_result,
            'last_error': summary.last_error,
        })

    messages.success(request, f'Clinical Summary #{summary.pk} generated.')
    if sync_hie and summary.hie_sync_status == 'error':
        messages.warning(request, f'HIE sync issue: {summary.last_error[:200]}')
    elif sync_hie and summary.hie_sync_status in ('synced', 'partial'):
        messages.info(request, f'Synced to Kenya HIE ({summary.hie_sync_status}).')
    return redirect('home:clinical_summary_detail', pk=summary.pk)


@login_required
def clinical_summary_detail(request, pk):
    from .models import ClinicalSummary

    summary = get_object_or_404(
        ClinicalSummary.objects.select_related('patient', 'visit', 'generated_by'),
        pk=pk,
    )
    if request.user.role not in ('Admin', 'Doctor', 'Nurse'):
        messages.error(request, 'Permission denied.')
        return redirect('home:patient_detail', pk=summary.patient_id)

    return render(request, 'home/clinical_summary_detail.html', {
        'summary': summary,
        'patient': summary.patient,
        'visit': summary.visit,
        'data': summary.summary_json or {},
    })


@login_required
def clinical_summary_print(request, pk):
    from django.conf import settings as django_settings
    from .models import ClinicalSummary

    summary = get_object_or_404(
        ClinicalSummary.objects.select_related('patient', 'visit', 'generated_by'),
        pk=pk,
    )
    return render(request, 'home/clinical_summary_print.html', {
        'summary': summary,
        'patient': summary.patient,
        'visit': summary.visit,
        'data': summary.summary_json or {},
        'facility_name': (
            (summary.summary_json or {}).get('facility', {}) or {}
        ).get('name') or getattr(django_settings, 'SHA_HIE_FACILITY_NAME', '') or 'Health Facility',
    })


@login_required
def clinical_summary_fhir_json(request, pk):
    from .models import ClinicalSummary

    summary = get_object_or_404(ClinicalSummary, pk=pk)
    if request.user.role not in ('Admin', 'Doctor', 'Nurse'):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    return JsonResponse(summary.fhir_bundle or {}, safe=False)


@login_required
def sync_clinical_summary_view(request, pk):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    from .models import ClinicalSummary
    from .clinical_summary import sync_clinical_summary_to_hie

    summary = get_object_or_404(ClinicalSummary, pk=pk)
    if request.user.role not in ('Admin', 'Doctor'):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    result = sync_clinical_summary_to_hie(summary)
    return JsonResponse({
        'success': summary.hie_sync_status in ('synced', 'partial'),
        'hie_sync_status': summary.hie_sync_status,
        'last_error': summary.last_error,
        'result': result,
        'document_id': summary.hie_document_id,
    })


@login_required
def clinical_decision_support_api(request, patient_pk):
    """
    GET /home/patients/<id>/cds/?visit_id=
    Clinical Decision Support using Problem List, HPT, allergies, demographics, labs, vitals.
    """
    from .clinical_decision_support import evaluate_cds

    patient = get_object_or_404(Patient, pk=patient_pk)
    visit = None
    visit_id = request.GET.get('visit_id')
    if visit_id:
        visit = Visit.objects.filter(pk=visit_id, patient=patient).first()
    payload = evaluate_cds(patient, visit=visit)
    return JsonResponse(payload)


@login_required
@require_http_methods(['POST'])
def cds_check_medication_api(request, patient_pk):
    """
    POST JSON: { name, generic_concept_code, generic_concept_display, actual_product_code, visit_id? }
    Prescribe-time allergy / HPT / CDS check for one medication.
    """
    from .clinical_decision_support import evaluate_cds

    patient = get_object_or_404(Patient, pk=patient_pk)
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    visit = None
    visit_id = body.get('visit_id') or request.GET.get('visit_id')
    if visit_id:
        visit = Visit.objects.filter(pk=visit_id, patient=patient).first()

    proposed = [{
        'name': body.get('name') or '',
        'generic_concept_code': body.get('generic_concept_code') or '',
        'generic_concept_display': body.get('generic_concept_display') or '',
        'actual_product_code': body.get('actual_product_code') or '',
    }]
    payload = evaluate_cds(patient, visit=visit, proposed_medications=proposed)
    allergy_alerts = [
        a for a in payload.get('alerts', [])
        if 'allergy_list' in (a.get('sources') or []) or a.get('blocking')
    ]
    return JsonResponse({
        'success': True,
        'patient_id': patient.pk,
        'blocking': any(a.get('blocking') for a in allergy_alerts),
        'allergy_alerts': allergy_alerts,
        'alerts': payload.get('alerts', []),
        'summary': payload.get('summary', {}),
        'inputs_used': payload.get('inputs_used', {}),
    })


@login_required
def add_tb_screening(request):
    """Save mandatory TB screening data for a visit"""
    if request.method == 'POST':
        try:
            from .forms import TBScreeningForm
            from .models import TBScreening
            
            visit_id = request.POST.get('visit_id')
            visit = get_object_or_404(Visit, pk=visit_id)
            
            # Block if not latest visit
            latest_visit = Visit.objects.filter(patient=visit.patient).order_by('-visit_date').first()
            if visit != latest_visit:
                return JsonResponse({'success': False, 'error': 'Cannot add screening to a previous visit.'})
                
            if not visit.is_active:
                return JsonResponse({'success': False, 'error': 'Cannot add screening to a closed visit.'})

            # Handle existing screening (Update instead of Create if already exists)
            screening = TBScreening.objects.filter(visit=visit).first()
            patient = visit.patient
            show_failure_to_thrive = patient.age is not None and patient.age < 15
            form = TBScreeningForm(
                request.POST,
                instance=screening,
                show_failure_to_thrive=show_failure_to_thrive,
            )
            
            if form.is_valid():
                tb_obj = form.save(commit=False)
                tb_obj.visit = visit
                tb_obj.screened_by = request.user
                if 'failure_to_thrive' not in form.cleaned_data:
                    tb_obj.failure_to_thrive = False
                tb_obj.save()
                return JsonResponse({'success': True})
            else:
                errors = []
                for field, msgs in form.errors.items():
                    label = form.fields.get(field)
                    name = label.label if label else field.replace('_', ' ').title()
                    errors.append(f'{name}: select Yes or No')
                return JsonResponse({
                    'success': False,
                    'error': errors[0] if len(errors) == 1 else 'Please select Yes or No for every symptom.',
                })
                
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def update_consultation_note(request, pk):
    """Update an existing consultation note"""
    if request.user.role != 'Doctor':
        return JsonResponse({'success': False, 'error': 'Only doctors can edit clinical notes.'})
    if request.method == 'POST':
        try:
            note = get_object_or_404(ConsultationNotes, pk=pk)
            visit = note.consultation.visit

            latest_visit = Visit.objects.filter(patient=visit.patient).order_by('-visit_date').first()
            if visit != latest_visit:
                return JsonResponse({'success': False, 'error': 'Cannot edit notes on a previous visit.'})
            if not visit.is_active:
                return JsonResponse({'success': False, 'error': 'Cannot edit notes on a closed visit.'})

            from .clinical_gates import doctor_requires_tb_screening, TB_SCREENING_MESSAGE
            if doctor_requires_tb_screening(request.user, visit):
                return JsonResponse({'success': False, 'error': TB_SCREENING_MESSAGE})

            note_content = request.POST.get('note_content')
            note_type_detail = request.POST.get('note_type_detail', '').strip()
            if note_type_detail:
                note_content = f"{note_content}\n\nFocus Area: {note_type_detail}"

            note.notes = note_content
            note.updated_by = request.user
            note.save()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def create_triage_entry(request):
    """Create a new triage entry from the modal form"""
    if request.method == 'POST':
        try:
            # Get form data
            visit_id = request.POST.get('visit_id')
            category = request.POST.get('category')
            priority = request.POST.get('priority')
            temperature = request.POST.get('temperature')
            blood_pressure_systolic = request.POST.get('blood_pressure_systolic')
            blood_pressure_diastolic = request.POST.get('blood_pressure_diastolic')
            heart_rate = request.POST.get('heart_rate')
            respiratory_rate = request.POST.get('respiratory_rate')
            oxygen_saturation = request.POST.get('oxygen_saturation')
            blood_glucose = request.POST.get('blood_glucose')
            weight = request.POST.get('weight')
            height = request.POST.get('height')
            disposition = request.POST.get('disposition', '') # Default to empty string
            triage_notes = request.POST.get('triage_notes')
            
            # Validate required fields (including User requested compulsory fields)
            if not visit_id or not category or not priority:
                return JsonResponse({'success': False, 'error': 'Missing required fields'})
                
            # Compulsory clinical fields check
            if not blood_pressure_systolic or not blood_pressure_diastolic:
                return JsonResponse({'success': False, 'error': 'Blood Pressure is required'})
            if not weight:
                return JsonResponse({'success': False, 'error': 'Weight is required'})
            if not height:
                return JsonResponse({'success': False, 'error': 'Height is required'})
            if not oxygen_saturation:
                return JsonResponse({'success': False, 'error': 'Oxygen Saturation is required'})

            # Get visit
            visit = get_object_or_404(Visit, pk=visit_id)
            
            # Create triage entry
            triage_entry = TriageEntry.objects.create(
                visit=visit,
                triage_nurse=request.user,
                category=category,
                priority=priority,
                temperature=float(temperature) if temperature else None,
                blood_pressure_systolic=int(blood_pressure_systolic) if blood_pressure_systolic else None,
                blood_pressure_diastolic=int(blood_pressure_diastolic) if blood_pressure_diastolic else None,
                # Removed heart_rate, respiratory_rate, blood_glucose as requested
                oxygen_saturation=int(oxygen_saturation) if oxygen_saturation else None,
                weight=float(weight) if weight else None,
                height=float(height) if height else None,
                disposition=disposition,
                triage_notes=triage_notes or ''
            )
            
            # Handle Patient Queueing to Consultation Room
            send_to = request.POST.get('send_to')
            if send_to:
                # Determine department name and abbreviation
                if send_to == "Maternity":
                    dept_name = "Maternity"
                    dept_abbr = "MAT"
                elif send_to.isdigit():
                    dept_name = f'Consultation Room {send_to}'
                    dept_abbr = f'CR{send_to}'
                else:
                    dept_name = send_to
                    dept_abbr = send_to[:10].upper()

                # Create or get triage department for queueing logic
                triage_dept, _ = Departments.objects.get_or_create(
                    name='Triage',
                    defaults={'abbreviation': 'TRI'}
                )

                # Create or get consultation room department
                consultation_room, _ = Departments.objects.get_or_create(
                    name=dept_name,
                    defaults={'abbreviation': dept_abbr}
                )
                
                # Mark the Triage entry as COMPLETED
                PatientQue.objects.filter(
                    visit=visit,
                    sent_to=triage_dept,
                    status='PENDING'
                ).update(status='COMPLETED')
                
                PatientQue.objects.create(
                    visit=visit,
                    qued_from=triage_dept,
                    sent_to=consultation_room,
                    created_by=request.user,
                    status='PENDING',
                    queue_type='INITIAL'
                )
            
            return JsonResponse({'success': True, 'message': 'Triage entry created successfully'})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
def check_active_visit(request):
    """Check if patient has an active visit and return unpaid invoice info."""
    patient_id = request.GET.get('patient_id')
    if not patient_id:
        return JsonResponse({'has_active': False})

    active_visits = Visit.objects.filter(patient_id=patient_id, is_active=True)
    if not active_visits.exists():
        return JsonResponse({'has_active': False})

    from accounts.models import Invoice
    unpaid_total = 0
    total_invoiced = 0
    total_paid = 0
    visit_details = []
    for v in active_visits:
        detail = {
            'visit_id': v.pk,
            'visit_type': v.visit_type,
            'visit_date': v.visit_date.strftime('%d %b %Y, %H:%M'),
            'invoice_id': None,
            'invoice_total': 0,
            'paid_amount': 0,
            'balance': 0,
        }
        try:
            inv = v.invoice
            if inv:
                detail['invoice_id'] = inv.pk
                detail['invoice_total'] = float(inv.total_amount)
                detail['paid_amount'] = float(inv.paid_amount)
                detail['balance'] = float(inv.balance)
                total_invoiced += float(inv.total_amount)
                total_paid += float(inv.paid_amount)
                if inv.balance > 0:
                    unpaid_total += float(inv.balance)
        except Exception:
            pass
        visit_details.append(detail)

    return JsonResponse({
        'has_active': True,
        'active_count': active_visits.count(),
        'total_invoiced': total_invoiced,
        'total_paid': total_paid,
        'unpaid_total': unpaid_total,
        'visits': visit_details,
    })


@login_required
def admit_patient_visit(request):
    """
    Admit a patient (create a Visit) and add to a Queue.
    OPD Consultation → Triage (with billing)
    MCH → MCH department (free, no triage)
    """
    if request.method == 'POST':
        try:
            from accounts.models import Invoice, InvoiceItem
            from django.utils import timezone
            from accounts.utils import get_or_create_invoice

            patient_id = request.POST.get('patient_id')
            consultation_id = request.POST.get('consultation_id')
            payment_method = request.POST.get('payment_method', 'Cash')
            patient_payment_method = request.POST.get('patient_payment_method', 'Cash')

            # OPD Billing Flags
            bill_opd_book = request.POST.get('bill_opd_book') == 'true'
            bill_opd_consult = request.POST.get('bill_opd_consultation') == 'true'

            patient = get_object_or_404(Patient, pk=patient_id)
            main_service = get_object_or_404(Service, pk=consultation_id)

            # Close any previous active visits
            active_visits = Visit.objects.filter(patient=patient, is_active=True)
            for old_visit in active_visits:
                old_visit.is_active = False
                old_visit.save(update_fields=['is_active'])
                
                if old_visit.visit_type == 'IN-PATIENT':
                    from inpatient.models import Admission
                    active_admissions = Admission.objects.filter(visit=old_visit, status='Admitted')
                    for admission in active_admissions:
                        admission.status = 'Discharged'
                        admission.discharged_at = timezone.now()
                        admission.discharged_by = request.user
                        admission.save()

            service_name_upper = main_service.name.upper()
            is_mch = 'MCH' in service_name_upper

            # Create visit
            visit = Visit.objects.create(
                patient=patient,
                visit_type='OUT-PATIENT',
                visit_mode='Walk In',
                payment_method='SHA' if payment_method == 'Insurance' else 'CASH',
                by_nurse=_is_nurse_user(request.user),
            )

            # Departments
            reception_dept, _ = Departments.objects.get_or_create(
                name='Reception', defaults={'abbreviation': 'REC'}
            )

            # --- Routing ---
            if is_mch:
                # MCH → MCH department directly (they have their own triage)
                destination_dept, _ = Departments.objects.get_or_create(
                    name='MCH', defaults={'abbreviation': 'MCH'}
                )
                billing_msg = " (MCH - Free Visit)"
            else:
                # OPD Consultation → Triage
                destination_dept, _ = Departments.objects.get_or_create(
                    name='Triage', defaults={'abbreviation': 'TRI'}
                )

                # --- Billing for OPD ---
                if payment_method == 'Free Visit':
                    billing_msg = " (Free Revisit)"
                else:
                    invoice = get_or_create_invoice(visit=visit, user=request.user)

                    # Bill OPD Book if checked
                    if bill_opd_book:
                        opd_book_service = Service.objects.filter(
                            name__icontains='OPD Book', is_active=True
                        ).first()
                        if opd_book_service:
                            InvoiceItem.objects.create(
                                invoice=invoice,
                                service=opd_book_service,
                                name=opd_book_service.name,
                                unit_price=opd_book_service.price,
                                quantity=1
                            )

                    # Bill OPD Consultation if checked
                    if bill_opd_consult:
                        unit_price = 300 if payment_method == 'Insurance' else 100
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            service=main_service,
                            name=main_service.name,
                            unit_price=unit_price,
                            quantity=1
                        )

                    # --- Payments ---
                    invoice.refresh_from_db()
                    if invoice.total_amount > 0:
                        if payment_method == 'Insurance':
                            # Insurance covers up to 300
                            insurance_amount = min(invoice.total_amount, 300)
                            Payment.objects.create(
                                invoice=invoice,
                                amount=insurance_amount,
                                payment_method='Insurance',
                                notes='Automated insurance portion (SHA)',
                                created_by=request.user
                            )
                            remaining = invoice.total_amount - insurance_amount
                            if remaining > 0:
                                Payment.objects.create(
                                    invoice=invoice,
                                    amount=remaining,
                                    payment_method=patient_payment_method,
                                    notes='Patient portion (Book/Co-pay)',
                                    created_by=request.user
                                )
                        else:
                            # Cash/M-Pesa full payment
                            Payment.objects.create(
                                invoice=invoice,
                                amount=invoice.total_amount,
                                payment_method=payment_method,
                                notes='Automated payment at admission',
                                created_by=request.user
                            )

                    billing_msg = " (Billed & Paid)"

            # --- Queue patient ---
            PatientQue.objects.create(
                visit=visit,
                qued_from=reception_dept,
                sent_to=destination_dept,
                created_by=request.user
            )

            return JsonResponse({
                'success': True,
                'message': f'Patient {patient.full_name} admitted for {main_service.name}{billing_msg}.'
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})



# Prescription Views
@login_required
def create_prescription(request, visit_id):
    """Create a new prescription for a patient linked to a specific visit"""
    allowed_roles = ['Doctor', 'Nurse']
    if request.user.role not in allowed_roles:
        messages.error(request, f"Only {', '.join(allowed_roles)} can create prescriptions.")
        # We need to find the patient first to redirect, or just redirect to dashboard
        visit = get_object_or_404(Visit, pk=visit_id)
        return redirect('home:patient_detail', pk=visit.patient.id)
    
    from django.forms import inlineformset_factory
    from django.db import transaction
    import uuid
    from .forms import PrescriptionForm, PrescriptionItemForm
    from .prescription_utils import (
        cache_prescription_submit,
        get_cached_prescription_id,
        get_or_create_visit_prescription,
        try_acquire_prescription_submit_lock,
        release_prescription_submit_lock,
    )
    from accounts.utils import get_or_create_invoice
    from accounts.models import InvoiceItem
    visit = get_object_or_404(Visit, pk=visit_id)
    patient = visit.patient
    
    # Block if not latest visit or if visit is not active
    latest_visit = Visit.objects.filter(patient=patient).order_by('-visit_date').first()
    
    if visit != latest_visit:
        messages.error(request, "Cannot create prescriptions for a previous visit.")
        return redirect('home:patient_detail', pk=patient.id)
        
    if not visit.is_active:
        messages.error(request, f"Visit for {patient.full_name} is already closed. Please create a new visit to prescribe medications.")
        return redirect('home:patient_detail', pk=patient.id)

    from .clinical_gates import doctor_requires_tb_screening, TB_SCREENING_MESSAGE
    if doctor_requires_tb_screening(request.user, visit):
        messages.warning(request, TB_SCREENING_MESSAGE)
        return redirect(f"{reverse('home:patient_detail', kwargs={'pk': patient.pk})}?visit_id={visit.pk}#visits")
    
    # Block prescription creation for IPD visits — use MedicationChart via case folder instead
    from inpatient.models import Admission
    active_admission = Admission.objects.filter(visit=visit, status='Admitted').first()
    if active_admission:
        messages.warning(
            request,
            f"{patient.full_name} is an admitted inpatient. "
            "Please prescribe medications from the Inpatient Case Folder instead."
        )
        return redirect('inpatient:patient_case_folder', admission_id=active_admission.id)
    
    # Create formset for prescription items (medications)
    PrescriptionItemFormSet = inlineformset_factory(
        Prescription,
        PrescriptionItem,
        form=PrescriptionItemForm,
        extra=1,  # Single add widget; more rows added via JS
        can_delete=True
    )
    
    form_token = ''
    if request.method == 'POST':
        form_token = request.POST.get('form_token', '').strip()
        cached_id = get_cached_prescription_id(visit_id, form_token)
        if cached_id:
            messages.info(request, 'Prescription already saved.')
            return redirect('home:prescription_detail', prescription_id=cached_id)

        form = PrescriptionForm(request.POST)
        formset = PrescriptionItemFormSet(request.POST, prefix='items')
        
        if form.is_valid() and formset.is_valid():
            from .clinical_decision_support import evaluate_cds

            # SHA visit terminology guard: all prescribed medications must exist in DHA Terminology
            is_sha_visit = (visit.payment_method or '').upper() in ('SHA', 'SHIF', 'INSURANCE') or bool(getattr(visit, 'sha_claim_session', None))
            sha_unmapped_items = []
            if is_sha_visit:
                for item_form in formset.forms:
                    if not hasattr(item_form, 'cleaned_data') or item_form.cleaned_data.get('DELETE'):
                        continue
                    med = item_form.cleaned_data.get('medication')
                    if not med:
                        continue
                    dha_code = (
                        item_form.cleaned_data.get('generic_concept_code')
                        or getattr(getattr(med, 'medication', None), 'generic_concept_code', '')
                        or ''
                    ).strip()
                    if not dha_code:
                        sha_unmapped_items.append(getattr(med, 'name', 'Medication'))

            if sha_unmapped_items:
                for unmapped_name in sha_unmapped_items:
                    messages.error(
                        request,
                        f'SHA Prescribing Error: "{unmapped_name}" does not exist in DHA Terminology (missing GE* code). Under SHA rules, this drug cannot be prescribed for SHA visits.',
                    )
            else:
                proposed = []
                for item_form in formset.forms:
                    if not hasattr(item_form, 'cleaned_data') or item_form.cleaned_data.get('DELETE'):
                        continue
                    med = item_form.cleaned_data.get('medication')
                    if not med:
                        continue
                    proposed.append({
                        'name': getattr(med, 'name', '') or '',
                        'generic_concept_code': item_form.cleaned_data.get('generic_concept_code') or '',
                        'generic_concept_display': item_form.cleaned_data.get('generic_concept_display') or '',
                        'actual_product_code': '',
                    })

                blockers = []
                if proposed:
                    cds_check = evaluate_cds(patient, visit=visit, proposed_medications=proposed)
                    blockers = [a for a in cds_check.get('alerts', []) if a.get('blocking')]

                if blockers and request.POST.get('cds_override') != '1':
                    for b in blockers[:5]:
                        messages.error(request, f"CDS block: {b.get('title')} — {b.get('message')}")
                    messages.warning(
                        request,
                        'Prescription blocked by Clinical Decision Support (allergy/safety). '
                        'Resolve conflicts or obtain clinical override.',
                    )
                else:
                    if blockers and request.POST.get('cds_override') == '1':
                        messages.warning(request, 'CDS allergy block overridden by clinician.')

                    submission_in_progress = False
                if form_token and not try_acquire_prescription_submit_lock(visit_id, form_token):
                    cached_id = get_cached_prescription_id(visit_id, form_token)
                    if cached_id:
                        messages.info(request, 'Prescription already saved.')
                        return redirect('home:prescription_detail', prescription_id=cached_id)
                    submission_in_progress = True
                    messages.warning(
                        request,
                        'This prescription is already being saved. Please wait a moment.',
                    )

                if not submission_in_progress:
                    try:
                        with transaction.atomic():
                            locked_visit = Visit.objects.select_for_update().get(pk=visit_id)
                            cached_id = get_cached_prescription_id(visit_id, form_token)
                            if cached_id:
                                messages.info(request, 'Prescription already saved.')
                                return redirect('home:prescription_detail', prescription_id=cached_id)

                            prescription, _created = get_or_create_visit_prescription(
                                locked_visit,
                                patient,
                                request.user,
                                diagnosis=form.cleaned_data['diagnosis'],
                                notes=form.cleaned_data.get('notes', ''),
                            )

                            if request.POST.get('action') == 'prescribe_close':
                                locked_visit.is_active = False
                                locked_visit.save(update_fields=['is_active'])
                                messages.info(request, "Visit has been closed.")

                            formset = PrescriptionItemFormSet(request.POST, instance=prescription, prefix='items')
                            formset.is_valid()
                            prescription_items = formset.save()

                        if prescription_items:
                            invoice = get_or_create_invoice(visit=prescription.visit, user=request.user)

                            new_notes = f"\nPrescription meds added: {', '.join([item.medication.name for item in prescription_items])}"
                            if invoice.notes:
                                invoice.notes += new_notes
                            else:
                                invoice.notes = new_notes.strip()
                            invoice.save()

                            prescription.invoice = invoice
                            prescription.save(update_fields=['invoice'])

                            for item in prescription_items:
                                if item.medication.selling_price > 0:
                                    InvoiceItem.objects.create(
                                        invoice=invoice,
                                        inventory_item=item.medication,
                                        name=item.medication.name,
                                        unit_price=item.medication.selling_price,
                                        quantity=item.quantity
                                    )

                            invoice.update_totals()
                            if invoice.total_amount == 0 and invoice.status != 'Paid':
                                invoice.status = 'Paid'
                                invoice.save()

                            try:
                                from accounts.sha_preauth_check import check_inventory_preauth

                                meds = [item.medication for item in prescription_items]
                                preauth_meds = check_inventory_preauth(prescription.visit, meds)
                                needing = list(preauth_meds.get('inform_patient') or [])

                                for row in needing:
                                    messages.warning(request, row.get('message') or 'SHA preauth required.')
                                if needing:
                                    messages.info(
                                        request,
                                        'Inform the patient: some prescribed items require SHA pre-authorization '
                                        'before SHA payment is guaranteed. Use the SHA claims desk to raise preauth.',
                                    )
                            except Exception:
                                pass

                        cache_prescription_submit(visit_id, form_token, prescription.id)
                        try:
                            from .medication_registry import sync_active_medications_from_prescription
                            synced = sync_active_medications_from_prescription(
                                prescription, user=request.user,
                            )
                            if synced:
                                messages.info(
                                    request,
                                    f'Active Medication List updated ({synced} item(s)). '
                                    'Review on the patient profile → Active Medications.',
                                )
                        except Exception:
                            pass
                        try:
                            from .electronic_prescribing import (
                                attach_clinical_context_to_prescription,
                                parse_id_list,
                            )
                            problem_ids = parse_id_list(request.POST.getlist('erx_problem_ids'))
                            include_meds = request.POST.get('erx_include_medication_list', '1') in (
                                '1', 'true', 'yes', 'on',
                            )
                            ctx = attach_clinical_context_to_prescription(
                                prescription,
                                problem_ids=problem_ids or None,
                                include_medication_list=include_meds,
                                diagnostic_service_ids=None,
                                order_diagnostics=False,
                                user=request.user,
                            )
                            bits = []
                            if ctx.get('includes', {}).get('problem_list'):
                                bits.append('Problem List')
                            if ctx.get('includes', {}).get('medication_list'):
                                bits.append('Medication List')
                            if bits:
                                messages.info(
                                    request,
                                    'eRx package includes: ' + ', '.join(bits) + '.',
                                )
                        except Exception:
                            pass
                        if request.POST.get('transmit_erx') in ('1', 'true', 'yes', 'on'):
                            try:
                                from accounts.sha_claims_service import (
                                    get_or_create_claim_session,
                                    submit_erx_for_visit,
                                )
                                session = get_or_create_claim_session(visit, user=request.user)
                                if session.consent_token:
                                    submit_erx_for_visit(session, practitioner=request.user)
                                    messages.success(request, 'Prescription transmitted electronically to SHA eRx.')
                                else:
                                    messages.warning(
                                        request,
                                        'Saved locally. Start SHA visit (OTP/consent) on Claims Desk before electronic transmission.',
                                    )
                            except Exception as exc:
                                messages.warning(request, f'Local Rx saved; eRx transmit deferred: {exc}')
                        if prescription_items:
                            messages.success(request, f'Prescription processed successfully for {patient.full_name}')
                        else:
                            messages.success(request, f'Prescription saved successfully for {patient.full_name}')
                        return redirect('home:prescription_detail', prescription_id=prescription.id)
                    finally:
                        if form_token and not get_cached_prescription_id(visit_id, form_token):
                            release_prescription_submit_lock(visit_id, form_token)

    else:
        from .models import Diagnosis
        visit_diagnosis = (
            Diagnosis.objects.filter(visit=visit)
            .order_by('-created_at')
            .values_list('data', flat=True)
            .first()
        )
        initial = {'diagnosis': visit_diagnosis} if visit_diagnosis else {}
        form = PrescriptionForm(initial=initial)
        formset = PrescriptionItemFormSet(prefix='items')
        form_token = str(uuid.uuid4())
    
    existing_prescription = (
        Prescription.objects.filter(visit=visit)
        .exclude(status='Cancelled')
        .order_by('-prescribed_at')
        .first()
    )
    # Prepare medication metadata for JS
    from inventory.models import InventoryItem, InventoryCategory
    import json
    
    # Get Pharmaceuticals category
    pharma_category = InventoryCategory.objects.filter(name__icontains='Pharmaceutical').first()
    
    if pharma_category:
        medications = InventoryItem.objects.filter(category=pharma_category).select_related('category')
    else:
        medications = InventoryItem.objects.all().select_related('category')
    
    # Prepare stock logic
    from django.db.models import Sum, Q 
    from inventory.models import StockRecord

    # Determine eligible departments for stock check
    if request.user.role == 'Nurse':
        departments = ['Mini Pharmacy']

    else:
        departments = ['Pharmacy']
    
    med_metadata = {}
    for item in medications:
        details = getattr(item, 'medication', None)
        
        # Calculate stock
        total_stock = StockRecord.objects.filter(
            item=item,
            current_location__name__in=departments
        ).aggregate(quantity__sum=Sum('quantity'))['quantity__sum'] or 0

        med_metadata[item.id] = {
            'name': item.name,
            'generic_name': details.generic_name if details else '',
            'formulation': details.formulation if details else '',
            'drug_class': details.drug_class.name if details and details.drug_class else '',
            'strength_amount': details.strength_amount if details else '',
            'strength_unit': details.strength_unit if details else '',
            'generic_concept_code': details.generic_concept_code if details else '',
            'generic_concept_display': details.generic_concept_display if details else '',
            'is_dha_mapped': bool(details and details.generic_concept_code),
            'is_dispensed_as_whole': item.is_dispensed_as_whole,
            'dispensing_unit': item.dispensing_unit,
            'selling_price': str(item.selling_price),
            'stock_quantity': total_stock,
            'visit_type': visit.visit_type,
            'sha_intervention_code': getattr(item, 'sha_intervention_code', None) or '',
        }

    from django.conf import settings as django_settings
    from .clinical_decision_support import evaluate_cds
    from .models import PatientAllergy as _PatientAllergy

    cds_payload = evaluate_cds(patient, visit=visit)
    from .knhts_conditions import ACTIVE_CLINICAL_STATUSES
    from .models import PatientMedication, Problem
    from accounts.models import Service as AccService
    from lab.models import LabResult as LabResultModel

    active_problems = list(
        Problem.objects.filter(patient=patient)
        .exclude(verification_status='entered-in-error')
        .filter(clinical_status__in=ACTIVE_CLINICAL_STATUSES)
        .order_by('-updated_at')[:30]
    )
    active_meds = list(
        PatientMedication.objects.filter(patient=patient, status='active').order_by('-updated_at')[:30]
    )
    diagnostic_catalog = list(
        AccService.objects.filter(
            is_active=True,
            department__isnull=False,
        ).filter(
            Q(department__name__icontains='Lab')
            | Q(department__name__icontains='Imag')
            | Q(department__name__icontains='Radiol')
            | Q(department__name__icontains='Proced')
        ).select_related('department').order_by('department__name', 'name')[:120]
    )
    if not diagnostic_catalog:
        diagnostic_catalog = list(
            AccService.objects.filter(is_active=True, department__isnull=False)
            .select_related('department').order_by('department__name', 'name')[:80]
        )
    visit_labs = list(
        LabResultModel.objects.filter(invoice__visit=visit)
        .select_related('service', 'service__department')
        .order_by('-requested_at')[:40]
    )
    sha_session = None
    try:
        sha_session = visit.sha_claim_session
    except Exception:
        sha_session = None

    context = {
        'form': form,
        'formset': formset,
        'patient': patient,
        'visit': visit,
        'form_token': form_token,
        'existing_prescription': existing_prescription,
        'med_metadata_json': json.dumps(med_metadata),
        'hpt_suggest_enabled': getattr(django_settings, 'HPT_DHA_SUGGEST_ON_SELECT', True),
        'hpt_require_code': getattr(django_settings, 'HPT_DHA_REQUIRE_CODE', False),
        'cds': cds_payload,
        'cds_check_url': reverse('home:cds_check_medication', kwargs={'patient_pk': patient.pk}),
        'active_patient_allergies': list(
            _PatientAllergy.objects.filter(patient=patient, clinical_status='active')[:30]
        ),
        'erx_active_problems': active_problems,
        'erx_active_medications': active_meds,
        'erx_diagnostic_catalog': diagnostic_catalog,
        'erx_visit_labs': visit_labs,
        'sha_claim_ready': bool(sha_session and sha_session.consent_token),
        'sha_preauth_check_url': reverse('home:sha_preauth_check_api'),
        'sha_visit_billed': bool(
            (visit.payment_method or '').upper() in ('SHA', 'INSURANCE', 'SHIF', 'UHC')
            or sha_session
        ),
        'dispensed_items': _get_normalized_history(visit, patient),
        'dispensing_departments': Departments.objects.all().order_by('name')
    }
    return render(request, 'home/create_prescription.html', context)

def _get_normalized_history(visit, patient):
    from inventory.models import DispensedItem
    from inventory.consumable_utils import is_pharmaceutical_item
    from accounts.models import InvoiceItem
    from inpatient.models import MedicationChart, InpatientConsumable
    
    if not visit:
        return []

    # 1. Fetch physical dispensations (Stock deducted)
    d_items = DispensedItem.objects.filter(visit=visit).select_related(
        'item', 'item__category', 'dispensed_by',
    ).order_by('-dispensed_at')
    
    # 2. Fetch billed items (Requested by doctor but might not be dispensed yet)
    billed_items = InvoiceItem.objects.filter(
        invoice__visit=visit,
        inventory_item__isnull=False,
    ).select_related('inventory_item', 'inventory_item__category', 'invoice__created_by').order_by('-created_at')

    # 3. Fetch IPD consumable requests (not yet dispensed) — skip MedicationChart (drugs)
    ipd_consumables = InpatientConsumable.objects.filter(
        admission__visit=visit,
        is_dispensed=False,
    ).select_related('item', 'item__category', 'prescribed_by').order_by('-prescribed_at')
        
    # 4. Combine and Normalize with De-duplication (consumables only — no pharmaceuticals)
    history = []
    
    # Track dispensed items to suppress corresponding requests
    # Frequency map: (item_id, quantity) -> count
    dispensed_counts = {}
    for d in d_items:
        if is_pharmaceutical_item(d.item):
            continue
        key = (d.item.id, d.quantity)
        dispensed_counts[key] = dispensed_counts.get(key, 0) + 1
        
        history.append({
            'item_name': d.item.name,
            'quantity': d.quantity,
            'at': d.dispensed_at,
            'by': d.dispensed_by,
            'status': 'Dispensed',
            'status_class': 'bg-emerald-50 text-emerald-700'
        })
        
    # Add billed items (Requests) - Suppress if already dispensed
    for b in billed_items:
        if is_pharmaceutical_item(b.inventory_item):
            continue
        key = (b.inventory_item.id, b.quantity)
        if dispensed_counts.get(key, 0) > 0:
            dispensed_counts[key] -= 1
            continue
            
        # Use b.name because it might contain "(from Dept)" info
        history.append({
            'item_name': b.name if b.name else b.inventory_item.name,
            'quantity': b.quantity,
            'at': b.created_at,
            'by': b.invoice.created_by if b.invoice else b.created_by,
            'status': 'Billed/Pending',
            'status_class': 'bg-amber-50 text-amber-700'
        })

    # Add IPD Consumables (non-pharmaceutical only)
    for c in ipd_consumables:
        if is_pharmaceutical_item(c.item):
            continue
        key = (c.item.id, c.quantity)
        if dispensed_counts.get(key, 0) > 0:
            dispensed_counts[key] -= 1
            continue

        history.append({
            'item_name': c.item.name,
            'quantity': c.quantity,
            'at': c.prescribed_at,
            'by': c.prescribed_by,
            'status': 'Requested',
            'status_class': 'bg-amber-50 text-amber-700'
        })
    
    # Sort combined history by timestamp
    history.sort(key=lambda x: x['at'], reverse=True)
    return history[:30]

@login_required
def health_records_view(request):
    """
    Health Records Registry View.
    Supports robust filtering for Visits and Patients.
    """
    # Simple role check for now (Admin, Receptionist, Doctor, Nurse, Triage Nurse)
    # Adding Health Records access logic
    allowed_roles = ['Admin', 'Receptionist', 'Doctor', 'Nurse', 'Triage Nurse', 'Health Records']
    if request.user.role not in allowed_roles and not request.user.is_superuser:
        messages.error(request, "Access denied. Health Records permission required.")
        return redirect('home:reception_dashboard')

    from django.db.models import Q
    from django.core.paginator import Paginator
    
    # Start with all visits
    visits = Visit.objects.select_related('patient').all().order_by('-visit_date')
    
    has_filters = False
    
    # 1. Search (Name, ID, Phone)
    search_query = request.GET.get('search', '')
    if search_query:
        has_filters = True
        visits = visits.filter(
            Q(patient__first_name__icontains=search_query) |
            Q(patient__last_name__icontains=search_query) |
            Q(patient__id_number__icontains=search_query) |
            Q(patient__phone__icontains=search_query)
        )
        
    # 2. Visit Type
    visit_type = request.GET.get('visit_type')
    if visit_type and visit_type != 'all':
        has_filters = True
        visits = visits.filter(visit_type=visit_type)
        
    # 3. Gender (KNHTS administrative-gender codes; accept legacy M/F)
    gender = request.GET.get('gender')
    if gender and gender != 'all':
        has_filters = True
        from .knhts_demographics import map_gender_to_knhts
        visits = visits.filter(patient__gender=map_gender_to_knhts(gender))
        
    # 4. Dates
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date:
        has_filters = True
        visits = visits.filter(visit_date__date__gte=start_date)
    if end_date:
        has_filters = True
        visits = visits.filter(visit_date__date__lte=end_date)
        
    # 5. Age
    # Note: Age is stored as an integer, but it's calculated on save. 
    # This filter relies on the persisted 'age' field being accurate.
    min_age = request.GET.get('min_age')
    max_age = request.GET.get('max_age')
    if min_age:
        has_filters = True
        visits = visits.filter(patient__age__gte=min_age)
    if max_age:
        has_filters = True
        visits = visits.filter(patient__age__lte=max_age)

    # Simple Pagination
    paginator = Paginator(visits, 20) # 20 per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Preserve query params for pagination links
    query_string = request.GET.copy()
    if 'page' in query_string:
        del query_string['page']
    query_string = '&' + query_string.urlencode() if query_string else ''

    context = {
        'visits': page_obj,
        'has_filters': has_filters,
        'query_string': query_string
    }
    return render(request, 'home/health_records.html', context)


@login_required
def prescription_detail(request, prescription_id):
    """View prescription details"""
    from .models import Prescription

    prescription = get_object_or_404(
        Prescription.objects.select_related('patient', 'visit', 'prescribed_by'),
        pk=prescription_id,
    )
    sha_ready = False
    if prescription.visit_id:
        try:
            session = prescription.visit.sha_claim_session
            sha_ready = bool(session and session.consent_token)
        except Exception:
            sha_ready = False

    context = {
        'prescription': prescription,
        'patient': prescription.patient,
        'sha_claim_ready': sha_ready,
        'erx_problems': prescription.problem_list_snapshot or [],
        'erx_medications': prescription.medication_list_snapshot or [],
        'erx_diagnostics': prescription.diagnostic_tests_snapshot or [],
    }
    return render(request, 'home/prescription_detail.html', context)


@login_required
def transmit_prescription_erx(request, prescription_id):
    """Electronically transmit visit prescription package to SHA eRx."""
    if request.method != 'POST':
        return redirect('home:prescription_detail', prescription_id=prescription_id)

    from .models import Prescription
    from accounts.sha_claims_service import get_or_create_claim_session, submit_erx_for_visit
    from .electronic_prescribing import attach_clinical_context_to_prescription

    prescription = get_object_or_404(Prescription, pk=prescription_id)
    if request.user.role not in ('Doctor', 'Admin', 'Pharmacist') and not request.user.is_superuser:
        messages.error(request, 'Permission denied.')
        return redirect('home:prescription_detail', prescription_id=prescription.id)

    if not prescription.visit_id:
        messages.error(request, 'Prescription has no visit — cannot transmit.')
        return redirect('home:prescription_detail', prescription_id=prescription.id)

    # Refresh clinical context if empty
    if not prescription.erx_clinical_context:
        attach_clinical_context_to_prescription(
            prescription,
            include_medication_list=True,
            order_diagnostics=False,
            user=request.user,
        )

    try:
        session = get_or_create_claim_session(prescription.visit, user=request.user)
        if not session.consent_token:
            messages.warning(
                request,
                'Start the SHA visit on Claims Desk (OTP → consent) before electronic transmission.',
            )
            return redirect('accounts:sha_claims_desk', visit_id=prescription.visit_id)
        submit_erx_for_visit(session, practitioner=request.user)
        messages.success(request, 'Electronic prescription transmitted to SHA eRx.')
    except Exception as exc:
        messages.error(request, f'eRx transmission failed: {exc}')

    return redirect('home:prescription_detail', prescription_id=prescription.id)


@login_required
def edit_prescription(request, prescription_id):
    """Edit an existing prescription"""
    prescription = get_object_or_404(Prescription, pk=prescription_id)
    patient = prescription.patient
    visit = prescription.visit

    # Role-based access control
    allowed_roles = ['Doctor', 'Nurse', 'Pharmacist', 'Admin']
    if request.user.role not in allowed_roles and not request.user.is_superuser:
        messages.error(request, "Access denied. You do not have permission to edit prescriptions.")
        return redirect('home:prescription_detail', prescription_id=prescription.id)

    if visit:
        from .clinical_gates import doctor_requires_tb_screening, TB_SCREENING_MESSAGE
        if doctor_requires_tb_screening(request.user, visit):
            messages.warning(request, TB_SCREENING_MESSAGE)
            return redirect(f"{reverse('home:patient_detail', kwargs={'pk': patient.pk})}?visit_id={visit.pk}#visits")

    from django.forms import inlineformset_factory
    from django.db import transaction
    import uuid
    from .forms import PrescriptionForm, PrescriptionItemForm
    from .prescription_utils import (
        cache_prescription_edit,
        get_cached_edit_prescription_id,
        try_acquire_prescription_edit_lock,
        release_prescription_edit_lock,
    )
    from accounts.utils import get_or_create_invoice
    from accounts.models import InvoiceItem, PatientCredit
    from decimal import Decimal

    # Create formset for prescription items (medications)
    PrescriptionItemFormSet = inlineformset_factory(
        Prescription,
        PrescriptionItem,
        form=PrescriptionItemForm,
        extra=1,
        can_delete=True
    )
    form_token = ''
    if request.method == 'POST':
        form_token = request.POST.get('form_token', '').strip()
        cached_id = get_cached_edit_prescription_id(prescription_id, form_token)
        if cached_id:
            messages.info(request, 'Prescription changes were already saved.')
            return redirect('home:prescription_detail', prescription_id=cached_id)

        invoice = None
        old_paid_amount = Decimal('0')
        if prescription.visit:
            invoice = get_or_create_invoice(visit=prescription.visit, user=request.user)
            old_paid_amount = invoice.paid_amount

        form = PrescriptionForm(request.POST, instance=prescription)
        formset = PrescriptionItemFormSet(request.POST, instance=prescription, prefix='items')

        if form.is_valid() and formset.is_valid():
            submission_in_progress = False
            if form_token and not try_acquire_prescription_edit_lock(prescription_id, form_token):
                cached_id = get_cached_edit_prescription_id(prescription_id, form_token)
                if cached_id:
                    messages.info(request, 'Prescription changes were already saved.')
                    return redirect('home:prescription_detail', prescription_id=cached_id)
                submission_in_progress = True
                messages.warning(
                    request,
                    'Your changes are already being saved. Please wait a moment.',
                )

            if not submission_in_progress:
                dispensed_conflict = False
                for med_form in formset.forms:
                    if med_form.instance.pk and med_form.instance.dispensed:
                        if med_form.cleaned_data.get('DELETE'):
                            messages.error(request, f"Cannot delete {med_form.instance.medication.name} because it has already been dispensed.")
                            dispensed_conflict = True
                        elif any(field in med_form.changed_data for field in ['medication', 'quantity', 'dose_count', 'frequency', 'number_of_days', 'instructions']):
                            messages.error(request, f"Cannot modify {med_form.instance.medication.name} as it has already been dispensed to the patient.")
                            dispensed_conflict = True

                if not dispensed_conflict:
                    try:
                        with transaction.atomic():
                            Prescription.objects.select_for_update().get(pk=prescription_id)
                            cached_id = get_cached_edit_prescription_id(prescription_id, form_token)
                            if cached_id:
                                messages.info(request, 'Prescription changes were already saved.')
                                return redirect('home:prescription_detail', prescription_id=cached_id)

                            prescription = form.save()
                            formset.save()

                        if invoice:
                            if not prescription.invoice:
                                prescription.invoice = invoice
                                prescription.save(update_fields=['invoice'])

                            current_med_ids = []
                            for p_item in prescription.items.all():
                                current_med_ids.append(p_item.medication.id)
                                i_item = InvoiceItem.objects.filter(
                                    invoice=invoice,
                                    inventory_item=p_item.medication
                                ).first()

                                if i_item:
                                    if i_item.quantity != p_item.quantity or i_item.unit_price != p_item.medication.selling_price:
                                        i_item.quantity = p_item.quantity
                                        i_item.unit_price = p_item.medication.selling_price
                                        i_item.save()
                                else:
                                    if p_item.medication.selling_price > 0:
                                        InvoiceItem.objects.create(
                                            invoice=invoice,
                                            inventory_item=p_item.medication,
                                            name=p_item.medication.name,
                                            unit_price=p_item.medication.selling_price,
                                            quantity=p_item.quantity
                                        )

                            invoice_meds = invoice.items.filter(inventory_item__isnull=False)
                            for i_item in invoice_meds:
                                if hasattr(i_item.inventory_item, 'medication'):
                                    if i_item.inventory_item.id not in current_med_ids:
                                        if not i_item.is_dispensed:
                                            i_item.delete()

                            invoice.update_totals()
                            if invoice.total_amount < old_paid_amount:
                                overpaid = old_paid_amount - invoice.total_amount
                                PatientCredit.objects.create(
                                    patient=patient,
                                    invoice=invoice,
                                    amount=overpaid,
                                    reason=f"Adjustment due to prescription edit (#{prescription.id})",
                                    created_by=request.user
                                )
                                messages.info(request, f"Note: A credit of {overpaid} has been recorded for {patient.full_name} due to overpayment.")

                        cache_prescription_edit(prescription_id, form_token)
                        try:
                            from .medication_registry import sync_active_medications_from_prescription
                            synced = sync_active_medications_from_prescription(
                                prescription, user=request.user,
                            )
                            if synced:
                                messages.info(
                                    request,
                                    f'Active Medication List updated ({synced} item(s)).',
                                )
                        except Exception:
                            pass
                        messages.success(request, f"Prescription for {patient.full_name} updated successfully.")
                        return redirect('home:prescription_detail', prescription_id=prescription.id)
                    finally:
                        if form_token and not get_cached_edit_prescription_id(prescription_id, form_token):
                            release_prescription_edit_lock(prescription_id, form_token)
                else:
                    if form_token:
                        release_prescription_edit_lock(prescription_id, form_token)
    else:
        form = PrescriptionForm(instance=prescription)
        formset = PrescriptionItemFormSet(instance=prescription, prefix='items')
        form_token = str(uuid.uuid4())

    # Prepare medication metadata for JS (same as create_prescription)
    from inventory.models import InventoryItem, InventoryCategory
    import json
    
    pharma_category = InventoryCategory.objects.filter(name__icontains='Pharmaceutical').first()
    if pharma_category:
        medications = InventoryItem.objects.filter(category=pharma_category).select_related('category')
    else:
        medications = InventoryItem.objects.all().select_related('category')
    
    from django.db.models import Sum
    from inventory.models import StockRecord

    # Determine eligible departments for stock check (Pharmacy only for outpatient, include Mini Pharmacy for inpatient)
    departments = ['Pharmacy']
    if prescription.visit and prescription.visit.visit_type == 'IN-PATIENT':
        departments.append('Mini Pharmacy')
    
    med_metadata = {}
    for item in medications:
        details = getattr(item, 'medication', None)
        total_stock = StockRecord.objects.filter(
            item=item,
            current_location__name__in=departments
        ).aggregate(quantity__sum=Sum('quantity'))['quantity__sum'] or 0

        med_metadata[item.id] = {
            'name': item.name,
            'generic_name': details.generic_name if details else '',
            'formulation': details.formulation if details else '',
            'drug_class': details.drug_class.name if details and details.drug_class else '',
            'strength_amount': details.strength_amount if details else '',
            'strength_unit': details.strength_unit if details else '',
            'generic_concept_code': details.generic_concept_code if details else '',
            'generic_concept_display': details.generic_concept_display if details else '',
            'is_dha_mapped': bool(details and details.generic_concept_code),
            'is_dispensed_as_whole': item.is_dispensed_as_whole,
            'dispensing_unit': item.dispensing_unit,
            'selling_price': str(item.selling_price),
            'stock_quantity': total_stock,
            'visit_type': visit.visit_type if visit else 'OUT-PATIENT'
        }
    
    pending_consumables, dispensed_consumables = _get_editable_visit_consumables(visit)
    from inventory.models import InventoryItem
    from inventory.consumable_utils import available_stock_for_department
    consumable_dept = Departments.objects.filter(
        name__iexact='Mini Pharmacy' if request.user.role == 'Nurse' else 'Pharmacy',
    ).first()
    for row in pending_consumables:
        try:
            inv_item = InventoryItem.objects.get(pk=row['inventory_item_id'])
            row['available_stock'] = available_stock_for_department(inv_item, consumable_dept)
        except InventoryItem.DoesNotExist:
            row['available_stock'] = 0
    context = {
        'form': form,
        'formset': formset,
        'patient': patient,
        'prescription': prescription,
        'visit': visit,
        'form_token': form_token,
        'med_metadata_json': json.dumps(med_metadata),
        'dispensing_departments': Departments.objects.all().order_by('name'),
        'pending_consumables': pending_consumables,
        'dispensed_consumables': dispensed_consumables,
        'dispensed_items': _get_normalized_history(visit, patient),
        'can_edit_consumables': _can_edit_visit_consumable(request.user),
        'consumable_stock_department_id': consumable_dept.pk if consumable_dept else '',
        'consumable_stock_department_name': consumable_dept.name if consumable_dept else 'Pharmacy',
    }
    return render(request, 'home/edit_prescription.html', context)


@login_required
def prescription_list(request, patient_id):
    """List all prescriptions for a patient"""
    from .models import Prescription
    
    patient = get_object_or_404(Patient, pk=patient_id)
    prescriptions = patient.prescriptions.all()
    
    # Filter by status if provided
    status_filter = request.GET.get('status', '')
    if status_filter:
        prescriptions = prescriptions.filter(status=status_filter)
    
    context = {
        'patient': patient,
        'prescriptions': prescriptions,
        'status_filter': status_filter,
    }
    return render(request, 'home/prescription_list.html', context)
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Sum, Count
from datetime import timedelta
from .models import Prescription, PrescriptionItem
from inventory.models import InventoryItem, StockRecord, InventoryRequest
from home.models import Departments


@login_required
def pharmacy_dashboard(request):
    """Pharmacy dashboard showing OPD and IPD prescriptions, consumables, stock, and requests"""
    # Role-based access control
    if request.user.role not in ['Pharmacist', 'Nurse', 'Admin']:
        messages.error(request, "Access denied. Only pharmacists, nurses and admins can access the pharmacy dashboard.")
        return redirect('home:reception_dashboard')

    # Always use the main Pharmacy department for this dashboard
    pharmacy_dept, created = Departments.objects.get_or_create(
        name='Pharmacy',
        defaults={'abbreviation': 'PHR'}
    )

    # Date filter
    from datetime import datetime, time
    filter_date_str = request.GET.get('date')
    if filter_date_str:
        try:
            filter_date = datetime.strptime(filter_date_str, '%Y-%m-%d').date()
        except ValueError:
            filter_date = timezone.localdate()
    else:
        filter_date = timezone.localdate()

    start_of_day = timezone.make_aware(datetime.combine(filter_date, time.min))
    end_of_day = timezone.make_aware(datetime.combine(filter_date, time.max))

    # Search functionality
    search_query = request.GET.get('search', '')
    stock_search = request.GET.get('stock_search', '')
    dispensed_search = request.GET.get('dispensed_search', '')
    request_search = request.GET.get('request_search', '')

    # Get ALL pending prescriptions and filter in Python to avoid DB-specific date issues
    pending_items_all = PrescriptionItem.objects.filter(dispensed=False).select_related(
        'prescription__patient',
        'prescription__prescribed_by',
        'prescription__invoice',
        'prescription__visit',
        'medication'
    )
    if _is_nurse_user(request.user):
        pending_items_all = pending_items_all.filter(prescription__visit__by_nurse=True)
    pending_items_all = pending_items_all.order_by('-prescription__prescribed_at')
    
    # Python-side filtering for reliability
    pending_items = [
        item for item in pending_items_all 
        if item.prescription and item.prescription.prescribed_at and timezone.localdate(item.prescription.prescribed_at) == filter_date
        and _visit_ok_for_user(item.prescription.visit, request.user)
    ]

    # Get ALL pending consumables and filter in Python
    from accounts.models import Invoice, InvoiceItem
    from inpatient.models import Admission

    pending_consumables_all = InvoiceItem.objects.filter(
        inventory_item__isnull=False,
        invoice__status__in=['Draft', 'Pending', 'Paid', 'Partial']
    ).select_related(
        'invoice__patient',
        'invoice__visit',
        'inventory_item',
    )
    if _is_nurse_user(request.user):
        pending_consumables_all = pending_consumables_all.filter(invoice__visit__by_nurse=True)
    pending_consumables_all = pending_consumables_all.order_by('-created_at')
    
    pending_consumables_list_raw = [
        ci for ci in pending_consumables_all
        if ci.created_at and timezone.localdate(ci.created_at) == filter_date
        and _visit_ok_for_user(ci.invoice.visit, request.user)
    ]

    # Group DispensedItem quantities to calculate net pending
    from django.db.models import Sum
    dispensed_map = {}
    dispensed_qs = DispensedItem.objects.filter(
        dispensed_at__range=(start_of_day, end_of_day)
    ).filter(_nurse_visit_q(request.user, prefix='visit__')).values('visit_id', 'item_id').annotate(total_qty=Sum('quantity'))
    
    for d in dispensed_qs:
        dispensed_map[(d['visit_id'], d['item_id'])] = d['total_qty']

    pending_consumable_list = []
    pool_usage = dispensed_map.copy()

    for ci in pending_consumables_list_raw:
        visit_id = ci.invoice.visit_id
        item_id = ci.inventory_item_id
        qty_invoiced = ci.quantity
        
        already_dispensed = pool_usage.get((visit_id, item_id), 0)
        
        if already_dispensed >= qty_invoiced:
            pool_usage[(visit_id, item_id)] = already_dispensed - qty_invoiced
            continue
        elif already_dispensed > 0:
            ci.quantity -= already_dispensed
            pool_usage[(visit_id, item_id)] = 0

        # Skip IPD consumables only if the patient is currently admitted (handled by IPD dashboard)
        # However, at discharge, the status is 'Discharged', so they should show up here.
        is_admitted = Admission.objects.filter(visit=ci.invoice.visit, status='Admitted').exists()
        if not is_admitted:
            pending_consumable_list.append(ci)

    if search_query and search_query.strip():
        search_query = search_query.lower().strip()
        pending_items = [
            item for item in pending_items
            if search_query in (item.prescription.patient.first_name or '').lower()
            or search_query in (item.prescription.patient.last_name or '').lower()
            or search_query in (item.medication.name or '').lower()
        ]
        # Filter pending consumable list
        pending_consumable_list = [
            ci for ci in pending_consumable_list
            if search_query.lower() in (ci.invoice.patient.first_name or '').lower()
            or search_query.lower() in (ci.invoice.patient.last_name or '').lower()
            or search_query.lower() in (ci.inventory_item.name or '').lower()
        ]

    # ---- Build grouped data: separate OPD and IPD ----
    from collections import defaultdict
    from collections import OrderedDict

    def create_group():
        return {
            'patient': None,
            'visit': None,
            'prescriptions': [],
            'consumables': [],
            'invoice': None,
            'invoice_status': 'No Invoice',
            'prescribed_at': None,
            'prescribed_by': None,
            'prescription_id': None,
            'diagnosis': '',
        }

    opd_visit_groups = defaultdict(create_group)
    ipd_visit_groups = defaultdict(create_group)

    for item in pending_items:
        visit = item.prescription.visit
        if not visit:
            continue
        
        is_ipd = str(visit.visit_type).upper() == 'IN-PATIENT'
        group = ipd_visit_groups[visit.id] if is_ipd else opd_visit_groups[visit.id]
        
        group['patient'] = item.prescription.patient
        group['visit'] = visit
        group['prescriptions'].append(item)
        if not group['prescription_id']:
            group['prescription_id'] = item.prescription.id
        if item.prescription.invoice:
            group['invoice'] = item.prescription.invoice
            group['invoice_status'] = item.prescription.invoice.status
        if not group['prescribed_at'] or item.prescription.prescribed_at > group['prescribed_at']:
            group['prescribed_at'] = item.prescription.prescribed_at
            group['prescribed_by'] = item.prescription.prescribed_by
            group['diagnosis'] = item.prescription.diagnosis

    for ci in pending_consumable_list:
        visit = ci.invoice.visit
        if not visit:
            continue
            
        is_ipd = str(visit.visit_type).upper() == 'IN-PATIENT'
        group = ipd_visit_groups[visit.id] if is_ipd else opd_visit_groups[visit.id]
        
        # Avoid duplicates
        is_duplicate = False
        for p_item in group['prescriptions']:
            if p_item.medication_id == ci.inventory_item_id and p_item.quantity == ci.quantity:
                is_duplicate = True
                break
        
        if not is_duplicate:
            group['patient'] = ci.invoice.patient
            group['visit'] = visit
            group['consumables'].append(ci)
            if not group['invoice']:
                group['invoice'] = ci.invoice
                group['invoice_status'] = ci.invoice.status


    # Convert to list and sort
    def sort_groups(groups_dict):
        return sorted(
            [g for g in groups_dict.values() if g['patient']],
            key=lambda g: g['prescribed_at'] or timezone.now(),
            reverse=True
        )

    opd_groups = sort_groups(opd_visit_groups)
    ipd_groups = sort_groups(ipd_visit_groups)

    # Get recently dispensed items (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    dispensed_items = DispensedItem.objects.filter(
        dispensed_at__gte=thirty_days_ago
    ).filter(_nurse_visit_q(request.user, prefix='visit__')).select_related(
        'patient',
        'item',
        'dispensed_by'
    ).order_by('-dispensed_at')[:50]

    # Apply dispensed search filter
    if dispensed_search:
        dispensed_items = dispensed_items.filter(
            Q(patient__first_name__icontains=dispensed_search) |
            Q(patient__last_name__icontains=dispensed_search) |
            Q(item__name__icontains=dispensed_search)
        )

    # Get pharmacy stock
    pharmacy_stock = StockRecord.objects.filter(
        current_location=pharmacy_dept,
        quantity__gt=0
    ).select_related('item', 'supplier').order_by('item__name')

    # Apply stock search filter
    if stock_search:
        pharmacy_stock = pharmacy_stock.filter(
            Q(item__name__icontains=stock_search) |
            Q(batch_number__icontains=stock_search)
        )

    # Identify low stock items (below reorder level)
    low_stock_items = []
    expiring_soon_items = []
    today = timezone.localdate()
    thirty_days_later = today + timedelta(days=30)

    for stock in pharmacy_stock:
        total_qty = StockRecord.objects.filter(
            current_location=pharmacy_dept,
            item=stock.item
        ).aggregate(total=Sum('quantity'))['total'] or 0

        if total_qty <= stock.item.reorder_level:
            if stock not in low_stock_items:
                low_stock_items.append(stock)

        if stock.expiry_date and stock.expiry_date <= thirty_days_later:
            expiring_soon_items.append(stock)

    # Get inventory requests for pharmacy
    inventory_requests_all = InventoryRequest.objects.filter(
        location=pharmacy_dept
    ).select_related('item', 'requested_by').order_by('-requested_at')

    if request_search:
        inventory_requests_all = inventory_requests_all.filter(
            Q(item__name__icontains=request_search) |
            Q(requested_by__first_name__icontains=request_search) |
            Q(requested_by__last_name__icontains=request_search)
        )

    pending_requests_count = inventory_requests_all.filter(status='Pending').count()
    inventory_requests = inventory_requests_all[:20]

    # Statistics
    stats = {
        'pending_prescriptions': len(pending_items) + len(pending_consumable_list),
        'opd_count': len(opd_groups),
        'ipd_count': len(ipd_groups),
        'low_stock_count': len(low_stock_items),
        'pending_requests': pending_requests_count,
        'dispensed_today': DispensedItem.objects.filter(
            dispensed_at__range=(start_of_day, end_of_day)
        ).filter(_nurse_visit_q(request.user, prefix='visit__')).count(),
    }

    context = {
        'opd_groups': opd_groups,
        'ipd_groups': ipd_groups,
        'pending_items': pending_items,
        'dispensed_items': dispensed_items,
        'pharmacy_stock': pharmacy_stock,
        'low_stock_items': low_stock_items,
        'expiring_soon_items': expiring_soon_items,
        'inventory_requests': inventory_requests,
        'stats': stats,
        'search_query': search_query,
        'stock_search': stock_search,
        'dispensed_search': dispensed_search,
        'request_search': request_search,
        'filter_date': filter_date,
        'debug_info': {
            'total_pending_all_dates': pending_items_all.count(),
            'after_python_date_filter': len(pending_items),
            'consumables_count': len(pending_consumable_list),
            'filter_date': filter_date,
            'tz_now': timezone.now(),
            'local_date': timezone.localdate(),
        },
        'pharmacy_dept': pharmacy_dept,
        'today_plus_30': today + timedelta(days=30),
        'can_edit_consumables': _can_edit_pharmacy_consumable(request.user),
    }

    return render(request, 'home/pharmacy_dashboard.html', context)


@login_required
@transaction.atomic
@require_http_methods(["POST"])
def api_pharmacy_update_consumable(request, item_id):
    """Update pending consumable item and/or quantity. Unit price follows the selected item (not editable separately)."""
    if not _can_edit_visit_consumable(request.user):
        return JsonResponse({'success': False, 'error': 'You do not have permission to edit consumables.'})

    from inventory.models import InventoryItem
    from accounts.models import PatientCredit
    from decimal import Decimal

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid request data.'})

    if 'unit_price' in payload or 'price' in payload:
        return JsonResponse({'success': False, 'error': 'Price cannot be changed from the pharmacy dashboard.'})

    quantity = payload.get('quantity')
    inventory_item_id = payload.get('inventory_item_id')
    department_id = payload.get('department_id')

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Quantity must be a whole number.'})
    if quantity < 1:
        return JsonResponse({'success': False, 'error': 'Quantity must be at least 1.'})

    invoice_item = get_object_or_404(
        InvoiceItem.objects.select_related('invoice__visit', 'invoice__patient', 'inventory_item'),
        pk=item_id,
        inventory_item__isnull=False,
    )

    if invoice_item.invoice.status == 'Cancelled':
        return JsonResponse({'success': False, 'error': 'Cannot edit items on a cancelled invoice.'})

    visit = invoice_item.invoice.visit
    if not visit:
        return JsonResponse({'success': False, 'error': 'This item is not linked to a visit.'})

    if not _invoice_item_is_consumable_line(invoice_item):
        return JsonResponse({
            'success': False,
            'error': 'This line is linked to a prescription medication and cannot be edited here.',
        })

    dispensed = _consumable_dispensed_qty(visit, invoice_item.inventory_item_id)
    if dispensed > 0:
        return JsonResponse({
            'success': False,
            'error': 'Cannot edit: dispensing has already started for this item on this visit.',
        })

    old_paid = invoice_item.invoice.paid_amount
    patient = invoice_item.invoice.patient

    if inventory_item_id is not None:
        try:
            inventory_item_id = int(inventory_item_id)
        except (TypeError, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid item selected.'})

        new_item = get_object_or_404(InventoryItem, pk=inventory_item_id)
        if hasattr(new_item, 'medication'):
            return JsonResponse({
                'success': False,
                'error': 'Selected item is a medication. Choose a consumable from stock.',
            })
        invoice_item.inventory_item = new_item
        invoice_item.name = new_item.name
        invoice_item.unit_price = new_item.selling_price or Decimal('0')

    stock_item = invoice_item.inventory_item
    from home.models import Departments
    from inventory.consumable_utils import available_stock_for_department

    department = None
    if department_id:
        try:
            department = Departments.objects.filter(pk=int(department_id)).first()
        except (TypeError, ValueError):
            pass
    if not department:
        dept_name = 'Mini Pharmacy' if getattr(request.user, 'role', None) == 'Nurse' else 'Pharmacy'
        department = Departments.objects.filter(name__iexact=dept_name).first()

    available_stock = available_stock_for_department(stock_item, department)
    if quantity > available_stock:
        dept_label = department.name if department else 'Pharmacy'
        return JsonResponse({
            'success': False,
            'error': (
                f'Insufficient stock in {dept_label}. '
                f'Available: {available_stock}, requested: {quantity}.'
            ),
        })

    invoice_item.quantity = quantity
    invoice_item.save()

    invoice = invoice_item.invoice
    invoice.update_totals()
    if patient and invoice.total_amount < old_paid:
        overpaid = old_paid - invoice.total_amount
        if overpaid > 0:
            PatientCredit.objects.create(
                patient=patient,
                invoice=invoice,
                amount=overpaid,
                reason=f'Adjustment due to consumable edit (line #{invoice_item.id})',
                created_by=request.user,
            )

    return JsonResponse({
        'success': True,
        'message': f'Updated {invoice_item.name} × {invoice_item.quantity}.',
        'item': {
            'id': invoice_item.id,
            'name': invoice_item.name,
            'quantity': invoice_item.quantity,
            'inventory_item_id': invoice_item.inventory_item_id,
        },
    })


@login_required
@transaction.atomic
@require_http_methods(["POST"])
def api_pharmacy_delete_consumable(request, item_id):
    """Remove a pending consumable invoice line (pharmacist/admin only)."""
    if not _can_edit_visit_consumable(request.user):
        return JsonResponse({'success': False, 'error': 'You do not have permission to delete consumables.'})

    from accounts.models import PatientCredit
    from decimal import Decimal

    invoice_item = get_object_or_404(
        InvoiceItem.objects.select_related('invoice__visit', 'invoice__patient', 'inventory_item'),
        pk=item_id,
        inventory_item__isnull=False,
    )

    if invoice_item.invoice.status == 'Cancelled':
        return JsonResponse({'success': False, 'error': 'Cannot remove items on a cancelled invoice.'})

    visit = invoice_item.invoice.visit
    if not visit:
        return JsonResponse({'success': False, 'error': 'This item is not linked to a visit.'})

    if not _invoice_item_is_consumable_line(invoice_item):
        return JsonResponse({
            'success': False,
            'error': 'This line is linked to a prescription medication and cannot be removed here.',
        })

    dispensed = _consumable_dispensed_qty(visit, invoice_item.inventory_item_id)
    if dispensed > 0 or invoice_item.is_dispensed:
        return JsonResponse({
            'success': False,
            'error': 'Cannot delete: dispensing has already started for this item on this visit.',
        })

    item_name = invoice_item.name
    old_paid = invoice_item.invoice.paid_amount
    patient = invoice_item.invoice.patient
    invoice = invoice_item.invoice

    invoice_item.delete()
    invoice.update_totals()

    if patient and invoice.total_amount < old_paid:
        overpaid = old_paid - invoice.total_amount
        if overpaid > 0:
            PatientCredit.objects.create(
                patient=patient,
                invoice=invoice,
                amount=overpaid,
                reason=f'Adjustment due to consumable removal (line #{item_id})',
                created_by=request.user,
            )

    return JsonResponse({
        'success': True,
        'message': f'Removed {item_name} from the visit invoice.',
    })


@login_required
@transaction.atomic
@require_http_methods(["POST"])
def dispense_all_visit_items(request, visit_id):
    """
    Dispense ALL pending items (medications + consumables) for a visit.
    - OPD: requires invoice to be Paid before dispensing.
    - IPD: dispenses immediately, creates invoice items at dispense time.
    """
    from accounts.models import Invoice, InvoiceItem
    from inventory.models import StockAdjustment, DispensedItem
    from inpatient.models import Admission

    try:
        visit = get_object_or_404(Visit, pk=visit_id)
        patient = visit.patient
        
        # Role-based validation
        if request.user.role not in ['Pharmacist', 'Nurse']:
            return JsonResponse({'success': False, 'error': 'Unauthorized role.'})
            
        # Determine if IPD or OPD
        is_ipd = Admission.objects.filter(visit=visit, status='Admitted').exists()
        
        # Enforce role-based strictness
        if is_ipd and request.user.role not in ['Nurse', 'Pharmacist', 'Admin']:
            return JsonResponse({'success': False, 'error': 'Only pharmacists and nurses can dispense IPD medications.'})
        if not is_ipd and request.user.role not in ['Pharmacist', 'Admin']:
            return JsonResponse({'success': False, 'error': 'Only pharmacists can dispense OPD medications.'})

        # Always use Pharmacy department for stock deduction
        pharmacy_dept = Departments.objects.get(name='Pharmacy')

        # ---- Gather pending items ----
        # 1. Prescription medications (PrescriptionItem)
        pending_meds = PrescriptionItem.objects.filter(
            prescription__visit=visit,
            dispensed=False,
        ).select_related('medication', 'prescription__invoice', 'prescription__patient')

        # 2. Pending consumables
        # Scenario A: InpatientConsumable (Modern IPD deferred billing)
        from inpatient.models import Admission, InpatientConsumable
        pending_ipd_consumable_reqs = InpatientConsumable.objects.filter(
            admission__visit=visit,
            is_dispensed=False
        ).select_related('item', 'admission')

        # Scenario B: InvoiceItems marked as Consumable or Direct-Billed Meds (not from prescription)
        pending_consumable_items = InvoiceItem.objects.filter(
            invoice__visit=visit,
            inventory_item__isnull=False,
        ).select_related('inventory_item', 'invoice')

        # Robust De-duplication for Consumables:
        # Calculate total quantity already dispensed for each item in this visit
        from django.db.models import Sum
        dispensed_totals = {
            item_id: total_qty for item_id, total_qty in 
            DispensedItem.objects.filter(visit=visit).values_list('item_id').annotate(total=Sum('quantity'))
        }

        pending_consumables = []
        # Track what we've already accounted for in this loop to handle multiple InvoiceItems for same item
        accounted_for_dispensed = dispensed_totals.copy()

        for ci in pending_consumable_items:
            item_id = ci.inventory_item_id
            qty_needed = ci.quantity
            
            # 1. Skip if already covered by a prescription item (to prevent double billing/dispensing)
            if any(pm.medication_id == item_id and pm.quantity == qty_needed for pm in pending_meds):
                continue
            
            # 2. Check if this specific quantity has already been dispensed
            already_dispensed = accounted_for_dispensed.get(item_id, 0)
            if already_dispensed >= qty_needed:
                # This item was already dispensed, subtract from pool and skip
                accounted_for_dispensed[item_id] -= qty_needed
                continue
            elif already_dispensed > 0:
                # Partially dispensed? Adjust quantity to only dispense the remainder
                ci.quantity -= already_dispensed
                accounted_for_dispensed[item_id] = 0
                
            pending_consumables.append(ci)

        total_pending = pending_meds.count() + len(pending_consumables) + pending_ipd_consumable_reqs.count()
        if total_pending == 0:
            return JsonResponse({
                'success': False,
                'error': 'No pending items found for this visit.'
            })

        # ---- OPD: Check payment ----
        if not is_ipd:
            # Check all related invoices are paid
            invoices = Invoice.objects.filter(visit=visit).exclude(status='Cancelled')
            unpaid = invoices.exclude(status='Paid')
            if unpaid.exists():
                inv_ids = ', '.join([f'INV-{inv.id}' for inv in unpaid])
                return JsonResponse({
                    'success': False,
                    'error': f'Payment required. Unpaid invoices: {inv_ids}'
                })

        dispensed_count = 0
        errors = []

        # ---- Dispense medications ----
        for med in pending_meds:
            # Check stock (FEFO)
            stock_records = StockRecord.objects.filter(
                current_location=pharmacy_dept,
                item=med.medication,
                quantity__gt=0
            ).order_by('expiry_date').select_for_update()

            total_available = sum(r.quantity for r in stock_records)
            if total_available < med.quantity:
                errors.append(f'Insufficient stock for {med.medication.name} (need {med.quantity}, have {total_available})')
                continue

            # Deduct stock FEFO
            remaining = med.quantity
            for record in stock_records:
                if remaining <= 0:
                    break
                take = min(record.quantity, remaining)
                record.quantity -= take
                record.save()
                StockAdjustment.objects.create(
                    item=med.medication,
                    quantity=-take,
                    adjustment_type='Usage',
                    reason=f'Dispensed to {patient.full_name} (Visit {visit.id})',
                    adjusted_by=request.user,
                    adjusted_from=pharmacy_dept,
                )
                remaining -= take

            # Mark as dispensed (+ DHA pack code snapshot)
            from accounts.sha_claims_service import mark_rx_item_dispensed
            mark_rx_item_dispensed(med, request.user)

            DispensedItem.objects.create(
                item=med.medication,
                patient=patient,
                visit=visit,
                quantity=med.quantity,
                dispensed_by=request.user,
                department=pharmacy_dept,
            )
            dispensed_count += 1

        # ---- Dispense consumables ----
        for ci in pending_consumables:
            item = ci.inventory_item
            qty = ci.quantity

            # Check stock (FEFO)
            stock_records = StockRecord.objects.filter(
                current_location=pharmacy_dept,
                item=item,
                quantity__gt=0
            ).order_by('expiry_date').select_for_update()

            total_available = sum(r.quantity for r in stock_records)
            if total_available < qty:
                errors.append(f'Insufficient stock for {item.name} (need {qty}, have {total_available})')
                continue

            # Deduct stock FEFO
            remaining = qty
            for record in stock_records:
                if remaining <= 0:
                    break
                take = min(record.quantity, remaining)
                record.quantity -= take
                record.save()
                StockAdjustment.objects.create(
                    item=item,
                    quantity=-take,
                    adjustment_type='Usage',
                    reason=f'Consumable dispensed to {patient.full_name} (Visit {visit.id})',
                    adjusted_by=request.user,
                    adjusted_from=pharmacy_dept,
                )
                remaining -= take

            DispensedItem.objects.create(
                item=item,
                patient=patient,
                visit=visit,
                quantity=qty,
                dispensed_by=request.user,
                department=pharmacy_dept,
            )
            dispensed_count += 1

        # ---- IPD: Also dispense MedicationChart items ----
        if is_ipd:
            pending_ipd_meds = MedicationChart.objects.filter(
                admission__visit=visit,
                is_dispensed=False,
            ).select_related('item', 'admission__patient')

            for med_item in pending_ipd_meds:
                qty_to_dispense = med_item.quantity
                if qty_to_dispense == 0:
                    errors.append(f'Zero quantity for {med_item.item.name}')
                    continue

                stock_records = StockRecord.objects.filter(
                    current_location=pharmacy_dept,
                    item=med_item.item,
                    quantity__gt=0
                ).order_by('expiry_date').select_for_update()

                total_available = sum(r.quantity for r in stock_records)
                if total_available < qty_to_dispense:
                    errors.append(f'Insufficient stock for {med_item.item.name} (need {qty_to_dispense}, have {total_available})')
                    continue

                # Deduct stock FEFO
                remaining = qty_to_dispense
                for record in stock_records:
                    if remaining <= 0:
                        break
                    take = min(record.quantity, remaining)
                    record.quantity -= take
                    record.save()
                    StockAdjustment.objects.create(
                        item=med_item.item,
                        quantity=-take,
                        adjustment_type='Usage',
                        reason=f'IPD Dispensed to {patient.full_name} (Visit {visit.id})',
                        adjusted_by=request.user,
                        adjusted_from=pharmacy_dept,
                    )
                    remaining -= take

                # Mark as dispensed
                med_item.is_dispensed = True
                med_item.dispensed_at = timezone.now()
                med_item.dispensed_by = request.user
                if med_item.quantity == 0:
                    med_item.quantity = qty_to_dispense
                med_item.save()

                DispensedItem.objects.create(
                    item=med_item.item,
                    patient=patient,
                    visit=visit,
                    quantity=qty_to_dispense,
                    dispensed_by=request.user,
                    department=pharmacy_dept,
                )

                # Add to IPD Invoice
                try:
                    invoice = Invoice.objects.filter(
                        visit=visit,
                        status__in=['Draft', 'Pending'],
                    ).first()
                    invoice = get_or_create_invoice(visit=visit, user=request.user)
                    if invoice.notes:
                        invoice.notes += f"\nIPD Billing for Visit {visit.id}"
                    else:
                        invoice.notes = f"IPD Billing for Visit {visit.id}"
                    invoice.save()
                    if med_item.item.selling_price > 0:
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            inventory_item=med_item.item,
                            name=f"{med_item.item.name} (IPD Dispense)",
                            quantity=qty_to_dispense,
                            unit_price=med_item.item.selling_price,
                        )
                except Exception as inv_err:
                    print(f"Invoicing failed for IPD med {med_item.id}: {str(inv_err)}")

                dispensed_count += 1

        # ---- Dispense InpatientConsumable requests (and bill them now) ----
        for req in pending_ipd_consumable_reqs:
            item = req.item
            qty = req.quantity

            # Check stock (FEFO)
            stock_records = StockRecord.objects.filter(
                current_location=pharmacy_dept,
                item=item,
                quantity__gt=0
            ).order_by('expiry_date').select_for_update()

            total_available = sum(r.quantity for r in stock_records)
            if total_available < qty:
                errors.append(f'Insufficient stock for {item.name} (need {qty}, have {total_available})')
                continue

            # Deduct stock FEFO
            remaining = qty
            for record in stock_records:
                if remaining <= 0:
                    break
                take = min(record.quantity, remaining)
                record.quantity -= take
                record.save()
                StockAdjustment.objects.create(
                    item=item,
                    quantity=-take,
                    adjustment_type='Usage',
                    reason=f'Consumable dispensed to {patient.full_name} (Visit {visit.id})',
                    adjusted_by=request.user,
                    adjusted_from=pharmacy_dept,
                )
                remaining -= take

            # Create InvoiceItem (Billed now upon dispense)
            try:
                invoice = Invoice.objects.filter(
                    visit=visit,
                    status__in=['Draft', 'Pending'],
                ).first()
                invoice = get_or_create_invoice(visit=visit, user=request.user)
                if invoice.notes:
                    invoice.notes += f"\nConsumable billing for IPD dispense {visit.id}"
                else:
                    invoice.notes = f"Consumable billing for IPD dispense {visit.id}"
                invoice.save()

                if item.selling_price > 0:
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        inventory_item=item,
                        name=f"{item.name} (Consumable)",
                        quantity=qty,
                        unit_price=item.selling_price,
                    )
                    invoice.update_totals()
            except Exception as inv_err:
                print(f"Invoicing failed for consumable req {req.id}: {str(inv_err)}")

            # Mark request as dispensed
            req.is_dispensed = True
            req.dispensed_at = timezone.now()
            req.dispensed_by = request.user
            req.save()

            DispensedItem.objects.create(
                item=item,
                patient=patient,
                visit=visit,
                quantity=qty,
                dispensed_by=request.user,
                department=pharmacy_dept,
            )
            dispensed_count += 1

        if dispensed_count == 0:
            return JsonResponse({
                'success': False,
                'error': '; '.join(errors) if errors else 'No items could be dispensed'
            })

        message = f'Successfully dispensed {dispensed_count} items.'
        if errors:
            message += f' Warnings: {"; ".join(errors)}'

        return JsonResponse({
            'success': True,
            'message': message,
            'dispensed_count': dispensed_count
        })

    except Departments.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Pharmacy department not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def night_pharmacy_dashboard(request):
    """Night Pharmacy dashboard showing OPD prescriptions, consumables, stock, and requests for Mini Pharmacy"""
    # Role-based access control
    if request.user.role not in ['Nurse', 'Admin', 'Pharmacist']:
        messages.error(request, "Access denied. Only nurses, pharmacists and admins can access the night pharmacy dashboard.")
        return redirect('home:reception_dashboard')

    # Always use the Mini Pharmacy department for this dashboard
    pharmacy_dept, created = Departments.objects.get_or_create(
        name='Mini Pharmacy',
        defaults={'abbreviation': 'MINI'}
    )

    # Date filter
    from datetime import datetime, time
    filter_date_str = request.GET.get('date')
    if filter_date_str:
        try:
            filter_date = datetime.strptime(filter_date_str, '%Y-%m-%d').date()
        except ValueError:
            filter_date = timezone.localdate()
    else:
        filter_date = timezone.localdate()

    start_of_day = timezone.make_aware(datetime.combine(filter_date, time.min))
    end_of_day = timezone.make_aware(datetime.combine(filter_date, time.max))

    # Search functionality
    search_query = request.GET.get('search', '')
    stock_search = request.GET.get('stock_search', '')
    dispensed_search = request.GET.get('dispensed_search', '')
    request_search = request.GET.get('request_search', '')

    # Get ALL pending prescriptions and filter in Python
    pending_items_all = PrescriptionItem.objects.filter(dispensed=False).select_related(
        'prescription__patient',
        'prescription__prescribed_by',
        'prescription__invoice',
        'prescription__visit',
        'medication'
    )
    if _is_nurse_user(request.user):
        pending_items_all = pending_items_all.filter(prescription__visit__by_nurse=True)
    pending_items_all = pending_items_all.order_by('-prescription__prescribed_at')
    
    # Python-side filtering for reliability
    pending_items = [
        item for item in pending_items_all 
        if item.prescription and item.prescription.prescribed_at and timezone.localdate(item.prescription.prescribed_at) == filter_date
        and _visit_ok_for_user(item.prescription.visit, request.user)
    ]

    # Get ALL pending consumables and filter in Python
    from accounts.models import Invoice, InvoiceItem
    from inpatient.models import Admission

    pending_consumables_all = InvoiceItem.objects.filter(
        inventory_item__isnull=False,
        invoice__status__in=['Draft', 'Pending', 'Paid', 'Partial']
    ).select_related(
        'invoice__patient',
        'invoice__visit',
        'inventory_item',
    )
    if _is_nurse_user(request.user):
        pending_consumables_all = pending_consumables_all.filter(invoice__visit__by_nurse=True)
    pending_consumables_all = pending_consumables_all.order_by('-created_at')
    
    pending_consumables_list_raw = [
        ci for ci in pending_consumables_all
        if ci.created_at and timezone.localdate(ci.created_at) == filter_date
        and _visit_ok_for_user(ci.invoice.visit, request.user)
    ]

    # Group DispensedItem quantities to calculate net pending (filtered by Mini Pharmacy department)
    from django.db.models import Sum
    dispensed_map = {}
    dispensed_qs = DispensedItem.objects.filter(
        department=pharmacy_dept,
        dispensed_at__range=(start_of_day, end_of_day)
    ).filter(_nurse_visit_q(request.user, prefix='visit__')).values('visit_id', 'item_id').annotate(total_qty=Sum('quantity'))
    
    for d in dispensed_qs:
        dispensed_map[(d['visit_id'], d['item_id'])] = d['total_qty']

    pending_consumable_list = []
    pool_usage = dispensed_map.copy()

    for ci in pending_consumables_list_raw:
        visit_id = ci.invoice.visit_id
        item_id = ci.inventory_item_id
        qty_invoiced = ci.quantity
        
        already_dispensed = pool_usage.get((visit_id, item_id), 0)
        
        if already_dispensed >= qty_invoiced:
            pool_usage[(visit_id, item_id)] = already_dispensed - qty_invoiced
            continue
        elif already_dispensed > 0:
            ci.quantity -= already_dispensed
            pool_usage[(visit_id, item_id)] = 0

        # Skip IPD consumables (only OPD for Night Pharmacy)
        is_admitted = Admission.objects.filter(visit=ci.invoice.visit, status='Admitted').exists()
        is_ipd = str(ci.invoice.visit.visit_type).upper() == 'IN-PATIENT' if ci.invoice.visit else False
        if not is_admitted and not is_ipd:
            pending_consumable_list.append(ci)

    if search_query and search_query.strip():
        search_query = search_query.lower().strip()
        pending_items = [
            item for item in pending_items
            if search_query in (item.prescription.patient.first_name or '').lower()
            or search_query in (item.prescription.patient.last_name or '').lower()
            or search_query in (item.medication.name or '').lower()
        ]
        # Filter pending consumable list
        pending_consumable_list = [
            ci for ci in pending_consumable_list
            if search_query.lower() in (ci.invoice.patient.first_name or '').lower()
            or search_query.lower() in (ci.invoice.patient.last_name or '').lower()
            or search_query.lower() in (ci.inventory_item.name or '').lower()
        ]

    # ---- Build grouped data: OPD only ----
    from collections import defaultdict
    def create_group():
        return {
            'patient': None,
            'visit': None,
            'prescriptions': [],
            'consumables': [],
            'invoice': None,
            'invoice_status': 'No Invoice',
            'prescribed_at': None,
            'prescribed_by': None,
            'prescription_id': None,
            'diagnosis': '',
        }

    opd_visit_groups = defaultdict(create_group)

    for item in pending_items:
        visit = item.prescription.visit
        if not visit:
            continue
        
        is_ipd = str(visit.visit_type).upper() == 'IN-PATIENT'
        if is_ipd:
            continue
            
        group = opd_visit_groups[visit.id]
        group['patient'] = item.prescription.patient
        group['visit'] = visit
        group['prescriptions'].append(item)
        if not group['prescription_id']:
            group['prescription_id'] = item.prescription.id
        if item.prescription.invoice:
            group['invoice'] = item.prescription.invoice
            group['invoice_status'] = item.prescription.invoice.status
        if not group['prescribed_at'] or item.prescription.prescribed_at > group['prescribed_at']:
            group['prescribed_at'] = item.prescription.prescribed_at
            group['prescribed_by'] = item.prescription.prescribed_by
            group['diagnosis'] = item.prescription.diagnosis

    for ci in pending_consumable_list:
        visit = ci.invoice.visit
        if not visit:
            continue
            
        is_ipd = str(visit.visit_type).upper() == 'IN-PATIENT'
        if is_ipd:
            continue
            
        group = opd_visit_groups[visit.id]
        
        # Avoid duplicates
        is_duplicate = False
        for p_item in group['prescriptions']:
            if p_item.medication_id == ci.inventory_item_id and p_item.quantity == ci.quantity:
                is_duplicate = True
                break
        
        if not is_duplicate:
            group['patient'] = ci.invoice.patient
            group['visit'] = visit
            group['consumables'].append(ci)
            if not group['invoice']:
                group['invoice'] = ci.invoice
                group['invoice_status'] = ci.invoice.status

    # Convert to list and sort
    def sort_groups(groups_dict):
        return sorted(
            [g for g in groups_dict.values() if g['patient']],
            key=lambda g: g['prescribed_at'] or timezone.now(),
            reverse=True
        )

    opd_groups = sort_groups(opd_visit_groups)

    # Get recently dispensed items from Mini Pharmacy (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    dispensed_items = DispensedItem.objects.filter(
        department=pharmacy_dept,
        dispensed_at__gte=thirty_days_ago
    ).filter(_nurse_visit_q(request.user, prefix='visit__')).select_related(
        'patient',
        'item',
        'dispensed_by'
    ).order_by('-dispensed_at')[:50]

    # Apply dispensed search filter
    if dispensed_search:
        dispensed_items = dispensed_items.filter(
            Q(patient__first_name__icontains=dispensed_search) |
            Q(patient__last_name__icontains=dispensed_search) |
            Q(item__name__icontains=dispensed_search)
        )

    # Get Mini Pharmacy stock
    pharmacy_stock = StockRecord.objects.filter(
        current_location=pharmacy_dept,
        quantity__gt=0
    ).select_related('item', 'supplier').order_by('item__name')

    # Apply stock search filter
    if stock_search:
        pharmacy_stock = pharmacy_stock.filter(
            Q(item__name__icontains=stock_search) |
            Q(batch_number__icontains=stock_search)
        )

    # Identify low stock items (below reorder level)
    low_stock_items = []
    expiring_soon_items = []
    today = timezone.localdate()
    thirty_days_later = today + timedelta(days=30)

    for stock in pharmacy_stock:
        total_qty = StockRecord.objects.filter(
            current_location=pharmacy_dept,
            item=stock.item
        ).aggregate(total=Sum('quantity'))['total'] or 0

        if total_qty <= stock.item.reorder_level:
            if stock not in low_stock_items:
                low_stock_items.append(stock)

        if stock.expiry_date and stock.expiry_date <= thirty_days_later:
            expiring_soon_items.append(stock)

    # Get inventory requests for Mini Pharmacy
    inventory_requests_all = InventoryRequest.objects.filter(
        location=pharmacy_dept
    ).select_related('item', 'requested_by').order_by('-requested_at')

    if request_search:
        inventory_requests_all = inventory_requests_all.filter(
            Q(item__name__icontains=request_search) |
            Q(requested_by__first_name__icontains=request_search) |
            Q(requested_by__last_name__icontains=request_search)
        )

    pending_requests_count = inventory_requests_all.filter(status='Pending').count()
    inventory_requests = inventory_requests_all[:20]

    # Statistics
    stats = {
        'pending_prescriptions': len(pending_items) + len(pending_consumable_list),
        'opd_count': len(opd_groups),
        'low_stock_count': len(low_stock_items),
        'pending_requests': pending_requests_count,
        'dispensed_today': DispensedItem.objects.filter(
            department=pharmacy_dept,
            dispensed_at__range=(start_of_day, end_of_day)
        ).filter(_nurse_visit_q(request.user, prefix='visit__')).count(),
    }

    context = {
        'opd_groups': opd_groups,
        'pending_items': pending_items,
        'dispensed_items': dispensed_items,
        'pharmacy_stock': pharmacy_stock,
        'low_stock_items': low_stock_items,
        'expiring_soon_items': expiring_soon_items,
        'inventory_requests': inventory_requests,
        'stats': stats,
        'search_query': search_query,
        'stock_search': stock_search,
        'dispensed_search': dispensed_search,
        'request_search': request_search,
        'filter_date': filter_date,
        'debug_info': {
            'total_pending_all_dates': pending_items_all.count(),
            'after_python_date_filter': len(pending_items),
            'consumables_count': len(pending_consumable_list),
            'filter_date': filter_date,
            'tz_now': timezone.now(),
            'local_date': timezone.localdate(),
        },
        'pharmacy_dept': pharmacy_dept,
        'today_plus_30': today + timedelta(days=30),
    }

    return render(request, 'home/night_pharmacy_dashboard.html', context)


def _normalize_night_payment_method(method):
    """Night shift accepts Cash and M-Pesa only."""
    key = (method or '').strip().lower().replace('_', '-')
    if key == 'cash':
        return 'Cash'
    if key in ('mpesa', 'm-pesa'):
        return 'M-Pesa'
    return None


@login_required
@transaction.atomic
@require_http_methods(["POST"])
def night_pharmacy_record_payment(request, invoice_id):
    """Record Cash / M-Pesa payment from the night pharmacy dashboard."""
    from decimal import Decimal

    if request.user.role not in ['Nurse', 'Admin', 'Pharmacist']:
        return JsonResponse({'success': False, 'error': 'Unauthorized role.'})

    invoice = get_object_or_404(Invoice, pk=invoice_id)
    if invoice.status == 'Cancelled':
        return JsonResponse({'success': False, 'error': 'This invoice has been cancelled.'})
    if not invoice.visit:
        return JsonResponse({'success': False, 'error': 'Invoice is not linked to a visit.'})
    if str(invoice.visit.visit_type).upper() == 'IN-PATIENT':
        return JsonResponse({'success': False, 'error': 'Night pharmacy only handles OPD visits.'})

    if invoice.status == 'Paid' or invoice.balance <= Decimal('0.01'):
        return JsonResponse({
            'success': True,
            'message': 'Invoice is already fully paid.',
            'invoice_status': invoice.status,
            'all_payment_ids': [],
        })

    try:
        data = json.loads(request.body)
        payments_data = data.get('payments', [])
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid payment data.'})

    if not payments_data:
        return JsonResponse({'success': False, 'error': 'No payment amounts provided.'})

    balance_due = invoice.balance
    parsed_payments = []
    total_paid = Decimal('0')

    try:
        for p_data in payments_data:
            amount_val = p_data.get('amount')
            if amount_val is None or Decimal(str(amount_val)) <= 0:
                continue

            method = _normalize_night_payment_method(
                p_data.get('method') or p_data.get('payment_method')
            )
            if not method:
                return JsonResponse({
                    'success': False,
                    'error': 'Night pharmacy only accepts Cash and M-Pesa payments.',
                })

            amount = Decimal(str(amount_val))
            total_paid += amount
            parsed_payments.append({
                'amount': amount,
                'method': method,
                'reference': p_data.get('reference') or '',
            })

        if not parsed_payments:
            return JsonResponse({'success': False, 'error': 'No valid payment amounts provided.'})

        if total_paid + Decimal('0.01') < balance_due:
            return JsonResponse({
                'success': False,
                'error': (
                    f'Payment incomplete. Received Ksh {total_paid:,.2f}; '
                    f'balance due Ksh {balance_due:,.2f}.'
                ),
            })

        payment_objs = [
            Payment(
                invoice=invoice,
                amount=p['amount'],
                payment_method=p['method'],
                transaction_reference=p['reference'],
                notes='Night pharmacy payment',
                created_by=request.user,
            )
            for p in parsed_payments
        ]
        created_payments = Payment.objects.bulk_create(payment_objs)
        invoice.distribute_payments()
        invoice.refresh_from_db()

        payment_ids = [p.id for p in created_payments if p.id]
        return JsonResponse({
            'success': True,
            'message': 'Payment recorded successfully.',
            'invoice_status': invoice.status,
            'invoice_id': invoice.id,
            'visit_id': invoice.visit_id,
            'payment_id': payment_ids[0] if payment_ids else None,
            'all_payment_ids': payment_ids,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@transaction.atomic
@require_http_methods(["POST"])
def dispense_night_opd_items(request, visit_id):
    """
    Dispense ALL pending items (medications + consumables) for a visit at night.
    Deducts stock from Mini Pharmacy.
    """
    from accounts.models import Invoice, InvoiceItem
    from inventory.models import StockAdjustment, DispensedItem
    from inpatient.models import Admission

    try:
        visit = get_object_or_404(Visit, pk=visit_id)
        patient = visit.patient
        
        # Role-based validation
        if request.user.role not in ['Nurse', 'Admin', 'Pharmacist']:
            return JsonResponse({'success': False, 'error': 'Unauthorized role.'})
            
        # Determine if IPD or OPD
        is_ipd = Admission.objects.filter(visit=visit, status='Admitted').exists()
        if is_ipd:
            return JsonResponse({'success': False, 'error': 'This page only handles OPD dispensing.'})

        # Use Mini Pharmacy department for stock deduction
        pharmacy_dept = get_object_or_404(Departments, name='Mini Pharmacy')

        # ---- Gather pending items ----
        # 1. Prescription medications (PrescriptionItem)
        pending_meds = PrescriptionItem.objects.filter(
            prescription__visit=visit,
            dispensed=False,
        ).select_related('medication', 'prescription__invoice', 'prescription__patient')

        # 2. Pending consumables
        pending_consumable_items = InvoiceItem.objects.filter(
            invoice__visit=visit,
            inventory_item__isnull=False,
        ).select_related('inventory_item', 'invoice')

        # Robust De-duplication for Consumables:
        # Calculate total quantity already dispensed for each item in this visit
        from django.db.models import Sum
        dispensed_totals = {
            item_id: total_qty for item_id, total_qty in 
            DispensedItem.objects.filter(visit=visit).values_list('item_id').annotate(total=Sum('quantity'))
        }

        pending_consumables = []
        accounted_for_dispensed = dispensed_totals.copy()

        for ci in pending_consumable_items:
            item_id = ci.inventory_item_id
            qty_needed = ci.quantity
            
            # 1. Skip if already covered by a prescription item (to prevent double billing/dispensing)
            if any(pm.medication_id == item_id and pm.quantity == qty_needed for pm in pending_meds):
                continue
            
            # 2. Check if this specific quantity has already been dispensed
            already_dispensed = accounted_for_dispensed.get(item_id, 0)
            if already_dispensed >= qty_needed:
                accounted_for_dispensed[item_id] -= qty_needed
                continue
            elif already_dispensed > 0:
                ci.quantity -= already_dispensed
                accounted_for_dispensed[item_id] = 0
                
            pending_consumables.append(ci)

        total_pending = pending_meds.count() + len(pending_consumables)
        if total_pending == 0:
            return JsonResponse({
                'success': False,
                'error': 'No pending items found for this visit.'
            })

        # ---- OPD: Check payment ----
        invoices = Invoice.objects.filter(visit=visit).exclude(status='Cancelled')
        unpaid = invoices.exclude(status='Paid')
        if unpaid.exists():
            inv_ids = ', '.join([f'INV-{inv.id}' for inv in unpaid])
            return JsonResponse({
                'success': False,
                'error': f'Payment required. Unpaid invoices: {inv_ids}'
            })

        dispensed_count = 0
        errors = []

        # ---- Dispense medications ----
        for med in pending_meds:
            # Check stock (FEFO)
            stock_records = StockRecord.objects.filter(
                current_location=pharmacy_dept,
                item=med.medication,
                quantity__gt=0
            ).order_by('expiry_date').select_for_update()

            total_available = sum(r.quantity for r in stock_records)
            if total_available < med.quantity:
                errors.append(f'Insufficient stock for {med.medication.name} (need {med.quantity}, have {total_available})')
                continue

            # Deduct stock FEFO
            remaining = med.quantity
            for record in stock_records:
                if remaining <= 0:
                    break
                take = min(record.quantity, remaining)
                record.quantity -= take
                record.save()
                StockAdjustment.objects.create(
                    item=med.medication,
                    quantity=-take,
                    adjustment_type='Usage',
                    reason=f'Dispensed to {patient.full_name} (Visit {visit.id}) via Night Pharmacy',
                    adjusted_by=request.user,
                    adjusted_from=pharmacy_dept,
                )
                remaining -= take

            # Mark as dispensed (+ DHA pack code snapshot)
            from accounts.sha_claims_service import mark_rx_item_dispensed
            mark_rx_item_dispensed(med, request.user)

            DispensedItem.objects.create(
                item=med.medication,
                patient=patient,
                visit=visit,
                quantity=med.quantity,
                dispensed_by=request.user,
                department=pharmacy_dept,
            )
            dispensed_count += 1

        # ---- Dispense consumables ----
        for ci in pending_consumables:
            item = ci.inventory_item
            qty = ci.quantity

            # Check stock (FEFO)
            stock_records = StockRecord.objects.filter(
                current_location=pharmacy_dept,
                item=item,
                quantity__gt=0
            ).order_by('expiry_date').select_for_update()

            total_available = sum(r.quantity for r in stock_records)
            if total_available < qty:
                errors.append(f'Insufficient stock for {item.name} (need {qty}, have {total_available})')
                continue

            # Deduct stock FEFO
            remaining = qty
            for record in stock_records:
                if remaining <= 0:
                    break
                take = min(record.quantity, remaining)
                record.quantity -= take
                record.save()
                StockAdjustment.objects.create(
                    item=item,
                    quantity=-take,
                    adjustment_type='Usage',
                    reason=f'Consumable dispensed to {patient.full_name} (Visit {visit.id}) via Night Pharmacy',
                    adjusted_by=request.user,
                    adjusted_from=pharmacy_dept,
                )
                remaining -= take

            DispensedItem.objects.create(
                item=item,
                patient=patient,
                visit=visit,
                quantity=qty,
                dispensed_by=request.user,
                department=pharmacy_dept,
            )
            dispensed_count += 1

        if dispensed_count == 0:
            return JsonResponse({
                'success': False,
                'error': '; '.join(errors) if errors else 'No items could be dispensed'
            })

        message = f'Successfully dispensed {dispensed_count} items.'
        if errors:
            message += f' Warnings: {"; ".join(errors)}'

        return JsonResponse({
            'success': True,
            'message': message,
            'dispensed_count': dispensed_count
        })

    except Departments.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Mini Pharmacy department not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def appointments_dashboard(request):
    """
    Dashboard for Doctors to view Appointments
    Shows analytics and a schedule of appointments
    """
    today = timezone.localdate()
    now = timezone.now()
    start_of_day = timezone.make_aware(datetime.combine(today, time.min))
    end_of_day = timezone.make_aware(datetime.combine(today, time.max))

    appointments = Appointments.objects.select_related(
        'patient', 'created_by'
    ).order_by('appointment_date')

    today_appointments = appointments.filter(
        appointment_date__range=(start_of_day, end_of_day)
    )
    todays_count = today_appointments.count()

    upcoming_appointments = appointments.filter(
        appointment_date__gt=now,
        is_completed=False,
    )
    upcoming_count = upcoming_appointments.count()

    missed_appointments = appointments.filter(
        appointment_date__lt=now,
        is_completed=False,
    )
    missed_count = missed_appointments.count()

    completed_appointments = appointments.filter(is_completed=True)
    completed_count = completed_appointments.count()

    next_24h = now + timedelta(hours=24)
    next_48h = now + timedelta(hours=48)

    filter_type = request.GET.get('filter', 'today')
    if filter_type == 'upcoming':
        display_appointments = upcoming_appointments
    elif filter_type == '24h':
        display_appointments = upcoming_appointments.filter(appointment_date__lte=next_24h)
    elif filter_type == '48h':
        display_appointments = upcoming_appointments.filter(appointment_date__lte=next_48h)
    elif filter_type == 'missed':
        display_appointments = missed_appointments
    elif filter_type == 'completed':
        display_appointments = completed_appointments
    elif filter_type == 'all':
        display_appointments = appointments
    else:
        filter_type = 'today'
        display_appointments = today_appointments

    search_query = (request.GET.get('search') or '').strip()
    if search_query:
        display_appointments = display_appointments.filter(
            Q(patient__first_name__icontains=search_query)
            | Q(patient__last_name__icontains=search_query)
            | Q(patient__id_number__icontains=search_query)
            | Q(patient__phone__icontains=search_query)
            | Q(appointment_type__icontains=search_query)
        )

    if filter_type in ('missed', 'completed', 'all'):
        display_appointments = display_appointments.order_by('-appointment_date')
    else:
        display_appointments = display_appointments.order_by('appointment_date')

    paginator = Paginator(display_appointments, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    filter_labels = {
        'today': "Today's appointments",
        'upcoming': 'Upcoming appointments',
        '24h': 'Next 24 hours',
        '48h': 'Next 48 hours',
        'missed': 'Missed appointments',
        'completed': 'Completed appointments',
        'all': 'All appointments',
    }

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'filter_type': filter_type,
        'filter_label': filter_labels.get(filter_type, 'Appointments'),
        'todays_count': todays_count,
        'upcoming_count': upcoming_count,
        'missed_count': missed_count,
        'completed_count': completed_count,
        'today': today,
        'now': now,
    }

    return render(request, 'home/appointments_dashboard.html', context)

@login_required
def opd_dashboard(request):
    """
    Dashboard for Outpatient Department (Doctors)
    Shows analytics and waiting patient queue
    """
    from datetime import datetime, time
    
    date_str = request.GET.get('date')
    if date_str:
        try:
            today = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            today = timezone.localdate()
    else:
        today = timezone.localdate()
    
    start_of_day = timezone.make_aware(datetime.combine(today, time.min))
    end_of_day = timezone.make_aware(datetime.combine(today, time.max))
    
    # Total "Walk In" or "Appointment" visits today
    todays_visits_count = Visit.objects.filter(
        visit_date__range=(start_of_day, end_of_day),
        visit_type='OUT-PATIENT',
    ).filter(_nurse_visit_q(request.user)).count()
    
    # Waiting Patients (In queue for Consultation rooms)
    # Filter departments that look like consultation rooms and are PENDING
    # Strictly filter for OUT-PATIENT visits to exclude admitted (IPD) patients
    consultation_queues = PatientQue.objects.filter(
        sent_to__name__icontains='Consultation',
        status='PENDING',
        visit__is_active=True,
        visit__visit_type='OUT-PATIENT',
        visit__visit_date__range=(start_of_day, end_of_day),
    ).filter(_nurse_visit_q(request.user, prefix='visit__')).select_related('visit__patient', 'sent_to', 'qued_from')

    # Apply Search Filter
    search_query = request.GET.get('q')
    if search_query:
        consultation_queues = consultation_queues.filter(
            Q(visit__patient__first_name__icontains=search_query) |
            Q(visit__patient__last_name__icontains=search_query) |
            Q(visit__patient__id_number__icontains=search_query) |
            Q(visit__patient__phone__icontains=search_query)
        )
    
    waiting_count = consultation_queues.count()

    
    # Priority Distribution from Triage Entries linked to today's visits
    triage_today = TriageEntry.objects.filter(
        visit__visit_date__range=(start_of_day, end_of_day),
    ).filter(_nurse_visit_q(request.user, prefix='visit__'))
    critical_count = triage_today.filter(priority__in=['URGENT', 'CRITICAL']).count()
    
    # 2. The Queue Data
    # Enrich queue items with triage info
    queue_list = []
    
    # Order by priority (requires join/subquery logic or python sorting)
    # Let's fetch all and sort in python for flexibility
    for item in consultation_queues.order_by('-created_at'):
        # Get latest triage for this visit
        triage = TriageEntry.objects.filter(visit=item.visit).order_by('-entry_date').first()
        
        # Check if patient has visited before today
        has_previous_visit = Visit.objects.filter(
            patient=item.visit.patient, 
            visit_date__lt=start_of_day
        ).exists()
        
        queue_list.append({
            'queue_id': item.id,
            'patient': item.visit.patient,
            'visit': item.visit,
            'sent_to': item.sent_to.name if item.sent_to else 'General OPD',
            'queued_at': item.created_at,
            'queue_type': item.queue_type,
            'is_revisit': has_previous_visit,
            'wait_time': None, # Can calculate relative time in template
            'triage': triage,
            'priority_rank': 0 if not triage else {
                'CRITICAL': 5, 'URGENT': 4, 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1
            }.get(triage.priority, 0),
            'type_rank': 1 if item.queue_type == 'REVIEW' else 0
        })
    
    # Sort by Priority (High to Low), then by Type (Review first), then by Visit Date (Oldest first)
    queue_list.sort(key=lambda x: (-x['priority_rank'], -x['type_rank'], x['visit'].visit_date))
    
    # Deduplicate by visit - keep the first one encountered (which is the highest priority/rank)
    deduplicated_queue = []
    seen_visits = set()
    for item in queue_list:
        if item['visit'].id not in seen_visits:
            deduplicated_queue.append(item)
            seen_visits.add(item['visit'].id)
    
    context = {
        'todays_visits_count': todays_visits_count,
        'waiting_count': len(deduplicated_queue),
        'critical_count': critical_count,
        'queue_list': deduplicated_queue,
        'today': today,
    }
    
    # Get recent consultations for history list
    recent_consultations = Consultation.objects.filter(
        doctor=request.user,
        visit__visit_date__range=(start_of_day, end_of_day),
    ).filter(_nurse_visit_q(request.user, prefix='visit__')).select_related('visit__patient').order_by('-checkin_date')[:5]
    context['recent_consultations'] = recent_consultations
    
    return render(request, 'home/opd_dashboard.html', context)

@login_required
def procedure_room_dashboard(request):
    """Dashboard for Procedure Room to view requested procedures"""
    # Procedure requests are invoice items linked to Procedure Room services.
    service_items = InvoiceItem.objects.filter(
        service__isnull=False,
        service__department__name='Procedure Room',
        invoice__visit__isnull=False,
        invoice__visit__is_active=True,
    ).select_related('invoice', 'invoice__patient', 'service', 'service__department')
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        service_items = service_items.filter(
            Q(invoice__patient__first_name__icontains=search_query) |
            Q(invoice__patient__last_name__icontains=search_query) |
            Q(service__name__icontains=search_query) |
            Q(name__icontains=search_query)
        )
    
    # Order by most recent
    service_items = service_items.order_by('-created_at')

    completed_item_ids = set(
        ProcedureCompletion.objects.filter(invoice_item__in=service_items).values_list('invoice_item_id', flat=True)
    )

    visits_map = {}
    for item in service_items:
        visit = item.invoice.visit
        if visit.id not in visits_map:
            visits_map[visit.id] = {
                'visit': visit,
                'patient': item.invoice.patient,
                'requested_at': item.created_at,
                'procedures': [],
                'total_count': 0,
                'done_count': 0,
            }

        is_done = item.id in completed_item_ids
        visits_map[visit.id]['procedures'].append({
            'id': item.id,
            'name': item.name,
            'unit_price': item.unit_price,
            'created_at': item.created_at,
            'is_done': is_done,
            'is_settled': item.is_settled or item.invoice.status == 'Paid',
        })
        visits_map[visit.id]['total_count'] += 1
        if is_done:
            visits_map[visit.id]['done_count'] += 1

    visit_groups = []
    for data in visits_map.values():
        total = data['total_count']
        done = data['done_count']
        data['pending_count'] = total - done
        data['progress_percent'] = int((done / total) * 100) if total else 0
        data['all_settled'] = all(proc['is_settled'] for proc in data['procedures']) if data['procedures'] else False
        visit_groups.append(data)

    visit_groups.sort(key=lambda x: x['requested_at'], reverse=True)

    # Pagination by visit group (not individual procedure rows)
    paginator = Paginator(visit_groups, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'total_requests': service_items.count(),
        'total_done': len(completed_item_ids),
        'procedure_room_stock_requests': InventoryRequest.objects.filter(
            location__name='Procedure Room'
        ).select_related('item', 'requested_by', 'location').order_by('-requested_at')[:15],
        'title': 'Procedure Room Dashboard'
    }
    return render(request, 'home/procedure_room_dashboard.html', context)

@login_required
def procedure_detail(request, visit_id):
    """Detail view for procedure requests for a specific visit"""
    visit = get_object_or_404(Visit, id=visit_id)
    patient = visit.patient
    
    # Get all procedure items for this visit
    procedures = InvoiceItem.objects.filter(
        invoice__visit=visit,
        service__isnull=False,
        service__department__name='Procedure Room',
    ).select_related('invoice', 'service', 'service__department').order_by('created_at')
    
    completion_map = {
        completion.invoice_item_id: completion
        for completion in ProcedureCompletion.objects.filter(invoice_item__in=procedures).select_related('completed_by')
    }

    procedure_rows = [
        {
            'item': item,
            'completion': completion_map.get(item.id),
            'is_done': item.id in completion_map,
        }
        for item in procedures
    ]

    # Get dispensed items history for this visit
    from inventory.models import DispensedItem
    dispensed_items = DispensedItem.objects.filter(visit=visit).select_related('item', 'dispensed_by').order_by('-dispensed_at')
        
    context = {
        'procedures': procedures,
        'procedure_rows': procedure_rows,
        'patient': patient,
        'visit': visit,
        'dispensed_items': dispensed_items,
        'dispensing_departments': Departments.objects.all().order_by('name'),
        'title': f'Procedures: {patient.full_name}'
    }
    return render(request, 'home/procedure_detail.html', context)


@login_required
@require_http_methods(["POST"])
def mark_procedure_done(request, item_id):
    procedure_item = get_object_or_404(
        InvoiceItem.objects.select_related('invoice__visit', 'service__department'),
        pk=item_id,
        service__isnull=False,
        service__department__name='Procedure Room',
        invoice__visit__isnull=False,
    )

    completion, created = ProcedureCompletion.objects.get_or_create(
        invoice_item=procedure_item,
        defaults={
            'visit': procedure_item.invoice.visit,
            'completed_by': request.user,
            'notes': request.POST.get('completion_notes', '').strip(),
        },
    )

    if created:
        messages.success(request, f"Marked '{procedure_item.name}' as done.")
    else:
        messages.info(request, f"'{procedure_item.name}' was already marked as done.")

    return redirect('home:procedure_detail', visit_id=procedure_item.invoice.visit.id)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def ambulance_dashboard(request):
    """
    Dashboard for Ambulance Usage and Revenue Analysis
    """
    from lab.models import AmbulanceActivity, AmbulanceCharge
    from accounts.models import Invoice, InvoiceItem
    from django.db.models.functions import TruncDate
    from django.db.models import Count, Sum
    from datetime import timedelta
    from django.utils import timezone
    import json

    # Handle New Trip Creation / New Route
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_route':
            try:
                route_form = AmbulanceRouteForm(request.POST)
                if route_form.is_valid():
                    route_form.save()
                    messages.success(request, 'New ambulance route added successfully.')
                else:
                    messages.error(request, 'Error adding route. Please check the form.')
            except Exception as e:
                messages.error(request, f'Error creating route: {str(e)}')
            return redirect('home:ambulance_dashboard')
            
        try:
            patient_id = request.POST.get('patient')
            route_id = request.POST.get('route')
            driver = request.POST.get('driver')
            notes = request.POST.get('notes')
            
            patient = get_object_or_404(Patient, pk=patient_id)
            route = get_object_or_404(AmbulanceCharge, pk=route_id)
            
            # Get or Create Visit Invoice (Consolidated) - use latest active visit if possible
            visit = Visit.objects.filter(patient=patient, is_active=True).last()
            invoice = get_or_create_invoice(visit=visit, user=request.user)
            if not invoice:
                # Fallback for visit-less invoice
                invoice = Invoice.objects.create(
                    patient=patient,
                    status='Pending',
                    created_by=request.user,
                    notes=f"Ambulance Trip: {route.from_location} to {route.to_location}"
                )
            else:
                if invoice.notes:
                    invoice.notes += f"\nAmbulance Trip: {route.from_location} to {route.to_location}"
                else:
                    invoice.notes = f"Ambulance Trip: {route.from_location} to {route.to_location}"
                invoice.save()
            
            # Create Invoice Item
            InvoiceItem.objects.create(
                invoice=invoice,
                name=f"Ambulance: {route.from_location} to {route.to_location}",
                quantity=1,
                unit_price=route.price
            )
            invoice.update_totals()
            
            # Record Activity
            AmbulanceActivity.objects.create(
                patient=patient,
                route=route,
                driver=driver,
                invoice=invoice,
                amount=route.price,
                notes=notes
            )
            messages.success(request, 'Ambulance trip recorded successfully.')
        except Exception as e:
            messages.error(request, f'Error creating trip: {str(e)}')
            
        return redirect('home:ambulance_dashboard')

    # Fetch Data
    today = timezone.localdate()
    start_of_day = timezone.make_aware(datetime.combine(today, time.min))
    end_of_day = timezone.make_aware(datetime.combine(today, time.max))

    start_date = today - timedelta(days=30)
    
    # Summary Stats
    total_trips = AmbulanceActivity.objects.count()
    total_revenue = AmbulanceActivity.objects.aggregate(total=Sum('amount'))['total'] or 0
    trips_today = AmbulanceActivity.objects.filter(date__range=(start_of_day, end_of_day)).count()
    revenue_today = AmbulanceActivity.objects.filter(
        date__range=(start_of_day, end_of_day)
    ).aggregate(total=Sum('amount'))['total'] or 0
    trips_30d = AmbulanceActivity.objects.filter(date__date__gte=start_date).count()
    revenue_30d = AmbulanceActivity.objects.filter(
        date__date__gte=start_date
    ).aggregate(total=Sum('amount'))['total'] or 0
    pending_trips = AmbulanceActivity.objects.exclude(invoice__status='Paid').count()
    paid_trips = AmbulanceActivity.objects.filter(invoice__status='Paid').count()
    avg_trip = (total_revenue / total_trips) if total_trips else 0
    route_count = AmbulanceCharge.objects.count()

    hour = timezone.localtime().hour
    if hour < 12:
        greeting = 'Good morning'
    elif hour < 17:
        greeting = 'Good afternoon'
    else:
        greeting = 'Good evening'
    
    # Recent trip activity for the table
    activities = (
        AmbulanceActivity.objects.all()
        .select_related('patient', 'route', 'invoice')
        .order_by('-date')[:20]
    )

    # Routes for Dropdown
    routes = AmbulanceCharge.objects.all()
    
    # Patients for Dropdown (Limit to 50 recent)
    patients = Patient.objects.all().order_by('-updated_at')[:50]

    # Chart Data (Last 30 Days)
    chart_qs = AmbulanceActivity.objects.filter(date__date__gte=start_date)\
        .annotate(day=TruncDate('date'))\
        .values('day')\
        .annotate(count=Count('id'), revenue=Sum('amount'))\
        .order_by('day')
        
    dates = []
    counts = []
    revenues = []
    
    # Create dictionary for quick lookup
    # Need to handle date/datetime comparison carefully
    chart_data_dict = {}
    for item in chart_qs:
        d_val = item['day']
        if hasattr(d_val, 'strftime'):
             key = d_val.strftime('%Y-%m-%d')
        else:
             key = str(d_val)
        chart_data_dict[key] = item
    
    # Fill in all days for smooth chart
    for i in range(30):
        d = start_date + timedelta(days=i)
        d_str = d.strftime('%Y-%m-%d')
        # item = chart_data_dict.get(d_str, {'count': 0, 'revenue': 0})
        # Handle lookup logic
        item = None
        if d_str in chart_data_dict:
            item = chart_data_dict[d_str]
        else:
            item = {'count': 0, 'revenue': 0}
            
        dates.append(d.strftime('%b %d'))
        counts.append(item['count'])
        revenues.append(float(item['revenue'] or 0))

    context = {
        'greeting': greeting,
        'range_start': start_date,
        'range_end': today,
        'total_trips': total_trips,
        'total_revenue': total_revenue,
        'trips_today': trips_today,
        'revenue_today': revenue_today,
        'trips_30d': trips_30d,
        'revenue_30d': revenue_30d,
        'pending_trips': pending_trips,
        'paid_trips': paid_trips,
        'avg_trip': avg_trip,
        'route_count': route_count,
        'activities': activities,
        'routes': routes,
        'patients': patients,
        'route_form': AmbulanceRouteForm(),
        'chart_labels': json.dumps(dates),
        'chart_counts': json.dumps(counts),
        'chart_revenues': json.dumps(revenues),
    }
    
    return render(request, 'home/ambulance_dashboard.html', context)

@login_required
def ward_management(request):
    """View to list all wards and their bed counts"""
    from inpatient.models import Ward, Bed
    from .forms import WardForm, BedForm
    wards = Ward.objects.prefetch_related('beds').all()
    ward_form = WardForm()
    bed_form = BedForm()
    
    from accounts.sha_hie_service import get_sha_bed_occupancy
    sha_bed_occupancy = get_sha_bed_occupancy()

    context = {
        'wards': wards,
        'ward_form': ward_form,
        'bed_form': bed_form,
        'sha_bed_occupancy': sha_bed_occupancy,
    }
    return render(request, 'home/ward_management.html', context)


@login_required
@require_http_methods(['POST'])
def add_ward(request):
    """View to handle adding a new ward"""
    from .forms import WardForm
    form = WardForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, 'Ward added successfully.')
        return redirect('home:ward_management')
    
    messages.error(request, 'Failed to add ward. Please check the form.')
    return redirect('home:ward_management')

@login_required
@require_http_methods(['POST'])
def add_bed(request):
    """View to handle adding a new bed to a ward"""
    from .forms import BedForm
    form = BedForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, 'Bed added successfully.')
        return redirect('home:ward_management')
    
    messages.error(request, 'Failed to add bed. Please check the form.')
    return redirect('home:ward_management')


@login_required
def add_appointment(request):
    """View to handle appointment booking via AJAX"""
    if request.user.role not in ['Doctor', 'Nurse', 'Receptionist', 'Admin']:
        return JsonResponse({'success': False, 'error': 'Unauthorized action.'})
    
    if request.method == 'POST':
        try:
            patient_id = request.POST.get('patient_id')
            patient = get_object_or_404(Patient, pk=patient_id)
            
            form = AppointmentForm(request.POST)
            if form.is_valid():
                appointment = form.save(commit=False)
                appointment.patient = patient
                appointment.created_by = request.user
                appointment.save()
                
                return JsonResponse({
                    'success': True, 
                    'message': f'Appointment booked for {patient.full_name} on {appointment.appointment_date.strftime("%M %d, %Y at %H:%M")}'
                })
            else:
                return JsonResponse({'success': False, 'error': form.errors.as_text()})
                
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
def mark_appointment_attended(request, appointment_id):
    """Marks an appointment as completed and redirects to patient detail"""
    appointment = get_object_or_404(Appointments, id=appointment_id)
    appointment.is_completed = True
    appointment.updated_by = request.user
    appointment.save()
    
    messages.success(request, f"Appointment for {appointment.patient.full_name} marked as attended.")
    return redirect('home:patient_detail', pk=appointment.patient.pk)


@login_required
def patient_search_api(request):
    """Simple patient search API returning JSON results."""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    patients = Patient.objects.filter(
        Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(id_number__icontains=q)
    )[:15]
    results = [{
        'id': p.id,
        'name': p.full_name,
        'id_number': p.id_number or '',
        'phone': p.phone or '',
    } for p in patients]
    return JsonResponse({'results': results})


def can_use_icd11(user):
    return user.is_authenticated and (
        user.is_superuser
        or user.role in ['Doctor', 'Nurse', 'Admin', 'SHA Manager']
    )


def can_use_terminology(user):
    """AfyaConnect LOINC / ICHI / concepts search (clinical coding + service catalog)."""
    return user.is_authenticated and (
        user.is_superuser
        or user.role in [
            'Doctor', 'Nurse', 'Admin', 'SHA Manager', 'Accountant', 'Lab Technician',
        ]
    )


@login_required
@user_passes_test(can_use_icd11)
def icd11_search_page(request):
    """Simple UI for WHO ICD-11 code search."""
    from django.conf import settings as django_settings
    from .icd11_local import local_icd11_count

    local_count = local_icd11_count()
    return render(request, 'home/icd11_search.html', {
        'release': django_settings.ICD11_RELEASE,
        'linearization': django_settings.ICD11_LINEARIZATION,
        'language': django_settings.ICD11_LANGUAGE,
        'has_credentials': bool(
            django_settings.ICD11_CLIENT_ID and django_settings.ICD11_CLIENT_SECRET
        ),
        'uses_local_db': django_settings.ICD11_USE_LOCAL_DB,
        'local_count': local_count,
        'has_local_data': local_count > 0,
    })


@login_required
@user_passes_test(can_use_icd11)
def icd11_search_api(request):
    """GET /home/api/icd11/search/?q=diabetes — local DB only."""
    from django.conf import settings as django_settings
    from .icd11_local import local_icd11_count, search_icd11_local

    query = (request.GET.get('q') or request.GET.get('query') or '').strip()
    if not query:
        return JsonResponse({'success': False, 'error': 'q is required.'}, status=400)

    if local_icd11_count() == 0:
        return JsonResponse({
            'success': False,
            'error': 'ICD-11 database is empty. Run `python manage.py sync_icd11` on the server.',
        }, status=503)

    try:
        payload = search_icd11_local(query, limit=25)
        results = payload.get('results') or []
        return JsonResponse({
            'success': True,
            'query': payload.get('query'),
            'release': payload.get('release') or django_settings.ICD11_RELEASE,
            'linearization': payload.get('linearization') or django_settings.ICD11_LINEARIZATION,
            'source': 'local',
            'count': len(results),
            'results': results,
        })
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@login_required
@user_passes_test(can_use_icd11)
def icd11_validate_api(request):
    """
    GET /home/api/icd11/validate/?code=BA00&title=Essential%20hypertension

    Cross-checks a locally selected ICD-11 code against DHA terminology:
    still supported, and title unchanged.
    """
    from .icd11_diagnosis import cross_check_icd11_with_dha

    code = (request.GET.get('code') or '').strip()
    title = (request.GET.get('title') or '').strip()
    if not code:
        return JsonResponse({'success': False, 'error': 'code is required.'}, status=400)

    try:
        payload = cross_check_icd11_with_dha(code, local_title=title or None)
        http_status = 200
        if not payload.get('success'):
            status = payload.get('status')
            if status in ('not_in_local_db', 'not_supported_by_dha', 'title_changed'):
                http_status = 409
            elif status == 'dha_unavailable':
                http_status = 502
        return JsonResponse(payload, status=http_status)
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@login_required
@user_passes_test(can_use_icd11)
def icd11_entity_api(request):
    """GET /home/api/icd11/entity/?id=257068234"""
    from .icd11_service import (
        Icd11ConfigError,
        Icd11RequestError,
        get_icd11_entity,
    )

    entity_ref = (request.GET.get('id') or request.GET.get('uri') or '').strip()
    if not entity_ref:
        return JsonResponse({'success': False, 'error': 'id or uri is required.'}, status=400)

    try:
        payload = get_icd11_entity(entity_ref)
        return JsonResponse({'success': True, **payload})
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Icd11ConfigError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=503)
    except Icd11RequestError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=502)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@login_required
@user_passes_test(can_use_icd11)
def icd11_code_api(request):
    """GET /home/api/icd11/code/?code=1A00"""
    from .icd11_service import (
        Icd11ConfigError,
        Icd11RequestError,
        get_icd11_code_info,
    )

    code = (request.GET.get('code') or '').strip()
    if not code:
        return JsonResponse({'success': False, 'error': 'code is required.'}, status=400)

    try:
        payload = get_icd11_code_info(code)
        return JsonResponse({'success': True, **payload})
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Icd11ConfigError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=503)
    except Icd11RequestError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=502)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@login_required
def hpt_search_api(request):
    """
    GET /home/api/hpt/search/?q=metformin+500&prefer=ge

    Search DHA MOH-PPB HPT terminology for medication concepts.
    """
    from .dha_medication import search_dha_medications

    query = (request.GET.get('q') or request.GET.get('search') or '').strip()
    if not query:
        return JsonResponse({'success': False, 'error': 'q is required.'}, status=400)

    prefer = (request.GET.get('prefer') or 'ge').strip().lower()
    prefer_generic = prefer in ('ge', 'generic', '1', 'true', 'yes')
    try:
        limit = int(request.GET.get('limit') or 25)
    except ValueError:
        limit = 25

    try:
        payload = search_dha_medications(
            query,
            limit=max(1, min(limit, 50)),
            prefer_generic=prefer_generic,
        )
        status = 200 if payload.get('success') else 502
        return JsonResponse(payload, status=status)
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@login_required
def hpt_suggest_api(request):
    """
    GET /home/api/hpt/suggest/?name=...&generic_name=...&formulation=...&code=...

    Suggest or verify DHA generic product codes after selecting a local inventory drug.
    """
    from .dha_medication import suggest_dha_for_local_drug

    name = (request.GET.get('name') or '').strip()
    generic_name = (request.GET.get('generic_name') or '').strip()
    formulation = (request.GET.get('formulation') or '').strip()
    code = (request.GET.get('code') or request.GET.get('generic_concept_code') or '').strip()

    if not (name or generic_name or code):
        return JsonResponse(
            {'success': False, 'error': 'name, generic_name, or code is required.'},
            status=400,
        )

    try:
        payload = suggest_dha_for_local_drug(
            name=name,
            generic_name=generic_name,
            formulation=formulation,
            concept_code=code,
        )
        status = 200 if payload.get('success') else 502
        return JsonResponse(payload, status=status)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@login_required
def sha_preauth_check_api(request):
    """
    GET/POST /home/api/sha/preauth-check/

    Advisory check: do selected labs / meds need SHA preauth?
    Query/body: visit_id, service_ids[] / services, inventory_ids[] / medications
    """
    from accounts.models import Service
    from accounts.sha_preauth_check import (
        check_inventory_preauth,
        check_services_preauth,
    )
    from inventory.models import InventoryItem

    if request.method == 'POST':
        visit_id = request.POST.get('visit_id') or request.GET.get('visit_id')
        service_ids = request.POST.getlist('service_ids') or request.POST.getlist('services')
        inventory_ids = (
            request.POST.getlist('inventory_ids')
            or request.POST.getlist('medications')
            or request.POST.getlist('medication_ids')
        )
        if request.content_type and 'application/json' in request.content_type:
            try:
                body = json.loads(request.body.decode('utf-8') or '{}')
            except ValueError:
                body = {}
            visit_id = body.get('visit_id') or visit_id
            service_ids = body.get('service_ids') or body.get('services') or service_ids
            inventory_ids = (
                body.get('inventory_ids')
                or body.get('medications')
                or body.get('medication_ids')
                or inventory_ids
            )
    else:
        visit_id = request.GET.get('visit_id')
        service_ids = request.GET.getlist('service_ids') or request.GET.getlist('services')
        inventory_ids = (
            request.GET.getlist('inventory_ids')
            or request.GET.getlist('medications')
            or request.GET.getlist('medication_ids')
        )
        # Allow comma-separated
        if len(service_ids) == 1 and ',' in service_ids[0]:
            service_ids = [x.strip() for x in service_ids[0].split(',') if x.strip()]
        if len(inventory_ids) == 1 and ',' in inventory_ids[0]:
            inventory_ids = [x.strip() for x in inventory_ids[0].split(',') if x.strip()]

    if not visit_id:
        return JsonResponse({'success': False, 'error': 'visit_id is required.'}, status=400)

    visit = get_object_or_404(Visit, pk=visit_id)
    payload: dict = {
        'success': True,
        'visit_id': visit.pk,
        'labs': None,
        'medications': None,
    }

    try:
        if service_ids:
            services = list(Service.objects.filter(pk__in=service_ids))
            payload['labs'] = check_services_preauth(visit, services)
        if inventory_ids:
            invs = list(
                InventoryItem.objects.filter(pk__in=inventory_ids).select_related('medication')
            )
            payload['medications'] = check_inventory_preauth(visit, invs)

        # If neither provided, still return visit-level / empty check
        if not service_ids and not inventory_ids:
            payload['labs'] = check_services_preauth(visit, [])

        attention = False
        inform = []
        for key in ('labs', 'medications'):
            block = payload.get(key) or {}
            if block.get('requires_attention'):
                attention = True
            inform.extend(block.get('inform_patient') or [])

        payload['requires_attention'] = attention
        payload['inform_patient'] = inform
        payload['message'] = (
            f"{len(inform)} item(s) require SHA pre-authorization — inform the patient."
            if inform
            else 'No SHA pre-authorization required for the selection.'
        )
        return JsonResponse(payload)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


def _terminology_search_response(request, system: str):
    """
    LOINC / ICHI search: local TerminologyConcept DB first.
    If no local hits, seed from DHA Terminology Service into DB, then return.
    Selection confirmation is a separate validate endpoint.
    """
    from accounts.sha_hie_service import ShaHieConfigError, ShaHieRequestError
    from .terminology_local import (
        local_terminology_count,
        search_terminology_local,
        seed_from_dha,
    )

    query = (request.GET.get('q') or request.GET.get('search') or '').strip()
    if not query:
        return JsonResponse({'success': False, 'error': 'q is required.'}, status=400)
    try:
        limit = int(request.GET.get('limit') or 25)
    except ValueError:
        limit = 25
    limit = max(1, min(limit, 50))

    force_live = (request.GET.get('live') or '').strip().lower() in (
        '1', 'true', 'yes', 'force',
    )

    try:
        if system in ('loinc', 'ichi'):
            local = search_terminology_local(system, query, limit=limit)
            results = local.get('results') or []
            if results and not force_live:
                return JsonResponse({
                    'success': True,
                    'query': query,
                    'system': system,
                    'source': 'local',
                    'count': len(results),
                    'local_total': local_terminology_count(system),
                    'results': results,
                })

            # Empty local (or ?live=1): fetch DHA, cache, return local-shaped rows
            seeded = seed_from_dha(system, query, limit=limit)
            results = seeded.get('results') or []
            return JsonResponse({
                'success': True,
                'query': query,
                'system': system,
                'source': seeded.get('source') or 'local_after_dha_seed',
                'path': seeded.get('dha_path'),
                'seeded': seeded.get('seeded') or 0,
                'count': len(results),
                'local_total': local_terminology_count(system),
                'results': results,
            })

        # Generic concepts: ICD-11 prefers local Icd11Code DB
        owner = (request.GET.get('owner') or '').strip()
        source = (request.GET.get('source') or '').strip()
        if not owner or not source:
            return JsonResponse(
                {'success': False, 'error': 'owner and source are required.'},
                status=400,
            )
        if source.upper() in ('ICD-11', 'ICD11') or 'ICD-11' in source.upper():
            from .icd11_local import local_icd11_count, search_icd11_local

            if local_icd11_count() == 0:
                return JsonResponse({
                    'success': False,
                    'error': 'ICD-11 database is empty. Run `python manage.py sync_icd11`.',
                }, status=503)
            payload = search_icd11_local(query, limit=limit)
            results = payload.get('results') or []
            return JsonResponse({
                'success': True,
                'query': query,
                'system': 'icd11',
                'owner': owner,
                'source': 'local',
                'count': len(results),
                'results': results,
            })

        from accounts.sha_hie_service import ShaHieClient

        payload = ShaHieClient().search_concepts(
            query, owner=owner, source=source, limit=limit
        )
        results = payload.get('results') or []
        return JsonResponse({
            'success': True,
            'query': payload.get('query') or query,
            'system': system,
            'owner': payload.get('owner'),
            'source': payload.get('source') or 'dha',
            'path': payload.get('path'),
            'count': len(results),
            'results': results,
        })
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except ShaHieConfigError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=503)
    except ShaHieRequestError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=502)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


def _terminology_validate_response(request, system: str):
    """Confirm a locally selected LOINC/ICHI code is unchanged on DHA."""
    from .terminology_validate import cross_check_terminology_with_dha

    code = (request.GET.get('code') or '').strip()
    title = (request.GET.get('title') or '').strip()
    if not code:
        return JsonResponse({'success': False, 'error': 'code is required.'}, status=400)

    try:
        payload = cross_check_terminology_with_dha(
            system, code, local_title=title or None
        )
        http_status = 200
        if not payload.get('success'):
            status = payload.get('status')
            if status in ('not_in_local_db', 'not_supported_by_dha', 'title_changed'):
                http_status = 409
            elif status == 'dha_unavailable':
                http_status = 502
        return JsonResponse(payload, status=http_status)
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@login_required
@user_passes_test(can_use_terminology)
def loinc_search_api(request):
    """GET /home/api/loinc/search/?q=glucose — local DB first, seed from DHA if miss."""
    return _terminology_search_response(request, 'loinc')


@login_required
@user_passes_test(can_use_terminology)
def ichi_search_api(request):
    """GET /home/api/ichi/search/?q=appendectomy — local DB first, seed from DHA if miss."""
    return _terminology_search_response(request, 'ichi')


@login_required
@user_passes_test(can_use_terminology)
def loinc_validate_api(request):
    """GET /home/api/loinc/validate/?code=2345-7&title=... — confirm unchanged via DHA."""
    return _terminology_validate_response(request, 'loinc')


@login_required
@user_passes_test(can_use_terminology)
def ichi_validate_api(request):
    """GET /home/api/ichi/validate/?code=ATD.AC.ZZ&title=... — confirm unchanged via DHA."""
    return _terminology_validate_response(request, 'ichi')


@login_required
@user_passes_test(can_use_terminology)
def terminology_concepts_api(request):
    """
    GET /home/api/terminology/concepts/?owner=WHO&source=ICD-11&q=...

    ICD-11 uses local Icd11Code DB. Other sources query DHA (no local table yet).
    """
    return _terminology_search_response(request, 'concepts')


@login_required
@user_passes_test(can_use_terminology)
def terminology_browser_page(request):
    """UI to search ICD-11 / LOINC / ICHI (local first, DHA confirm on select)."""
    from django.conf import settings as django_settings
    from .icd11_local import local_icd11_count
    from .terminology_local import local_terminology_count

    return render(request, 'home/terminology_browser.html', {
        'loinc_owner': django_settings.SHA_HIE_LOINC_OWNER,
        'loinc_source': django_settings.SHA_HIE_LOINC_SOURCE,
        'ichi_owner': django_settings.SHA_HIE_ICHI_OWNER,
        'ichi_source': django_settings.SHA_HIE_ICHI_SOURCE,
        'icd11_owner': django_settings.SHA_HIE_ICD11_OWNER,
        'icd11_source': django_settings.SHA_HIE_ICD11_SOURCE,
        'terminology_base': django_settings.SHA_HIE_TERMINOLOGY_BASE_URL,
        'local_icd11_count': local_icd11_count(),
        'local_loinc_count': local_terminology_count('loinc'),
        'local_ichi_count': local_terminology_count('ichi'),
        'validate_on_select': django_settings.TERMINOLOGY_DHA_VALIDATE_ON_SELECT,
    })
