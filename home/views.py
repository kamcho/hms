from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.db.models import Q, Count, Sum, Avg, Prefetch, F
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
import json
from datetime import timedelta
from .models import Patient, Visit, TriageEntry, EmergencyContact, Consultation, PatientQue, ConsultationNotes, Departments, Prescription, PrescriptionItem, Referral
from accounts.models import Invoice, InvoiceItem, Service, Payment
from accounts.utils import get_or_create_invoice
from lab.models import LabResult
from inpatient.models import Admission
from morgue.models import MorgueAdmission
from .forms import EmergencyContactForm, PatientForm, ReferralForm
from django.db.models import Q
from inventory.models import DispensedItem
class PatientListView(LoginRequiredMixin, ListView):
    model = Patient
    template_name = 'home/patient_list.html'
    context_object_name = 'patients'
    
    def get_queryset(self):
        queryset = Patient.objects.all().order_by('-created_at')
        search_query = self.request.GET.get('search')
        if search_query:
            # Check if search query is a number for ID lookup
            id_filter = Q()
            if search_query.isdigit():
                id_filter = Q(pk=int(search_query))

            queryset = queryset.filter(
                id_filter |
                Q(id_number__icontains=search_query) |
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(phone__icontains=search_query)
            ).order_by('-created_at')
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add statistics
        today = timezone.now().date()
        all_patients = Patient.objects.all()
        
        context['stats'] = {
            'total': all_patients.count(),
            'new_today': all_patients.filter(created_at__date=today).count(),
            'male': all_patients.filter(gender='M').count(),
            'female': all_patients.filter(gender='F').count(),
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
        return context

class PatientCreateView(LoginRequiredMixin, CreateView):
    model = Patient
    form_class = PatientForm
    template_name = 'home/patient_form.html'
    success_url = reverse_lazy('home:patient_list')
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        
        # First save the patient to get the instance and set self.object
        self.object = form.save()
        
        # Handle integrated billing
        selected_service = form.cleaned_data.get('consultation_type')
        payment_method = form.cleaned_data.get('payment_method')
        
        # Define which services create a Visit + Queue
        VISIT_SERVICES = {'OPD Consultation', 'ANC', 'PNC Visit (Mother)', 'PNC Visit (Baby)', 'CWC'}
        creates_visit = selected_service and selected_service.name in VISIT_SERVICES
        
        if creates_visit:
            # Create a visit for the new patient
            visit = Visit.objects.create(
                patient=self.object,
                visit_type='OUT-PATIENT',
                visit_mode='Walk In'
            )
            
            if selected_service and payment_method:
                # Get or Create Visit Invoice (Consolidated)
                invoice = get_or_create_invoice(visit=visit, user=self.request.user)
                
                # Create InvoiceItem
                item = InvoiceItem.objects.create(
                    invoice=invoice,
                    service=selected_service,
                    name=selected_service.name,
                    unit_price=selected_service.price,
                    quantity=1
                )
                
                # Record Payment
                Payment.objects.create(
                    invoice=invoice,
                    amount=item.amount,
                    payment_method=payment_method,
                    created_by=self.request.user
                )
                
                messages.success(self.request, f"Patient registered and {selected_service.name} billed via {payment_method}.")
            
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
                
                item = InvoiceItem.objects.create(
                    invoice=invoice,
                    service=selected_service,
                    name=selected_service.name,
                    unit_price=selected_service.price,
                    quantity=1
                )
                
                Payment.objects.create(
                    invoice=invoice,
                    amount=item.amount,
                    payment_method=payment_method,
                    created_by=self.request.user
                )
                
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

class PatientDeleteView(LoginRequiredMixin, DeleteView):
    model = Patient
    template_name = 'home/patient_confirm_delete.html'
    success_url = reverse_lazy('home:patient_list')

class PatientDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = Patient
    template_name = 'home/patient_detail.html'
    context_object_name = 'patient'
    
    def test_func(self):
        return self.request.user.role in ['Admin', 'Doctor']
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = self.get_object()
        from inpatient.models import Admission

        # Get all visits for the filter dropdown
        all_visits = Visit.objects.filter(patient=patient).order_by('-visit_date')
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
            
        context['triage_entries'] = TriageEntry.objects.filter(**triage_filter).order_by('-entry_date')
        context['consultations'] = Consultation.objects.filter(**consultation_filter).order_by('-checkin_date')
        context['consultation_notes'] = ConsultationNotes.objects.filter(**notes_filter).order_by('-created_at')
        context['queue_entries'] = PatientQue.objects.filter(**queue_filter).order_by('-created_at')
        context['emergency_contacts'] = EmergencyContact.objects.filter(patient=patient).order_by('-is_primary', 'name')
        
        # Get lab results and reports for this patient
        from lab.models import LabResult, LabReport
        lab_results = LabResult.objects.filter(**lab_filter).select_related('service', 'requested_by').order_by('-requested_at')
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
                'price': str(test.price) if test.price else None
            })
        context['medical_tests_data'] = medical_tests_data
        context['medical_tests_json'] = json.dumps(medical_tests_data)
        
        # Get departments for the "Send To" options (only Lab, Imaging, Procedure Room)
        context['available_departments'] = Departments.objects.filter(
            name__in=['Lab', 'Imaging', 'Procedure Room']
        ).order_by('name')
        
        # Get dispensed items history (Normalized)
        context['dispensed_items'] = _get_normalized_history(selected_visit, patient)
        
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
            patient_id = request.POST.get('patient_id')
            consultation_id = request.POST.get('consultation_id')
            doctor_id = request.POST.get('doctor_id')
            note_content = request.POST.get('note_content')
            note_type = request.POST.get('note_type', 'GENERAL')
            
            # Get patient
            patient = get_object_or_404(Patient, pk=patient_id)
            
            # Identify the latest visit
            latest_visit = Visit.objects.filter(patient=patient).order_by('-visit_date').first()
            
            if not latest_visit:
                return JsonResponse({'success': False, 'error': 'No active visit found for this patient.'})

            if not latest_visit.is_active:
                return JsonResponse({'success': False, 'error': f'Visit for {patient.full_name} is already closed. Please create a new visit to record notes.'})

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
            
            # Block if latest visit is already closed (unless it's a walk-in dispense which we haven't fully separated yet, 
            # but for clinical actions like routing/labs, it must be active)
            if latest_visit and not latest_visit.is_active:
                return JsonResponse({'success': False, 'error': f'Visit for {patient.full_name} is already closed. Clinical actions cannot be performed on closed visits.'})

            # If no active visit, we allow walk-in invoicing (visit=None)
            visit = latest_visit
            
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
                for test_id in selected_tests:
                    try:
                        service = Service.objects.get(pk=test_id)
                        
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
            
            return JsonResponse({
                'success': True,
                'invoice_id': invoice_id,
                'message': f'Next action processed for {patient.first_name} {patient.last_name}. ' +
                          f'Patient routed to {len(send_to_departments)} department(s) and ' +
                          f'{len(selected_tests)} test(s) ordered.'
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
    
    # Get search query for patients
    patient_search = request.GET.get('patient_search', '')
    
    # Get search queries for triage (only for triage nurses)
    triage_search = request.GET.get('triage_search', '')
    pending_search = request.GET.get('pending_search', '')
    
    # Get user role
    user_role = request.user.role
    
    # Get recent patients with search functionality (limit to 10)
    patients = Patient.objects.all()
    
    if patient_search:
        patients = patients.filter(
            Q(first_name__icontains=patient_search) |
            Q(last_name__icontains=patient_search) |
            Q(phone__icontains=patient_search) |
            Q(location__icontains=patient_search)
        )
    
    patients = patients.order_by('-created_at')[:10]
    
    # Get today's visits
    today = timezone.now().date()
    today_visits = Visit.objects.filter(visit_date__date=today).count()
    
    # Get total patients count
    total_patients = Patient.objects.count()
    
    # Initialize context with common data
    context = {
        'patients': patients,
        'today_visits': today_visits,
        'total_patients': total_patients,
        'patient_search': patient_search,
        'triage_search': triage_search,
        'pending_search': pending_search,
        'user_role': user_role,
        'ipd_admissions': Admission.objects.filter(status='Admitted').select_related('patient', 'bed', 'bed__ward'),
        'morgue_admissions': MorgueAdmission.objects.filter(status='ADMITTED').select_related('deceased'),
    }
    
    if user_role == 'Receptionist' or user_role == 'Admin':
        # Receptionist (and Admin) sees invoices
        # Get patient service invoices with search functionality
        invoices = Invoice.objects.filter(
            Q(status__in=['Pending', 'Partial', 'Draft']) & 
            (Q(visit__visit_type='OUT-PATIENT') | Q(visit__visit_type='IN-PATIENT', visit__admissions__isnull=True))
        ).select_related('patient', 'deceased').prefetch_related(
            Prefetch('items', queryset=InvoiceItem.objects.filter(paid_amount__lt=F('amount')).select_related('service'))
        )
        
        if invoice_search:
            invoices = invoices.filter(
                Q(patient__first_name__icontains=invoice_search) |
                Q(patient__last_name__icontains=invoice_search) |
                Q(deceased__first_name__icontains=invoice_search) |
                Q(deceased__last_name__icontains=invoice_search) |
                Q(items__name__icontains=invoice_search) |
                Q(id__icontains=invoice_search)
            ).distinct()
        
        invoices = invoices.order_by('-created_at')
        
        # Get unpaid invoices count
        unpaid_invoices = Invoice.objects.filter(
            Q(status__in=['Pending', 'Partial', 'Draft']) & 
            (Q(visit__visit_type='OUT-PATIENT') | Q(visit__visit_type='IN-PATIENT', visit__admissions__isnull=True))
        ).count()
        
        # Get active services grouped by department for quick invoicing
        services = Service.objects.filter(is_active=True).select_related('department').order_by('department__name', 'name')
        
        context.update({
            'invoices': invoices,
            'unpaid_invoices': unpaid_invoices,
            'invoice_search': invoice_search,
            'services': services,
        })
        
    elif user_role == 'Triage Nurse':
        # Triage Nurse sees triage entries and visits without triage
        # Get recent triage entries
        triage_entries = TriageEntry.objects.select_related('visit__patient', 'triage_nurse')
        
        if triage_search:
            triage_entries = triage_entries.filter(
                Q(visit__patient__first_name__icontains=triage_search) |
                Q(visit__patient__last_name__icontains=triage_search) |
                Q(visit__patient__phone__icontains=triage_search)
            )
            
        triage_entries = triage_entries.order_by('-entry_date')[:10]
        
        # Get visits without triage entries
        visits_with_triage = Visit.objects.filter(triage_entries__isnull=False).values_list('pk', flat=True)
        visits_without_triage = Visit.objects.filter(
            ~Q(pk__in=visits_with_triage),
            patient_queue__sent_to__name='Triage', # Ensuring we only show patients actually queued for Triage
            patient_queue__status='PENDING'
        ).select_related('patient').prefetch_related('invoice__items__service').distinct()
        
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
        
        # Get triage entries count for today
        today_triage_entries = TriageEntry.objects.filter(entry_date__date=today).count()
        
        # Get pending triage count (visits without triage)
        pending_triage_count = Visit.objects.filter(
            ~Q(pk__in=visits_with_triage),
            visit_date__date=today,
            patient_queue__sent_to__name='Triage',
            patient_queue__status='PENDING'
        ).distinct().count()
        
        context.update({
            'triage_entries': triage_entries,
            'visits_without_triage': visits_without_triage,
            'today_triage_entries': today_triage_entries,
            'pending_triage_count': pending_triage_count,
        })
    
    return render(request, 'home/reception_dashboard.html', context)


@login_required
def add_symptoms(request):
    """Add symptoms to a visit"""
    if request.method == 'POST':
        try:
            visit_id = request.POST.get('visit_id')
            data = request.POST.get('data')
            days = request.POST.get('days')
            
            visit = get_object_or_404(Visit, pk=visit_id)
            
            # Block if not latest visit or if visit is not active
            latest_visit = Visit.objects.filter(patient=visit.patient).order_by('-visit_date').first()
            if visit != latest_visit:
                return JsonResponse({'success': False, 'error': 'Cannot add symptoms to a previous visit.'})
            
            if not visit.is_active:
                return JsonResponse({'success': False, 'error': 'Cannot add symptoms to a closed visit. Please create a new visit.'})

            from .models import Symptoms
            
                
            Symptoms.objects.create(
                visit=visit,
                data=data,
                days=days,
                created_by=request.user
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
def add_diagnosis(request):
    """Add diagnosis to a visit"""
    if request.method == 'POST':
        try:
            visit_id = request.POST.get('visit_id')
            data = request.POST.get('data')
            
            visit = get_object_or_404(Visit, pk=visit_id)
            
            # Block if not latest visit or if visit is not active
            latest_visit = Visit.objects.filter(patient=visit.patient).order_by('-visit_date').first()
            if visit != latest_visit:
                return JsonResponse({'success': False, 'error': 'Cannot add diagnosis to a previous visit.'})
                
            if not visit.is_active:
                return JsonResponse({'success': False, 'error': 'Cannot add diagnosis to a closed visit.'})

            from .models import Diagnosis
            Diagnosis.objects.create(
                visit=visit,
                data=data,
                created_by=request.user
            )
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


@login_required # Ensure login
def admit_patient_visit(request):
    """
    Admit a patient (create a Visit) and add to a Queue (Reception -> Dest).
    """
    if request.method == 'POST':
        try:
            patient_id = request.POST.get('patient_id')
            service_id = request.POST.get('service_id') or request.POST.get('consultation_id')
            
            patient = get_object_or_404(Patient, pk=patient_id)
            main_service = get_object_or_404(Service, pk=service_id)
            
            # Create a visit for the patient
            visit = Visit.objects.create(
                patient=patient,
                visit_type='OUT-PATIENT',
                visit_mode='Walk In'
            )
            
            # Create or get reception and triage departments
            reception_dept, _ = Departments.objects.get_or_create(
                name='Reception',
                defaults={'abbreviation': 'REC'}
            )
            
            triage_dept, _ = Departments.objects.get_or_create(
                name='Triage',
                defaults={'abbreviation': 'TRI'}
            )

            # Route based on Service Name (Smart Routing)
            # Default: If service has a linked department, send there. Else fallback to Triage.
            destination_dept = main_service.department if main_service.department else triage_dept
            
            service_name_upper = main_service.name.upper()
            is_maternity = False
            
            # Specific Overrides - Order Matters! Check specific depts first before generic 'Consultation'
            if "ANC" in service_name_upper:
                anc_dept, _ = Departments.objects.get_or_create(name='ANC', defaults={'abbreviation': 'ANC'})
                destination_dept = anc_dept
                is_maternity = True
            elif "PNC" in service_name_upper:
                pnc_dept, _ = Departments.objects.get_or_create(name='PNC', defaults={'abbreviation': 'PNC'})
                destination_dept = pnc_dept
                is_maternity = True
            elif "CWC" in service_name_upper or "CHILD WELFARE" in service_name_upper or "IMMUNIZA" in service_name_upper or "VACCIN" in service_name_upper or "CNC" in service_name_upper:
                cwc_dept, _ = Departments.objects.get_or_create(name='CWC', defaults={'abbreviation': 'CWC'})
                destination_dept = cwc_dept
                is_maternity = True
            elif "LAB" in service_name_upper or "LABORATORY" in service_name_upper:
                 lab_dept, _ = Departments.objects.get_or_create(name='Lab', defaults={'abbreviation': 'LAB'})
                 destination_dept = lab_dept
            elif "RADIOLOGY" in service_name_upper or "IMAGING" in service_name_upper or "X-RAY" in service_name_upper or "ULTRASOUND" in service_name_upper:
                 img_dept, _ = Departments.objects.get_or_create(name='Imaging', defaults={'abbreviation': 'IMG'})
                 destination_dept = img_dept
            elif "IPD" in service_name_upper or "ADMISSION" in service_name_upper:
                 # Route IPD/Admissions to Admissions Desk/Ward
                 adm_dept, _ = Departments.objects.get_or_create(name='Admissions', defaults={'abbreviation': 'ADM'})
                 destination_dept = adm_dept
            elif "OPD" in service_name_upper or "CONSULTATION" in service_name_upper:
                # General OPD / Consultations always go to Triage first (if not matched above)
                destination_dept = triage_dept
            
            # --- Billing Logic ---
            from accounts.models import Invoice, InvoiceItem
            from django.utils import timezone
            from accounts.utils import get_or_create_invoice

            should_bill = False
            
            if is_maternity:
                # ANC / PNC / CWC: Always Bill
                should_bill = True
            else:
                # OPD: Check if billed for consultation this year
                current_year = timezone.now().year
                has_billed_this_year = InvoiceItem.objects.filter(
                    invoice__patient=patient,
                    service__name__icontains='Consultation', # Broad check for consultation services
                    invoice__created_at__year=current_year,
                    invoice__status__in=['Paid', 'Partial', 'Pending'] # Assuming we only care if they have a valid previous invoice
                ).exists()
                
                if not has_billed_this_year:
                    should_bill = True
            
            billing_msg = " (Free Visit)"
            if should_bill:
                # Create Invoice
                invoice = get_or_create_invoice(visit=visit, user=request.user)
                
                InvoiceItem.objects.create(
                    invoice=invoice,
                    service=main_service,
                    name=main_service.name,
                    unit_price=main_service.price,
                    quantity=1
                )
                billing_msg = " (Billed)"
            
            # Create PatientQue from reception to destination (Triage or Direct Maternity)
            que = PatientQue.objects.create(
                visit=visit,
                qued_from=reception_dept,
                sent_to=destination_dept,
                created_by=request.user
            )
            
            # --- ANC Revisit: Auto-queue returning patients directly into Clinical Queue ---
            if "ANC" in service_name_upper:
                from maternity.models import Pregnancy, AntenatalVisit
                active_pregnancy = Pregnancy.objects.filter(patient=patient, status='Active').first()
                
                if active_pregnancy:
                    # Patient has active pregnancy → create AntenatalVisit directly
                    # Only check for OPEN visits today (closed ones don't block a new revisit)
                    existing_open_today = AntenatalVisit.objects.filter(
                        pregnancy=active_pregnancy,
                        visit_date=timezone.now().date(),
                        is_closed=False
                    ).first()
                    
                    if not existing_open_today:
                        AntenatalVisit.objects.create(
                            pregnancy=active_pregnancy,
                            visit_date=timezone.now().date(),
                            visit_number=(active_pregnancy.anc_visits.count() + 1),
                            gestational_age=active_pregnancy.gestational_age_weeks,
                            service_received=False,
                            is_closed=False,
                            recorded_by=request.user
                        )
                    
                    # Mark queue as completed — patient goes straight to Clinical Queue
                    que.status = 'COMPLETED'
                    que.save()
            
            return JsonResponse({
                'success': True, 
                'message': f'Patient {patient.full_name} admitted for {main_service.name}{billing_msg}.'
            })
        except Exception as e:
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
    from .forms import PrescriptionForm, PrescriptionItemForm

    
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
        extra=3,  # Show 3 empty forms by default
        can_delete=True
    )
    
    if request.method == 'POST':
        form = PrescriptionForm(request.POST)
        formset = PrescriptionItemFormSet(request.POST, prefix='items')
        
        if form.is_valid() and formset.is_valid():
            # Save prescription
            prescription = form.save(commit=False)
            prescription.patient = patient
            prescription.prescribed_by = request.user
            prescription.visit = visit
                
            # Close visit if requested
            if request.POST.get('action') == 'prescribe_close':
                visit.is_active = False
                visit.save()
                messages.info(request, "Visit has been closed.")
            
            prescription.save()
            
            # Save prescription items
            formset.instance = prescription
            prescription_items = formset.save()
            
            # Create billing for the prescription medications
            if prescription_items:
                # Get or Create Visit Invoice (Consolidated)
                invoice = get_or_create_invoice(visit=prescription.visit, user=request.user)
                
                # Append to existing notes
                new_notes = f"\nPrescription meds added: {', '.join([item.medication.name for item in prescription_items])}"
                if invoice.notes:
                    invoice.notes += new_notes
                else:
                    invoice.notes = new_notes.strip()
                invoice.save()
                
                # Link invoice to prescription
                prescription.invoice = invoice
                prescription.save()
                
                for item in prescription_items:
                    # Skip creating invoice items for free medications
                    if item.medication.selling_price > 0:
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            inventory_item=item.medication,
                            name=item.medication.name,
                            unit_price=item.medication.selling_price,
                            quantity=item.quantity
                        )
                
                # Update invoice totals and handle free prescriptions
                invoice.update_totals()
                if invoice.total_amount == 0 and invoice.status != 'Paid':
                    invoice.status = 'Paid'
                    invoice.save()

                messages.success(request, f'Prescription processed successfully for {patient.full_name}')
            else:
                messages.success(request, f'Prescription created successfully (no items) for {patient.full_name}')
                
            return redirect('home:prescription_detail', prescription_id=prescription.id)
    else:
        form = PrescriptionForm()
        formset = PrescriptionItemFormSet(prefix='items')
    
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
    departments = ['Pharmacy'] # Base for everyone
    if visit.visit_type == 'OUT-PATIENT':
        departments.append('Main Store')
    else: # In-Patient
        departments.extend(['Main Store', 'Mini Pharmacy'])
    
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
            'is_dispensed_as_whole': item.is_dispensed_as_whole,
            'dispensing_unit': item.dispensing_unit,
            'selling_price': str(item.selling_price),
            'stock_quantity': total_stock,
            'visit_type': visit.visit_type
        }
    
    context = {
        'form': form,
        'formset': formset,
        'patient': patient,
        'visit': visit,
        'med_metadata_json': json.dumps(med_metadata),
        # Add Dispensed Items context for the widget (Normalized)
        'dispensed_items': _get_normalized_history(visit, patient),
        'dispensing_departments': Departments.objects.all().order_by('name')
    }
    return render(request, 'home/create_prescription.html', context)

def _get_normalized_history(visit, patient):
    from inventory.models import DispensedItem
    from accounts.models import InvoiceItem
    from inpatient.models import MedicationChart, InpatientConsumable
    
    if not visit:
        return []

    # 1. Fetch physical dispensations (Stock deducted)
    d_items = DispensedItem.objects.filter(visit=visit).select_related('item', 'dispensed_by').order_by('-dispensed_at')
    
    # 2. Fetch billed items (Requested by doctor but might not be dispensed yet)
    billed_items = InvoiceItem.objects.filter(
        invoice__visit=visit,
        inventory_item__isnull=False
    ).select_related('inventory_item', 'invoice__created_by').order_by('-created_at')

    # 3. Fetch IPD requests (not yet dispensed)
    ipd_meds = MedicationChart.objects.filter(
        admission__visit=visit,
        is_dispensed=False
    ).select_related('item', 'prescribed_by').order_by('-prescribed_at')
    
    ipd_consumables = InpatientConsumable.objects.filter(
        admission__visit=visit,
        is_dispensed=False
    ).select_related('item', 'prescribed_by').order_by('-prescribed_at')
        
    # 4. Combine and Normalize with De-duplication
    history = []
    
    # Track dispensed items to suppress corresponding requests
    # Frequency map: (item_id, quantity) -> count
    dispensed_counts = {}
    for d in d_items:
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
            'status': 'Requested',
            'status_class': 'bg-amber-50 text-amber-700'
        })

    # Add IPD Meds
    for m in ipd_meds:
        key = (m.item.id, m.quantity)
        if dispensed_counts.get(key, 0) > 0:
            dispensed_counts[key] -= 1
            continue

        history.append({
            'item_name': m.item.name,
            'quantity': m.quantity,
            'at': m.prescribed_at,
            'by': m.prescribed_by,
            'status': 'Requested',
            'status_class': 'bg-amber-50 text-amber-700'
        })

    # Add IPD Consumables
    for c in ipd_consumables:
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
        
    # 3. Gender
    gender = request.GET.get('gender')
    if gender and gender != 'all':
        has_filters = True
        visits = visits.filter(patient__gender=gender)
        
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
    
    prescription = get_object_or_404(Prescription, pk=prescription_id)
    
    context = {
        'prescription': prescription,
        'patient': prescription.patient,
    }
    return render(request, 'home/prescription_detail.html', context)


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
from inpatient.models import MedicationChart


@login_required
@login_required
def pharmacy_dashboard(request):
    """Pharmacy dashboard showing prescriptions, consumables, stock, and requests"""
    # Role-based access control
    if request.user.role not in ['Pharmacist', 'Nurse']:
        messages.error(request, "Access denied. Only pharmacists and nurses can access the pharmacy dashboard.")
        return redirect('home:reception_dashboard')

    # Determine department based on role
    dept_name = 'Pharmacy' if request.user.role == 'Pharmacist' else 'mini pharmacy'
    pharmacy_dept, created = Departments.objects.get_or_create(
        name=dept_name,
        defaults={'abbreviation': 'PHR' if dept_name == 'Pharmacy' else 'MPHR'}
    )

    # Search functionality
    search_query = request.GET.get('search', '')
    stock_search = request.GET.get('stock_search', '')
    dispensed_search = request.GET.get('dispensed_search', '')
    request_search = request.GET.get('request_search', '')

    # Get pending prescriptions (not dispensed)
    pending_items = PrescriptionItem.objects.filter(
        dispensed=False
    ).select_related(
        'prescription__patient',
        'prescription__prescribed_by',
        'prescription__invoice',
        'prescription__visit',
        'medication'
    ).order_by('-prescription__prescribed_at')

    # Get pending IPD medications (from MedicationChart)
    pending_ipd_items = MedicationChart.objects.filter(
        is_dispensed=False
    ).select_related(
        'admission__patient',
        'admission__visit',
        'admission__bed__ward',
        'prescribed_by',
        'item'
    ).order_by('-prescribed_at')

    # Get pending IPD consumables
    from inpatient.models import Admission, InpatientConsumable
    pending_ipd_consumables = InpatientConsumable.objects.filter(
        is_dispensed=False
    ).select_related(
        'admission__patient',
        'admission__visit',
        'prescribed_by',
        'item'
    ).order_by('-prescribed_at')

    # Get pending consumables — InvoiceItems with inventory_item that have NOT been dispensed yet
    from accounts.models import Invoice, InvoiceItem

    # Consumable InvoiceItems: have inventory_item set, but are NOT medications
    pending_consumables = InvoiceItem.objects.filter(
        inventory_item__isnull=False,
        inventory_item__medication__isnull=True, # Structural check for consumables (non-drugs)
        invoice__status__in=['Draft', 'Pending', 'Paid', 'Partial'],
    ).select_related(
        'invoice__patient',
        'invoice__visit',
        'inventory_item',
    ).order_by('-created_at')

    # Filter out consumables that already have a DispensedItem
    # (match by visit + inventory_item + quantity)
    dispensed_consumable_keys = set()
    for d in DispensedItem.objects.all().values_list('visit_id', 'item_id', 'quantity'):
        dispensed_consumable_keys.add(d)

    pending_consumable_list = []
    for ci in pending_consumables:
        key = (ci.invoice.visit_id, ci.inventory_item_id, ci.quantity)
        if key not in dispensed_consumable_keys:
            pending_consumable_list.append(ci)

    if search_query:
        pending_items = pending_items.filter(
            Q(prescription__patient__first_name__icontains=search_query) |
            Q(prescription__patient__last_name__icontains=search_query) |
            Q(medication__name__icontains=search_query)
        )
        pending_ipd_items = pending_ipd_items.filter(
            Q(admission__patient__first_name__icontains=search_query) |
            Q(admission__patient__last_name__icontains=search_query) |
            Q(item__name__icontains=search_query)
        )
        pending_ipd_consumables = pending_ipd_consumables.filter(
            Q(admission__patient__first_name__icontains=search_query) |
            Q(admission__patient__last_name__icontains=search_query) |
            Q(item__name__icontains=search_query)
        )
        # Filter pending consumable list
        pending_consumable_list = [
            ci for ci in pending_consumable_list
            if search_query.lower() in (ci.invoice.patient.first_name or '').lower()
            or search_query.lower() in (ci.invoice.patient.last_name or '').lower()
            or search_query.lower() in (ci.inventory_item.name or '').lower()
        ]

    # ---- Build OPD grouped data: group prescriptions + consumables by visit ----
    from collections import defaultdict

    opd_visit_groups = defaultdict(lambda: {
        'patient': None,
        'visit': None,
        'prescriptions': [],
        'consumables': [],
        'invoice': None,
        'invoice_status': 'No Invoice',
        'prescribed_at': None,
        'prescribed_by': None,
    })

    for item in pending_items:
        visit = item.prescription.visit
        if not visit:
            continue
        # PrescriptionItem is guaranteed OPD (IPD blocked at create_prescription)
        vkey = visit.id
        group = opd_visit_groups[vkey]
        group['patient'] = item.prescription.patient
        group['visit'] = visit
        group['prescriptions'].append(item)
        if item.prescription.invoice:
            group['invoice'] = item.prescription.invoice
            group['invoice_status'] = item.prescription.invoice.status
        if not group['prescribed_at'] or item.prescription.prescribed_at > group['prescribed_at']:
            group['prescribed_at'] = item.prescription.prescribed_at
            group['prescribed_by'] = item.prescription.prescribed_by

    for ci in pending_consumable_list:
        visit = ci.invoice.visit
        if not visit:
            continue
        # Check if this visit is IPD — skip, those go in IPD section
        is_ipd = Admission.objects.filter(visit=visit, status='Admitted').exists()
        if is_ipd:
            continue
        vkey = visit.id
        group = opd_visit_groups[vkey]
        group['patient'] = ci.invoice.patient
        group['visit'] = visit
        group['consumables'].append(ci)
        if not group['invoice']:
            group['invoice'] = ci.invoice
            group['invoice_status'] = ci.invoice.status

    # Convert to list and sort
    opd_groups = sorted(
        [g for g in opd_visit_groups.values() if g['patient']],
        key=lambda g: g['prescribed_at'] or timezone.now(),
        reverse=True
    )

    # ---- Build IPD grouped data ----
    ipd_visit_groups = defaultdict(lambda: {
        'patient': None,
        'visit': None,
        'admission': None,
        'medications': [],
        'consumables': [],
    })

    for item in pending_ipd_items:
        vkey = item.admission.visit_id
        group = ipd_visit_groups[vkey]
        group['patient'] = item.admission.patient
        group['visit'] = item.admission.visit
        group['admission'] = item.admission
        group['medications'].append(item)

    for item in pending_ipd_consumables:
        vkey = item.admission.visit_id
        group = ipd_visit_groups[vkey]
        group['patient'] = item.admission.patient
        group['visit'] = item.admission.visit
        group['admission'] = item.admission
        group['consumables'].append(item)

    for ci in pending_consumable_list:
        visit = ci.invoice.visit
        if not visit:
            continue
        is_ipd = Admission.objects.filter(visit=visit, status='Admitted').exists()
        if not is_ipd:
            continue
        vkey = visit.id
        group = ipd_visit_groups[vkey]
        group['patient'] = ci.invoice.patient
        group['visit'] = visit
        if not group['admission']:
            group['admission'] = Admission.objects.filter(visit=visit, status='Admitted').first()
        group['consumables'].append(ci)

    ipd_groups = sorted(
        [g for g in ipd_visit_groups.values() if g['patient']],
        key=lambda g: g['admission'].admitted_at if g['admission'] else timezone.now(),
        reverse=True
    )

    # Get recently dispensed items (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    dispensed_items = DispensedItem.objects.filter(
        dispensed_at__gte=thirty_days_ago
    ).select_related(
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
    today = timezone.now().date()
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
        'pending_prescriptions': pending_items.count() + len([c for c in pending_consumable_list if not Admission.objects.filter(visit=c.invoice.visit, status='Admitted').exists()]),
        'pending_ipd_count': pending_ipd_items.count() + pending_ipd_consumables.count() + len([c for c in pending_consumable_list if Admission.objects.filter(visit=c.invoice.visit, status='Admitted').exists()]),
        'low_stock_count': len(low_stock_items),
        'pending_requests': pending_requests_count,
        'dispensed_today': DispensedItem.objects.filter(
            dispensed_at__date=today
        ).count(),
    }

    context = {
        'opd_groups': opd_groups if request.user.role == 'Pharmacist' else [],
        'ipd_groups': ipd_groups if request.user.role == 'Nurse' else [],
        'pending_items': pending_items,
        'pending_ipd_items': pending_ipd_items,
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
        'pharmacy_dept': pharmacy_dept,
    }

    return render(request, 'home/pharmacy_dashboard.html', context)


@login_required
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
        if is_ipd and request.user.role != 'Nurse':
            return JsonResponse({'success': False, 'error': 'Only nurses can dispense IPD medications.'})
        if not is_ipd and request.user.role != 'Pharmacist':
            return JsonResponse({'success': False, 'error': 'Only pharmacists can dispense OPD medications.'})

        # Determine department based on role
        dept_name = 'Pharmacy' if request.user.role == 'Pharmacist' else 'Mini Pharmacy'
        pharmacy_dept = Departments.objects.get(name=dept_name)

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

        # Scenario B: InvoiceItems marked as Consumable (Legacy IPD or Modern OPD immediate billing)
        pending_consumable_items = InvoiceItem.objects.filter(
            invoice__visit=visit,
            inventory_item__isnull=False,
            inventory_item__medication__isnull=True, # Ensure it is a consumable (not a linked medication)
        ).select_related('inventory_item', 'invoice')

        # Filter out already-dispensed consumables for Scenario B
        dispensed_keys = set(
            DispensedItem.objects.filter(visit=visit).values_list('item_id', 'quantity')
        )
        pending_consumables = [
            ci for ci in pending_consumable_items
            if (ci.inventory_item_id, ci.quantity) not in dispensed_keys
        ]

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

            # Mark as dispensed
            med.dispensed = True
            med.dispensed_at = timezone.now()
            med.dispensed_by = request.user
            med.save()

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

def opd_dashboard(request):
    """
    Dashboard for Outpatient Department (Doctors)
    Shows analytics and waiting patient queue
    """
    today = timezone.now().date()
    
    # 1. Analytics
    # Total "Walk In" or "Appointment" visits today
    todays_visits_count = Visit.objects.filter(
        visit_date__date=today,
        visit_type='OUT-PATIENT'
    ).count()
    
    # Waiting Patients (In queue for Consultation rooms)
    # Filter departments that look like consultation rooms and are PENDING
    # Strictly filter for OUT-PATIENT visits to exclude admitted (IPD) patients
    consultation_queues = PatientQue.objects.filter(
        sent_to__name__icontains='Consultation',
        status='PENDING',
        visit__is_active=True,
        visit__visit_type='OUT-PATIENT'
    ).select_related('visit__patient', 'sent_to', 'qued_from')

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
    triage_today = TriageEntry.objects.filter(visit__visit_date__date=today)
    critical_count = triage_today.filter(priority__in=['URGENT', 'CRITICAL']).count()
    
    # 2. The Queue Data
    # Enrich queue items with triage info
    queue_list = []
    
    # Order by priority (requires join/subquery logic or python sorting)
    # Let's fetch all and sort in python for flexibility
    for item in consultation_queues.order_by('-created_at'):
        # Get latest triage for this visit
        triage = TriageEntry.objects.filter(visit=item.visit).order_by('-entry_date').first()
        
        queue_list.append({
            'queue_id': item.id,
            'patient': item.visit.patient,
            'visit': item.visit,
            'sent_to': item.sent_to.name if item.sent_to else 'General OPD',
            'queued_at': item.created_at,
            'queue_type': item.queue_type,
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
        doctor=request.user
    ).select_related('visit__patient').order_by('-checkin_date')[:5]
    context['recent_consultations'] = recent_consultations
    
    return render(request, 'home/opd_dashboard.html', context)

@login_required
def procedure_room_dashboard(request):
    """Dashboard for Procedure Room to view requested procedures"""
    # Procedures are InvoiceItems with a linked procedure
    # Filter for items where procedure is not null
    service_items = InvoiceItem.objects.filter(
        procedure__isnull=False
    ).select_related('invoice', 'invoice__patient', 'procedure', 'service')
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        service_items = service_items.filter(
            Q(invoice__patient__first_name__icontains=search_query) |
            Q(invoice__patient__last_name__icontains=search_query) |
            Q(procedure__name__icontains=search_query) |
            Q(name__icontains=search_query)
        )
    
    # Order by most recent
    service_items = service_items.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(service_items, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
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
        procedure__isnull=False
    ).select_related('invoice', 'service', 'procedure').order_by('created_at')
    
    # Get dispensed items history for this visit
    from inventory.models import DispensedItem
    dispensed_items = DispensedItem.objects.filter(visit=visit).select_related('item', 'dispensed_by').order_by('-dispensed_at')
        
    context = {
        'procedures': procedures,
        'patient': patient,
        'visit': visit,
        'dispensed_items': dispensed_items,
        'dispensing_departments': Departments.objects.all().order_by('name'),
        'title': f'Procedures: {patient.full_name}'
    }
    return render(request, 'home/procedure_detail.html', context)

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

    # Handle New Trip Creation
    if request.method == 'POST':
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
    today = timezone.now().date()
    start_date = today - timedelta(days=30)
    
    # Summary Stats
    total_trips = AmbulanceActivity.objects.count()
    total_revenue = AmbulanceActivity.objects.aggregate(total=Sum('amount'))['total'] or 0
    trips_today = AmbulanceActivity.objects.filter(date__date=today).count()
    
    # Recent Activities
    activities = AmbulanceActivity.objects.all().select_related('patient', 'route', 'invoice').order_by('-date')[:20]
    
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
        'total_trips': total_trips,
        'total_revenue': total_revenue,
        'trips_today': trips_today,
        'activities': activities,
        'routes': routes,
        'patients': patients,
        'chart_labels': json.dumps(dates),
        'chart_counts': json.dumps(counts),
        'chart_revenues': json.dumps(revenues),
    }
    
    return render(request, 'home/ambulance_dashboard.html', context)
