from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .models import (
    Admission, Ward, Bed, InpatientDischarge, MedicationChart, 
    ServiceAdmissionLink, PatientVitals, ClinicalNote, 
    FluidBalance, WardTransfer, DoctorInstruction, NutritionOrder
)
from .forms import (
    AdmissionForm, MedicationChartForm, ServiceAdmissionLinkForm, 
    InpatientDischargeForm, PatientVitalsForm, ClinicalNoteForm, 
    FluidBalanceForm, WardTransferForm, DoctorInstructionForm, NutritionOrderForm
)
from home.models import Patient, Visit, Departments
from django.db.models import Count, Q, Sum, F
from django.utils import timezone
import math
from accounts.models import Service
from lab.models import LabResult
@login_required
def dashboard(request):
    # Analytics
    active_admissions = Admission.objects.filter(status='Admitted').select_related(
        'patient', 'bed', 'bed__ward'
    ).prefetch_related('vitals')
    
    total_admitted = active_admissions.count()
    
    total_beds = Bed.objects.count()
    occupied_beds = Bed.objects.filter(is_occupied=True).count()
    occupancy_rate = (occupied_beds / total_beds * 100) if total_beds > 0 else 0
    
    ward_stats = Ward.objects.annotate(
        occupied=Count('beds', filter=Q(beds__is_occupied=True)),
        total=Count('beds')
    )

    # Attach latest vitals to each admission
    for admission in active_admissions:
        admission.latest_vitals = admission.vitals.first()

    return render(request, 'inpatient/dashboard.html', {
        'active_admissions': active_admissions,
        'total_admitted': total_admitted,
        'occupancy_rate': round(occupancy_rate, 1),
        'ward_stats': ward_stats,
    })

@login_required
def admit_patient(request, patient_id):
    if request.user.role != 'Doctor':
        messages.error(request, "Only doctors can admit patients.")
        return redirect('home:patient_detail', pk=patient_id)
    
    patient = get_object_or_404(Patient, id=patient_id)
    
    # Check if already admitted
    if Admission.objects.filter(patient=patient, status='Admitted').exists():
        messages.warning(request, f"{patient.full_name} is already admitted.")
        return redirect('home:patient_detail', pk=patient.pk)
    
    if request.method == 'POST':
        form = AdmissionForm(request.POST, patient=patient)
        if form.is_valid():
            admission = form.save(commit=False)
            admission.patient = patient
            admission.admitted_by = request.user
            
            # Always create a new IN-PATIENT visit
            visit = Visit.objects.create(
                patient=patient,
                visit_type='IN-PATIENT',
                visit_mode='Walk In'
            )
            admission.visit = visit
            messages.info(request, f"New IN-PATIENT visit created for {patient.full_name}.")
                
            admission.save()
            messages.success(request, f"Patient {patient.full_name} admitted successfully.")
            return redirect('inpatient:patient_case_folder', admission_id=admission.id)
    else:
        form = AdmissionForm(patient=patient)
        
    return render(request, 'inpatient/admit_patient.html', {
        'form': form,
        'patient': patient,
        'title': f'Admit Patient: {patient.full_name}'
    })

@login_required
def patient_case_folder(request, admission_id):
    admission = get_object_or_404(Admission, id=admission_id)
    
    # Clinical Data
    vitals = admission.vitals.all().order_by('-recorded_at')[:10]
    vitals_history = admission.vitals.all().order_by('recorded_at')[:20]  # For charts
    latest_vitals = vitals[0] if vitals else None
    notes = admission.clinical_notes.all().order_by('-created_at')
    fluid_intake = admission.fluid_balances.filter(fluid_type='Intake').aggregate(total=Sum('amount_ml'))['total'] or 0
    fluid_output = admission.fluid_balances.filter(fluid_type='Output').aggregate(total=Sum('amount_ml'))['total'] or 0
    
    # Forms
    vitals_form = PatientVitalsForm()
    note_form = ClinicalNoteForm()
    fluid_form = FluidBalanceForm()
    med_form = MedicationChartForm()
    instruction_form = DoctorInstructionForm()
    nutrition_form = NutritionOrderForm()
    transfer_form = WardTransferForm(initial={'ward': admission.bed.ward if admission.bed else None})
    if admission.bed:
        transfer_form.fields['to_bed'].queryset = Bed.objects.filter(is_occupied=False, ward=admission.bed.ward)
    
    # Clinical orders
    instructions = admission.instructions.all().order_by('-created_at')
    nutrition_orders = admission.nutrition_orders.all().order_by('-prescribed_at')
    current_nutrition = nutrition_orders.first()

    # Consolidated Activity Log
    activity_log = []
    
    # 1. Vitals
    for v in admission.vitals.all():
        activity_log.append({
            'time': v.recorded_at,
            'type': 'Vitals',
            'icon': 'fa-heartbeat',
            'color': 'rose',
            'title': 'Vitals Recorded',
            'detail': f"Temp: {v.temperature}°C, Pulse: {v.pulse_rate}bpm, BP: {v.systolic_bp}/{v.diastolic_bp}",
            'user': v.recorded_by
        })
    
    # 2. Clinical Notes
    for n in admission.clinical_notes.all():
        activity_log.append({
            'time': n.created_at,
            'type': 'Note',
            'icon': 'fa-notes-medical',
            'color': 'indigo',
            'title': f"{n.get_note_type_display()}",
            'detail': (n.content[:100] + '...') if len(n.content) > 100 else n.content,
            'user': n.created_by
        })
        
    # 3. Medications
    for m in admission.medications.all():
        activity_log.append({
            'time': m.prescribed_at,
            'type': 'Medication',
            'icon': 'fa-pills',
            'color': 'purple',
            'title': 'Medication Prescribed',
            'detail': f"{m.item.name} - {m.dosage}",
            'user': m.prescribed_by
        })
        if m.is_administered:
             activity_log.append({
                'time': m.administered_at,
                'type': 'Medication',
                'icon': 'fa-check-circle',
                'color': 'emerald',
                'title': 'Medication Administered',
                'detail': f"{m.item.name} given",
                'user': m.administered_by
            })

    # 4. Fluid Balance
    for f in admission.fluid_balances.all():
        activity_log.append({
            'time': f.recorded_at,
            'type': 'Fluid',
            'icon': 'fa-tint',
            'color': 'blue',
            'title': f"Fluid {f.fluid_type}",
            'detail': f"{f.amount_ml}ml - {f.item}",
            'user': f.recorded_by
        })

    # 5. Transfers
    for t in admission.transfers.all():
        activity_log.append({
            'time': t.transferred_at,
            'type': 'Transfer',
            'icon': 'fa-exchange-alt',
            'color': 'slate',
            'title': 'Ward Transfer',
            'detail': f"From {t.from_bed} to {t.to_bed}",
            'user': t.transferred_by
        })

    # 6. Instructions
    for i in admission.instructions.all():
        activity_log.append({
            'time': i.created_at,
            'type': 'Instruction',
            'icon': 'fa-user-md',
            'color': 'amber',
            'title': f"{i.instruction_type} Order",
            'detail': i.instruction,
            'user': i.created_by
        })
        if i.is_completed:
            activity_log.append({
                'time': i.completed_at,
                'type': 'Instruction',
                'icon': 'fa-check-double',
                'color': 'emerald',
                'title': 'Instruction Completed',
                'detail': i.instruction[:50],
                'user': i.completed_by
            })

    # 7. Nutrition
    for nu in admission.nutrition_orders.all():
        activity_log.append({
            'time': nu.prescribed_at,
            'type': 'Nutrition',
            'icon': 'fa-utensils',
            'color': 'orange',
            'title': 'Nutrition Order',
            'detail': f"{nu.diet_type} - {nu.specific_instructions[:50]}",
            'user': nu.prescribed_by
        })

    activity_log.sort(key=lambda x: x['time'] or timezone.now(), reverse=True)

    # Get medical tests services for the Next Action section
    # FILTERED BY DEPARTMENT: Lab, Imaging, Procedure, etc.
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
            'department_name': test.department.name.lower(),
            'price': str(test.price) if test.price else None
        })
    import json

    # Serialize vitals for Chart.js
    vitals_data = {
        'times': [v.recorded_at.strftime('%H:%M') for v in vitals_history],
        'temp': [float(v.temperature) if v.temperature else None for v in vitals_history],
        'pulse': [v.pulse_rate for v in vitals_history],
        'systolic': [v.systolic_bp for v in vitals_history],
        'diastolic': [v.diastolic_bp for v in vitals_history],
        'spo2': [v.spo2 for v in vitals_history],
    }

    # Check if invoice is paid for discharge button restriction
    from accounts.models import Invoice
    invoice = Invoice.objects.filter(visit=admission.visit).exclude(status='Cancelled').first()
    invoice_is_paid = invoice.status == 'Paid' if invoice else False

    # Prepare medication metadata for smart prescription JS
    from inventory.models import InventoryItem
    import json
    med_metadata = {}
    for item in InventoryItem.objects.filter(item_type='Medicine').select_related('medication'):
        details = getattr(item, 'medication', None)
        med_metadata[item.id] = {
            'name': item.name,
            'strength': details.strength if details else '',
            'formulation': details.formulation if details else '',
            'is_controlled': details.is_controlled if details else False,
            'is_dispensed_as_whole': item.is_dispensed_as_whole,
            'selling_price': str(item.selling_price)
        }

    return render(request, 'inpatient/patient_case_folder.html', {
        'admission': admission,
        'vitals': vitals,
        'vitals_history': vitals_history,
        'vitals_data': vitals_data,
        'latest_vitals': latest_vitals,
        'notes': notes,
        'fluid_intake': fluid_intake,
        'fluid_output': fluid_output,
        'vitals_form': vitals_form,
        'note_form': note_form,
        'fluid_form': fluid_form,
        'med_form': med_form,
        'instruction_form': instruction_form,
        'nutrition_form': nutrition_form,
        'transfer_form': transfer_form,
        'medications': admission.medications.all().order_by('-prescribed_at'),
        'instructions': instructions,
        'nutrition_orders': nutrition_orders,
        'current_nutrition': current_nutrition,
        'activity_log': activity_log,
        'medical_tests_data': medical_tests_data,
        'available_departments': Departments.objects.all().order_by('name'),
        'lab_results': LabResult.objects.filter(patient=admission.patient).select_related('service', 'requested_by').order_by('-requested_at'),
        'invoice_is_paid': invoice_is_paid,
        'med_metadata_json': json.dumps(med_metadata),
        'title': f"Case Folder: {admission.patient.full_name}"
    })

@login_required
def add_vitals(request, admission_id):
    admission = get_object_or_404(Admission, id=admission_id)
    if request.method == 'POST':
        form = PatientVitalsForm(request.POST)
        if form.is_valid():
            vitals = form.save(commit=False)
            vitals.admission = admission
            vitals.recorded_by = request.user
            vitals.save()
            messages.success(request, "Vitals recorded successfully.")
        else:
            messages.error(request, "Error recording vitals.")
    return redirect(f'/inpatient/admissions/{admission.id}/case-folder/?tab=timeline')

@login_required
def add_clinical_note(request, admission_id):
    if request.user.role != 'Doctor':
        messages.error(request, "Only doctors can record clinical notes.")
        return redirect('inpatient:patient_case_folder', admission_id=admission_id)
    
    admission = get_object_or_404(Admission, id=admission_id)
    if request.method == 'POST':
        form = ClinicalNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.admission = admission
            note.created_by = request.user
            note.save()
            messages.success(request, "Clinical note added.")
        else:
            messages.error(request, "Error adding clinical note.")
    return redirect(f'/inpatient/admissions/{admission.id}/case-folder/?tab=notes')

@login_required
def add_fluid_balance(request, admission_id):
    admission = get_object_or_404(Admission, id=admission_id)
    if request.method == 'POST':
        form = FluidBalanceForm(request.POST)
        if form.is_valid():
            fluid = form.save(commit=False)
            fluid.admission = admission
            fluid.recorded_by = request.user
            fluid.save()
            messages.success(request, "Fluid balance entry recorded.")
        else:
            messages.error(request, "Error recording fluid balance.")
    return redirect(f'/inpatient/admissions/{admission.id}/case-folder/?tab=fluids')

@login_required
def transfer_patient(request, admission_id):
    if request.user.role != 'Doctor':
        messages.error(request, "Only doctors can order ward transfers.")
        return redirect('inpatient:patient_case_folder', admission_id=admission_id)
    
    admission = get_object_or_404(Admission, id=admission_id)
    if request.method == 'POST':
        form = WardTransferForm(request.POST)
        if form.is_valid():
            transfer = form.save(commit=False)
            transfer.admission = admission
            transfer.from_bed = admission.bed
            transfer.transferred_by = request.user
            transfer.save()
            messages.success(request, f"Patient transferred to {transfer.to_bed}.")
        else:
            messages.error(request, "Error during transfer.")
    return redirect('inpatient:patient_case_folder', admission_id=admission.id)

@login_required
def add_medication(request, admission_id):
    if request.user.role != 'Doctor':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Only doctors can prescribe inpatient medications.'})
        messages.error(request, "Only doctors can prescribe inpatient medications.")
        return redirect('inpatient:patient_case_folder', admission_id=admission_id)
    
    admission = get_object_or_404(Admission, id=admission_id)
    if request.method == 'POST':
        form = MedicationChartForm(request.POST)
        if form.is_valid():
            med = form.save(commit=False)
            med.admission = admission
            med.prescribed_by = request.user
            med.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Medication added successfully.'})
            messages.success(request, "Medication added.")
            return redirect(f'/inpatient/admissions/{admission.id}/case-folder/?tab=medications')
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': form.errors.as_json()})
    return redirect('inpatient:patient_case_folder', admission_id=admission.id)

@login_required
def add_service(request, admission_id):
    if request.user.role != 'Doctor':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Only doctors can request ward services.'})
        messages.error(request, "Only doctors can request ward services.")
        return redirect('inpatient:patient_case_folder', admission_id=admission_id)
    
    admission = get_object_or_404(Admission, id=admission_id)
    if request.method == 'POST':
        form = ServiceAdmissionLinkForm(request.POST)
        if form.is_valid():
            service_link = form.save(commit=False)
            service_link.admission = admission
            service_link.provided_by = request.user
            service_link.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Service added successfully.'})
            messages.success(request, "Service added.")
            return redirect('inpatient:patient_case_folder', admission_id=admission.id)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': form.errors.as_json()})
    return redirect('inpatient:patient_case_folder', admission_id=admission.id)

@login_required
def administer_medication(request, medication_id):
    medication = get_object_or_404(MedicationChart, id=medication_id)
    if not medication.is_administered:
        medication.is_administered = True
        medication.administered_at = timezone.now()
        medication.administered_by = request.user
        medication.save()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': f'{medication.item.name} administered.'})
        messages.success(request, f"Medication {medication.item.name} administered.")
    return redirect('inpatient:patient_case_folder', admission_id=medication.admission.id)

@login_required
def add_doctor_instruction(request, admission_id):
    if request.user.role != 'Doctor':
        messages.error(request, "Only doctors can record instructions.")
        return redirect('inpatient:patient_case_folder', admission_id=admission_id)
    
    admission = get_object_or_404(Admission, id=admission_id)
    if request.method == 'POST':
        form = DoctorInstructionForm(request.POST)
        if form.is_valid():
            instruction = form.save(commit=False)
            instruction.admission = admission
            instruction.created_by = request.user
            instruction.save()
            messages.success(request, "Instruction recorded.")
        else:
            messages.error(request, "Error recording instruction.")
    return redirect(f'/inpatient/admissions/{admission.id}/case-folder/?tab=instructions')

@login_required
def complete_instruction(request, instruction_id):
    instruction = get_object_or_404(DoctorInstruction, id=instruction_id)
    instruction.is_completed = True
    instruction.completed_at = timezone.now()
    instruction.completed_by = request.user
    instruction.save()
    messages.success(request, "Instruction marked as completed.")
    return redirect('inpatient:patient_case_folder', admission_id=instruction.admission.id)

@login_required
def add_nutrition_order(request, admission_id):
    admission = get_object_or_404(Admission, id=admission_id)
    if request.method == 'POST':
        form = NutritionOrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.admission = admission
            order.prescribed_by = request.user
            order.save()
            messages.success(request, "Nutrition order updated.")
        else:
            messages.error(request, "Error updating nutrition order.")
    return redirect(f'/inpatient/admissions/{admission.id}/case-folder/?tab=nutrition')

@login_required
def discharge_patient(request, admission_id):
    if request.user.role != 'Doctor':
        messages.error(request, "Only doctors can discharge patients.")
        return redirect('inpatient:patient_case_folder', admission_id=admission_id)
    
    admission = get_object_or_404(Admission, id=admission_id)
    
    if admission.status != 'Admitted':
        messages.warning(request, f"Patient {admission.patient.full_name} is not currently admitted.")
        return redirect('home:patient_detail', pk=admission.patient.pk)

    # Calculate Billing
    now = timezone.now()
    duration = now - admission.admitted_at
    days_stayed = max(1, math.ceil(duration.total_seconds() / 86400))
    
    # Calculate Billing based on logged services (now includes daily bed charges)
    ward_cost = admission.services.filter(
        service__category='Admission/Accommodation'
    ).aggregate(
        total=Sum(F('service__price') * F('quantity'))
    )['total'] or 0
    
    med_cost = admission.medications.filter(is_dispensed=True).aggregate(
        total=Sum(F('item__selling_price') * F('quantity'))
    )['total'] or 0
    
    service_cost = admission.services.exclude(
        service__category='Admission/Accommodation'
    ).aggregate(
        total=Sum(F('service__price') * F('quantity'))
    )['total'] or 0
    
    total_bill = ward_cost + med_cost + service_cost

    if request.method == 'POST':
        form = InpatientDischargeForm(request.POST)
        if form.is_valid():
            discharge = form.save(commit=False)
            discharge.admission = admission
            discharge.total_bill_snapshot = total_bill
            discharge.discharged_by = request.user
            discharge.save()
            
            # Update admission
            admission.status = 'Discharged'
            admission.discharged_at = now
            admission.discharged_by = request.user
            admission.save()
            
            messages.success(request, f"Patient {admission.patient.full_name} has been discharged.")
            return redirect('inpatient:discharge_summary', pk=discharge.pk)
    else:
        form = InpatientDischargeForm()

    return render(request, 'inpatient/discharge_patient.html', {
        'admission': admission,
        'form': form,
        'days_stayed': days_stayed,
        'ward_cost': ward_cost,
        'med_cost': med_cost,
        'service_cost': service_cost,
        'total_bill': total_bill,
        'title': f'Discharge: {admission.patient.full_name}'
    })

@login_required
def get_available_beds(request, ward_id):
    beds = Bed.objects.filter(ward_id=ward_id, is_occupied=False).values('id', 'bed_number', 'bed_type')
    return JsonResponse({'beds': list(beds)})

@login_required
def discharge_summary(request, pk):
    discharge = get_object_or_404(InpatientDischarge, pk=pk)
    admission = discharge.admission
    
    return render(request, 'inpatient/inpatient_discharge_summary.html', {
        'discharge': discharge,
        'admission': admission,
        'medications': admission.medications.filter(is_dispensed=True).select_related('item'),
        'services': admission.services.all().select_related('service'),
        'title': f'Discharge Summary: {admission.patient.full_name}'
    })
@login_required
def admission_patient_list(request):
    """View to select a patient for admission"""
    query = request.GET.get('search', '')
    if query:
        patients = Patient.objects.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(phone__icontains=query) |
            Q(id_number__icontains=query)
        ).order_by('-created_at')
    else:
        patients = Patient.objects.all().order_by('-created_at')[:20]  # Limit initial load
    
    # Check admission status for each patient
    for patient in patients:
        patient.is_admitted = Admission.objects.filter(patient=patient, status='Admitted').exists()
        
    return render(request, 'inpatient/admission_patient_list.html', {
        'patients': patients,
        'title': 'New Admission - Select Patient'
    })
