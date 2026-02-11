from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.db.models import Q, Count, Sum, Avg
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
import json
from datetime import timedelta
from .models import Patient, Visit, TriageEntry, EmergencyContact, Consultation, PatientQue, ConsultationNotes, Departments, Prescription, PrescriptionItem
from accounts.models import Invoice, InvoiceItem, Service, Payment
from lab.models import LabResult
from inpatient.models import Admission
from morgue.models import MorgueAdmission
from .forms import EmergencyContactForm, PatientForm
from django.db.models import Q

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
        
        # Create a visit for the new patient
        visit = Visit.objects.create(
            patient=self.object,
            visit_type='OUT-PATIENT',
            visit_mode='Walk In'
        )
        
        # Handle integrated billing
        consultation_service = form.cleaned_data.get('consultation_type')
        payment_method = form.cleaned_data.get('payment_method')
        
        if consultation_service and payment_method:
            # Create Invoice
            invoice = Invoice.objects.create(
                patient=self.object,
                visit=visit,
                status='Pending',
                created_by=self.request.user
            )
            
            # Create InvoiceItem for consultation
            item = InvoiceItem.objects.create(
                invoice=invoice,
                service=consultation_service,
                name=consultation_service.name,
                unit_price=consultation_service.price,
                quantity=1
            )
            
            # Record Payment
            Payment.objects.create(
                invoice=invoice,
                amount=item.amount,
                payment_method=payment_method,
                created_by=self.request.user
            )
            
            # Invoice update_totals and status will be handled by Payment.save()
            messages.success(self.request, f"Patient registered and {consultation_service.name} billed via {payment_method}.")
        
        # Create or get reception and triage departments
        reception_dept, created = Departments.objects.get_or_create(
            name='Reception',
            defaults={'abbreviation': 'REC'}
        )
        
        triage_dept, created = Departments.objects.get_or_create(
            name='Triage',
            defaults={'abbreviation': 'TRI'}
        )
        
        # Create PatientQue from reception to triage
        PatientQue.objects.create(
            visit=visit,
            qued_from=reception_dept,
            sent_to=triage_dept,
            created_by=self.request.user,
            status='PENDING',
            queue_type='INITIAL'
        )
        
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

        # Get visit filter from GET parameters
        visit_id = self.request.GET.get('visit_id', None)
        selected_visit = None
        
        if visit_id and visit_id != 'all':
            try:
                selected_visit = Visit.objects.get(id=visit_id, patient=patient)
            except Visit.DoesNotExist:
                selected_visit = None

        # Get all visits for the filter dropdown
        all_visits = Visit.objects.filter(patient=patient).order_by('-visit_date')
        latest_visit = all_visits.first()
        
        context['visits'] = all_visits
        context['selected_visit'] = selected_visit
        context['latest_visit'] = latest_visit
        
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
        context['medical_tests_json'] = json.dumps(medical_tests_data)
        
        # Get departments for the "Send To" options (only Lab, Imaging, Procedure Room)
        context['available_departments'] = Departments.objects.filter(
            name__in=['Lab', 'Imaging', 'Procedure Room']
        ).order_by('name')
        
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
                dept_name = "Maternity"
                dept_abbr = "MAT"
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

            # Handle consultation
            consultation = None
            
            # If a specific consultation is provided, use it
            if consultation_id and consultation_id != 'new':
                consultation = get_object_or_404(Consultation, pk=consultation_id)
                # Ensure this consultation belongs to the latest visit
                if consultation.visit != latest_visit:
                    return JsonResponse({'success': False, 'error': 'Can only add notes to the latest visit.'})
            else:
                # We are creating a new note, it MUST be for the latest visit
                # Find or create a consultation for the latest visit
                consultation = Consultation.objects.filter(visit=latest_visit, doctor=request.user).first()
                if not consultation:
                    consultation = Consultation.objects.create(
                        visit=latest_visit,
                        doctor=request.user
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
    allowed_roles = ['Doctor', 'Receptionist', 'Triage Nurse', 'Admin']
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
            
            # If no active visit, we allow walk-in invoicing (visit=None)
            visit = latest_visit
            
            # Process department routing
            for dept in send_to_departments:
                # Create or get destination department
                if dept == 'pharmacy':
                    dept_name = 'Pharmacy'
                    dept_abbr = 'PHR'
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
            invoice_id = None
            if selected_tests:
                # Create one invoice for all tests
                invoice = Invoice.objects.create(
                    patient=patient,
                    visit=visit,
                    status='Pending',
                    created_by=request.user
                )
                invoice_id = invoice.id
                
                items_created = 0
                for test_id in selected_tests:
                    try:
                        service = Service.objects.get(pk=test_id)
                        item = InvoiceItem.objects.create(
                            invoice=invoice,
                            service=service,
                            name=service.name,
                            unit_price=service.price,
                            quantity=1
                        )

                        # Automatically create LabResult for Lab/Imaging/Procedure tests
                        if service.category in ['Lab', 'Imaging', 'Procedure']:
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
            status__in=['Pending', 'Partial', 'Draft'],
            visit__visit_type='OUT-PATIENT'
        ).select_related('patient', 'deceased').prefetch_related('items__service')
        
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
        unpaid_invoices = Invoice.objects.filter(status__in=['Pending', 'Partial', 'Draft'], visit__visit_type='OUT-PATIENT').count()
        
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
            ~Q(pk__in=visits_with_triage)
        ).select_related('patient').prefetch_related('invoices__items__service')
        
        if pending_search:
            visits_without_triage = visits_without_triage.filter(
                Q(patient__first_name__icontains=pending_search) |
                Q(patient__last_name__icontains=pending_search) |
                Q(patient__phone__icontains=pending_search) |
                Q(invoices__items__service__name__icontains=pending_search) |
                Q(invoices__items__name__icontains=pending_search)
            ).distinct()
            
        visits_without_triage = visits_without_triage.order_by('-visit_date')[:10]

        # Tag maternity visits based on services in recent invoices
        for visit in visits_without_triage:
            visit.is_maternity = False
            visit.services_list = []
            for invoice in visit.invoices.all():
                for item in invoice.items.all():
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
            visit_date__date=today
        ).count()
        
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
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def add_impression(request):
    """Add impression to a visit"""
    if request.method == 'POST':
        try:
            visit_id = request.POST.get('visit_id')
            data = request.POST.get('data')
            
            visit = get_object_or_404(Visit, pk=visit_id)
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


@login_required
def admit_patient_visit(request):
    """Create a new visit and queue entry for an existing patient (Free Revisit)"""
    if request.method == 'POST':
        try:
            patient_id = request.POST.get('patient_id')
            service_id = request.POST.get('consultation_id') # Kept the key for JS compatibility
            
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
            
            # Create PatientQue from reception to triage
            PatientQue.objects.create(
                visit=visit,
                qued_from=reception_dept,
                sent_to=triage_dept,
                created_by=request.user
            )
            
            return JsonResponse({
                'success': True, 
                'message': f'Patient {patient.full_name} admitted for {main_service.name} (Free Revisit).'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


# Prescription Views
@login_required
def create_prescription(request, visit_id):
    """Create a new prescription for a patient linked to a specific visit"""
    if request.user.role != 'Doctor':
        messages.error(request, "Only doctors can create prescriptions.")
        # We need to find the patient first to redirect, or just redirect to dashboard
        visit = get_object_or_404(Visit, pk=visit_id)
        return redirect('home:patient_detail', pk=visit.patient.id)
    
    from django.forms import inlineformset_factory
    from .forms import PrescriptionForm, PrescriptionItemForm
    from .models import Prescription, PrescriptionItem, Visit
    
    visit = get_object_or_404(Visit, pk=visit_id)
    patient = visit.patient
    
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
        formset = PrescriptionItemFormSet(request.POST)
        
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
                # Create a single invoice for all prescribed items
                invoice = Invoice.objects.create(
                    patient=patient,
                    visit=prescription.visit,
                    status='Pending',
                    created_by=request.user,
                    notes=f"Prescription billing for meds: {', '.join([item.medication.name for item in prescription_items])}"
                )
                
                # Link invoice to prescription
                prescription.invoice = invoice
                prescription.save()
                
                for item in prescription_items:
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        inventory_item=item.medication,
                        name=item.medication.name,
                        unit_price=item.medication.selling_price,
                        quantity=item.quantity
                    )
                
                messages.success(request, f'Prescription and invoice created successfully for {patient.full_name}')
            else:
                messages.success(request, f'Prescription created successfully (no items) for {patient.full_name}')
                
            return redirect('home:patient_detail', pk=patient.id)
    else:
        form = PrescriptionForm()
        formset = PrescriptionItemFormSet()
    
    # Prepare medication metadata for JS
    from inventory.models import InventoryItem, InventoryCategory
    import json
    
    # Get Pharmaceuticals category
    pharma_category = InventoryCategory.objects.filter(name__icontains='Pharmaceutical').first()
    
    if pharma_category:
        medications = InventoryItem.objects.filter(category=pharma_category).select_related('category')
    else:
        medications = InventoryItem.objects.all().select_related('category')
    
    med_metadata = {}
    for item in medications:
        details = getattr(item, 'medication', None)
        med_metadata[item.id] = {
            'name': item.name,
            'generic_name': details.generic_name if details else '',
            'formulation': details.formulation if details else '',
            'is_dispensed_as_whole': item.is_dispensed_as_whole,
            'selling_price': str(item.selling_price)
        }
    
    context = {
        'form': form,
        'formset': formset,
        'patient': patient,
        'visit': visit,
        'med_metadata_json': json.dumps(med_metadata),
        # Add Dispensed Items context for the widget
        'dispensed_items': visit.dispensed_items.select_related('item', 'dispensed_by').order_by('-dispensed_at')
    }
    return render(request, 'home/create_prescription.html', context)

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
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Sum, Count
from datetime import timedelta
from .models import Prescription, PrescriptionItem
from inventory.models import InventoryItem, StockRecord, InventoryRequest
from home.models import Departments
from inpatient.models import MedicationChart


@login_required
def pharmacy_dashboard(request):
    """Pharmacy dashboard showing prescriptions, stock, and requests"""
    
    # Get or create pharmacy department
    pharmacy_dept, created = Departments.objects.get_or_create(
        name='Pharmacy',
        defaults={'abbreviation': 'PHR'}
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
        'medication'
    ).order_by('-prescription__prescribed_at')
    
    # Get pending IPD medications (from MedicationChart)
    pending_ipd_items = MedicationChart.objects.filter(
        is_dispensed=False
    ).select_related(
        'admission__patient',
        'admission__bed__ward',
        'prescribed_by',
        'item'
    ).order_by('-prescribed_at')
    
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
    
    # Get recently dispensed items (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    dispensed_items = PrescriptionItem.objects.filter(
        dispensed=True,
        dispensed_at__gte=thirty_days_ago
    ).select_related(
        'prescription__patient',
        'medication',
        'dispensed_by'
    ).order_by('-dispensed_at')[:50]  # Limit to 50 recent items
    
    # Apply dispensed search filter
    if dispensed_search:
        dispensed_items = PrescriptionItem.objects.filter(
            dispensed=True,
            dispensed_at__gte=thirty_days_ago
        ).filter(
            Q(prescription__patient__first_name__icontains=dispensed_search) |
            Q(prescription__patient__last_name__icontains=dispensed_search) |
            Q(medication__name__icontains=dispensed_search)
        ).select_related(
            'prescription__patient',
            'medication',
            'dispensed_by'
        ).order_by('-dispensed_at')[:50]
    
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
        # Calculate total quantity for this item across all batches
        total_qty = StockRecord.objects.filter(
            current_location=pharmacy_dept,
            item=stock.item
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        if total_qty <= stock.item.reorder_level:
            if stock not in low_stock_items:
                low_stock_items.append(stock)
        
        # Check for expiring items
        if stock.expiry_date and stock.expiry_date <= thirty_days_later:
            expiring_soon_items.append(stock)
    
    # Get inventory requests for pharmacy
    inventory_requests_all = InventoryRequest.objects.filter(
        location=pharmacy_dept
    ).select_related('item', 'requested_by').order_by('-requested_at')
    
    # Apply request search filter
    if request_search:
        inventory_requests_all = inventory_requests_all.filter(
            Q(item__name__icontains=request_search) |
            Q(requested_by__first_name__icontains=request_search) |
            Q(requested_by__last_name__icontains=request_search)
        )
    
    # Calculate pending count before slicing
    pending_requests_count = inventory_requests_all.filter(status='Pending').count()
    
    # Slice for display
    inventory_requests = inventory_requests_all[:20]
    
    # Statistics
    stats = {
        'pending_prescriptions': pending_items.count(),
        'pending_ipd_count': pending_ipd_items.count(),
        'low_stock_count': len(set(low_stock_items)),
        'pending_requests': pending_requests_count,
        'dispensed_today': PrescriptionItem.objects.filter(
            dispensed=True,
            dispensed_at__date=today
        ).count() + MedicationChart.objects.filter(
            is_dispensed=True,
            dispensed_at__date=today
        ).count(),
    }
    
    context = {
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
    }
    
    return render(request, 'home/pharmacy_dashboard.html', context)


@login_required
def dispense_medication(request, item_id):
    """Mark a prescription item as dispensed"""
    from django.http import JsonResponse
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})
    
    try:
        prescription_item = get_object_or_404(PrescriptionItem, pk=item_id)
        
        # Check if already dispensed
        if prescription_item.dispensed:
            return JsonResponse({
                'success': False,
                'error': 'This medication has already been dispensed'
            })
        
        # Check payment status
        prescription = prescription_item.prescription
        if prescription.invoice and prescription.invoice.status != 'Paid':
            return JsonResponse({
                'success': False,
                'error': f'Payment required. Invoice {prescription.invoice.id} is {prescription.invoice.status}.'
            })
        
        # Get pharmacy department
        pharmacy_dept = Departments.objects.get(name='Pharmacy')
        
        # Check stock availability
        available_stock = StockRecord.objects.filter(
            current_location=pharmacy_dept,
            item=prescription_item.medication,
            quantity__gte=prescription_item.quantity
        ).first()
        
        if not available_stock:
            return JsonResponse({
                'success': False,
                'error': f'Insufficient stock for {prescription_item.medication.name}'
            })
        
        # Mark as dispensed
        prescription_item.dispensed = True
        prescription_item.dispensed_at = timezone.now()
        prescription_item.dispensed_by = request.user
        prescription_item.save()
        
        # Reduce stock
        available_stock.quantity -= prescription_item.quantity
        available_stock.save()
        
        # Create stock adjustment record
        from inventory.models import StockAdjustment
        StockAdjustment.objects.create(
            item=prescription_item.medication,
            quantity=-prescription_item.quantity,
            adjustment_type='Usage',
            reason=f'Dispensed to {prescription_item.prescription.patient.full_name}',
            adjusted_by=request.user,
            adjusted_from=pharmacy_dept
        )
        
        return JsonResponse({
            'success': True,
            'message': f'{prescription_item.medication.name} dispensed successfully'
        })
        
    except Departments.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Pharmacy department not found'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@require_http_methods(["POST"])
def dispense_all_medications(request, prescription_id):
    """Mark all pending items in a prescription as dispensed"""
    try:
        prescription = get_object_or_404(Prescription, pk=prescription_id)
        pending_items = prescription.items.filter(dispensed=False)
        
        if not pending_items.exists():
            return JsonResponse({
                'success': False,
                'error': 'No pending items found for this prescription'
            })
        
        # Check payment status
        if prescription.invoice and prescription.invoice.status != 'Paid':
            return JsonResponse({
                'success': False,
                'error': f'Bulk dispensing blocked. Prescription invoice is {prescription.invoice.status}.'
            })
            
        pharmacy_dept = Departments.objects.get(name='Pharmacy')
        dispensed_count = 0
        errors = []
        
        from inventory.models import StockAdjustment
        
        for item in pending_items:
            # Check stock for each item
            available_stock = StockRecord.objects.filter(
                current_location=pharmacy_dept,
                item=item.medication,
                quantity__gte=item.quantity
            ).first()
            
            if not available_stock:
                errors.append(f'Insufficient stock for {item.medication.name}')
                continue
                
            # Perform dispensing
            item.dispensed = True
            item.dispensed_at = timezone.now()
            item.dispensed_by = request.user
            item.save()
            
            # Update stock
            available_stock.quantity -= item.quantity
            available_stock.save()
            
            # Record adjustment
            StockAdjustment.objects.create(
                item=item.medication,
                adjusted_from=pharmacy_dept,
                adjustment_type='Usage',
                quantity=-item.quantity,
                reason=f'Bulk Dispensed for Prescription #{prescription.id}',
                adjusted_by=request.user
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
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def dispense_ipd_medication(request, item_id):
    """Mark an inpatient medication (MedicationChart) as dispensed"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})
    
    try:
        med_item = get_object_or_404(MedicationChart, pk=item_id)
        
        # Check if already dispensed
        if med_item.is_dispensed:
            return JsonResponse({
                'success': False,
                'error': 'This medication has already been dispensed'
            })
        
        # Get pharmacy department
        pharmacy_dept = Departments.objects.get(name='Pharmacy')
        
        # Calculate quantity if it's 0 (smart dispensing)
        qty_to_dispense = med_item.quantity
        if qty_to_dispense == 0:
            qty_to_dispense = med_item.dose_count * med_item.frequency_count * med_item.duration_days
            
        if qty_to_dispense == 0:
             return JsonResponse({
                'success': False,
                'error': f'Dispense quantity for {med_item.item.name} is zero. Please check prescription.'
            })

        # Check stock availability
        available_stock = StockRecord.objects.filter(
            current_location=pharmacy_dept,
            item=med_item.item,
            quantity__gte=qty_to_dispense
        ).first()
        
        if not available_stock:
            return JsonResponse({
                'success': False,
                'error': f'Insufficient stock for {med_item.item.name}'
            })
        
        # Mark as dispensed
        med_item.is_dispensed = True
        med_item.dispensed_at = timezone.now()
        med_item.dispensed_by = request.user
        if med_item.quantity == 0:
            med_item.quantity = qty_to_dispense
        med_item.save()
        
        # Reduce stock
        available_stock.quantity -= qty_to_dispense
        available_stock.save()
        
        # Create stock adjustment record
        from inventory.models import StockAdjustment
        StockAdjustment.objects.create(
            item=med_item.item,
            quantity=-qty_to_dispense,
            adjustment_type='Usage',
            reason=f'Dispensed to IPD: {med_item.admission.patient.full_name}',
            adjusted_by=request.user,
            adjusted_from=pharmacy_dept
        )
        
        # Add to Invoice (Provisional Billing)
        try:
            from accounts.models import Invoice, InvoiceItem
            
            # Find or create a pending invoice for this visit
            invoice = Invoice.objects.filter(
                visit=med_item.admission.visit,
                status__in=['Draft', 'Pending']
            ).exclude(status='Cancelled').first()
            
            if not invoice:
                invoice = Invoice.objects.create(
                    patient=med_item.admission.patient,
                    visit=med_item.admission.visit,
                    status='Pending',
                    created_by=request.user,
                    notes=f"IPD Billing for Admission {med_item.admission.id}"
                )
            
            # Create invoice item
            InvoiceItem.objects.create(
                invoice=invoice,
                inventory_item=med_item.item,
                name=f"{med_item.item.name} (IPD Dispense)",
                quantity=qty_to_dispense,
                unit_price=med_item.item.selling_price
            )
        except Exception as inv_err:
            # Don't fail the dispense if invoicing fails, but log it
            print(f"Invoicing failed for med {med_item.id}: {str(inv_err)}")

        return JsonResponse({
            'success': True,
            'message': f'{med_item.item.name} dispensed to IPD successfully'
        })
        
    except Departments.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Pharmacy department not found'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

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
    consultation_queues = PatientQue.objects.filter(
        sent_to__name__icontains='Consultation',
        status='PENDING'
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
