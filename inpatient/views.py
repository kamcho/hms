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
from home.models import Patient, Visit, Departments, Prescription, PrescriptionItem
from home.forms import PrescriptionItemForm
from django.forms import inlineformset_factory
from django.db.models import Count, Q, Sum, F
from django.utils import timezone
import math
from accounts.models import Service, Invoice, InvoiceItem
from accounts.utils import get_or_create_invoice
from lab.models import LabResult
@login_required
def dashboard(request):
    # Analytics
    active_admissions = Admission.objects.filter(status='Admitted').select_related(
        'patient', 'bed', 'bed__ward'
    ).prefetch_related('vitals', 'delivery')
    
    total_admitted = active_admissions.count()
    
    total_beds = Bed.objects.count()
    occupied_beds = Bed.objects.filter(is_occupied=True).count()
    occupancy_rate = (occupied_beds / total_beds * 100) if total_beds > 0 else 0
    
    ward_stats = Ward.objects.annotate(
        occupied=Count('beds', filter=Q(beds__is_occupied=True)),
        total=Count('beds')
    )

    # Recent Discharges
    recent_discharges = InpatientDischarge.objects.select_related(
        'admission', 'admission__patient', 'admission__bed', 'admission__bed__ward', 'admission__visit'
    ).order_by('-discharge_date')[:10]

    # Attach latest vitals to each admission
    for admission in active_admissions:
        admission.latest_vitals = admission.vitals.first()

    return render(request, 'inpatient/dashboard.html', {
        'active_admissions': active_admissions,
        'recent_discharges': recent_discharges,
        'total_admitted': total_admitted,
        'occupancy_rate': round(occupancy_rate, 1),
        'ward_stats': ward_stats,
    })

@login_required
def admit_patient(request, patient_id):
    # Debug: Check user role
    print(f"DEBUG: User role = {request.user.role}")
    print(f"DEBUG: User = {request.user}")
    print(f"DEBUG: Is authenticated = {request.user.is_authenticated}")
    
    if request.user.role not in ['Doctor', 'Nurse']:
        print(f"DEBUG: Access denied for role: {request.user.role}")
        messages.error(request, "Only doctors and nurses can admit patients.")
        return redirect('home:patient_detail', pk=patient_id)
    
    print(f"DEBUG: Access granted for role: {request.user.role}")
    patient = get_object_or_404(Patient, id=patient_id)
    print(f"DEBUG: Patient = {patient.full_name} (ID: {patient.id})")
    
    # Get invoice_id from URL parameter (for Extend to IPD functionality)
    invoice_id = request.GET.get('invoice_id')
    print(f"DEBUG: Invoice ID from URL = {invoice_id}")
    
    # Check if already admitted
    is_already_admitted = Admission.objects.filter(patient=patient, status='Admitted').exists()
    print(f"DEBUG: Is already admitted = {is_already_admitted}")
    
    # For Extend to IPD functionality, allow admission even if already admitted
    # This will close the current admission and create a new one
    if is_already_admitted and not invoice_id:
        print(f"DEBUG: Patient already admitted without invoice_id, redirecting...")
        messages.warning(request, f"{patient.full_name} is already admitted.")
        return redirect('home:patient_detail', pk=patient.pk)
    
    print(f"DEBUG: Continuing with admission process...")
    
    previous_invoice = None
    if invoice_id:
        try:
            previous_invoice = Invoice.objects.get(id=invoice_id, patient=patient)
            print(f"DEBUG: Previous invoice found = {previous_invoice}")
        except Invoice.DoesNotExist:
            print(f"DEBUG: Invoice not found, clearing invoice_id")
            messages.error(request, "Invalid invoice ID provided.")
            invoice_id = None
    
    if request.method == 'POST':
        form = AdmissionForm(request.POST, patient=patient)
        if form.is_valid():
            admission = form.save(commit=False)
            admission.patient = patient
            admission.admitted_by = request.user
            
            # For Extend to IPD: Close existing admission if exists
            if is_already_admitted:
                print(f"DEBUG: Closing existing admission for Extend to IPD")
                existing_admission = Admission.objects.get(patient=patient, status='Admitted')
                existing_admission.status = 'Discharged'
                existing_admission.discharged_at = timezone.now()
                existing_admission.discharged_by = request.user
                existing_admission.save()
                
                # Release the bed
                if existing_admission.bed:
                    existing_admission.bed.is_occupied = False
                    existing_admission.bed.save()
                
                messages.info(request, f"Previous admission closed. Extending to new IPD admission.")
            
            # Deactivate any existing active visits (e.g., from OPD or Maternity)
            Visit.objects.filter(patient=patient, is_active=True).update(is_active=False)
            
            # Always create a new IN-PATIENT visit
            visit = Visit.objects.create(
                patient=patient,
                visit_type='IN-PATIENT',
                visit_mode='Walk In'
            )
            admission.visit = visit
            
            # Handle invoice mirroring if previous_invoice exists
            if previous_invoice:
                # Create new invoice for the new visit
                from accounts.utils import get_or_create_invoice
                new_invoice = get_or_create_invoice(visit=visit, user=request.user)
                
                # Copy only Normal Delivery items from previous invoice to new invoice
                for item in previous_invoice.items.all():
                    print(f"DEBUG: Checking item - Service: {item.service}, Name: {item.name}, Amount: {item.amount}")
                    
                    # Only copy Normal Delivery service items
                    if item.service and item.service.name == 'Normal Delivery':
                        InvoiceItem.objects.create(
                            invoice=new_invoice,
                            service=item.service,
                            inventory_item=item.inventory_item,
                            name=item.name,
                            quantity=item.quantity,
                            unit_price=item.unit_price,
                            amount=item.amount,
                            paid_amount=item.paid_amount,
                            created_by=request.user
                        )
                        print(f"DEBUG: Copied Normal Delivery item: {item.name} (Amount: {item.amount})")
                    else:
                        print(f"DEBUG: Skipped non-Normal Delivery item: {item.name}")
                
                # Set all unpaid items in previous invoice to paid (only if not already paid)
                unpaid_items = previous_invoice.items.filter(
                    Q(paid_amount__lt=F('amount')) | Q(paid_amount=0)
                )
                if unpaid_items.exists():
                    # Mark items as fully paid by setting paid_amount = amount
                    unpaid_items.update(paid_amount=F('amount'))
                    print(f"DEBUG: Marked {unpaid_items.count()} unpaid items as paid in previous invoice")
                    
                    # Update invoice status to Canceled since it was transferred to IPD
                    previous_invoice.status = 'Canceled'
                    previous_invoice.save()
                    print(f"DEBUG: Updated invoice #{previous_invoice.id} status to: {previous_invoice.status}")
                else:
                    print(f"DEBUG: All items already paid in previous invoice")
                
                messages.success(request, f"Extended to IPD successfully. Unpaid items from Invoice #{previous_invoice.id} have been transferred to new visit.")
            
            admission.save()
            messages.success(request, f"Patient {patient.full_name} admitted successfully.")
            return redirect('inpatient:patient_case_folder', admission_id=admission.id)
    else:
        form = AdmissionForm(patient=patient)
        
    return render(request, 'inpatient/admit_patient.html', {
        'form': form,
        'patient': patient,
        'title': f'Admit Patient: {patient.full_name}',
        'previous_invoice': previous_invoice
    })

@login_required
def patient_case_folder(request, admission_id):
    admission = get_object_or_404(Admission, id=admission_id)
    all_admissions = Admission.objects.filter(patient=admission.patient).order_by('-admitted_at')
    
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

    # 8. Consumables (New requested/dispensed items)
    from inpatient.models import InpatientConsumable
    for c in admission.consumables.all():
        activity_log.append({
            'time': c.prescribed_at,
            'type': 'Consumable',
            'icon': 'fa-box-open',
            'color': 'indigo',
            'title': 'Consumable Requested',
            'detail': f"{c.item.name} x{c.quantity} requested",
            'user': c.prescribed_by
        })
        if c.is_dispensed:
            activity_log.append({
                'time': c.dispensed_at,
                'type': 'Consumable',
                'icon': 'fa-check-double',
                'color': 'emerald',
                'title': 'Consumable Dispensed',
                'detail': f"{c.item.name} x{c.quantity} released from pharmacy",
                'user': c.dispensed_by
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

    # 8. Consumables History (Unified UI list)
    from inventory.models import DispensedItem
    from inpatient.models import InpatientConsumable
    
    # Get all tracking records (Pending + Dispensed via new flow)
    consumable_reqs = InpatientConsumable.objects.filter(admission=admission).select_related('item', 'prescribed_by', 'dispensed_by')
    
    # Get all legacy/OPD dispensed items for this visit
    legacy_dispensed = DispensedItem.objects.filter(visit=admission.visit).select_related('item', 'dispensed_by')
    
    dispensed_items_ui = []
    
    # Add requests
    for req in consumable_reqs:
        dispensed_items_ui.append({
            'item_name': req.item.name,
            'status': 'Dispensed' if req.is_dispensed else 'Pending',
            'status_class': 'bg-emerald-100 text-emerald-700' if req.is_dispensed else 'bg-amber-100 text-amber-700',
            'at': req.dispensed_at if req.is_dispensed else req.prescribed_at,
            'by': req.dispensed_by if req.is_dispensed else req.prescribed_by,
            'quantity': req.quantity
        })
        
    # Add legacy items (avoid duplicates if possible, though visit_id + item_id might clash)
    processed_new_flow_keys = set((req.item_id, req.quantity) for req in consumable_reqs if req.is_dispensed)
    for ld in legacy_dispensed:
        if (ld.item_id, ld.quantity) not in processed_new_flow_keys:
            dispensed_items_ui.append({
                'item_name': ld.item.name,
                'status': 'Dispensed',
                'status_class': 'bg-emerald-100 text-emerald-700',
                'at': ld.dispensed_at,
                'by': ld.dispensed_by,
                'quantity': ld.quantity
            })
            
    # Sort UI list by date
    dispensed_items_ui.sort(key=lambda x: x['at'] or timezone.now(), reverse=True)

    # 9. Procedures (Invoiced items linked to a Service in Procedure Room)
    from accounts.models import InvoiceItem
    performed_procedures = InvoiceItem.objects.filter(
        invoice__visit=admission.visit, 
        service__department__name='Procedure Room'
    ).select_related('service').order_by('-created_at')

    return render(request, 'inpatient/patient_case_folder.html', {
        'performed_procedures': performed_procedures,
        'dispensed_items': dispensed_items_ui,
        'admission': admission,
        'all_admissions': all_admissions,
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
        'medical_tests_data': medical_tests_data,
        'available_departments': Departments.objects.all().order_by('name'),
        'dispensing_departments': Departments.objects.all().order_by('name'),
        'lab_results': LabResult.objects.filter(patient=admission.patient).select_related('service', 'requested_by').order_by('-requested_at'),
        'invoice_is_paid': invoice_is_paid,
        'med_metadata_json': json.dumps(med_metadata),
        'title': f"Case Folder: {admission.patient.full_name}"
    })

@login_required
def add_vitals(request, admission_id):
    admission = get_object_or_404(Admission, id=admission_id)
    
    # Block if not latest visit
    from home.models import Visit
    latest_visit = Visit.objects.filter(patient=admission.patient).order_by('-visit_date').first()
    if admission.visit != latest_visit:
        messages.error(request, "Cannot modify records for a previous visit.")
        return redirect('inpatient:patient_case_folder', admission_id=admission.id)
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
    if request.user.role not in ['Doctor', 'Nurse']:
        messages.error(request, "Only doctors and nurses can record clinical notes.")
        return redirect('inpatient:patient_case_folder', admission_id=admission_id)
    
    admission = get_object_or_404(Admission, id=admission_id)
    
    # Block if not latest visit
    from home.models import Visit
    latest_visit = Visit.objects.filter(patient=admission.patient).order_by('-visit_date').first()
    if admission.visit != latest_visit:
        messages.error(request, "Cannot modify records for a previous visit.")
        return redirect('inpatient:patient_case_folder', admission_id=admission.id)
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
    
    # Block if not latest visit
    from home.models import Visit
    latest_visit = Visit.objects.filter(patient=admission.patient).order_by('-visit_date').first()
    if admission.visit != latest_visit:
        messages.error(request, "Cannot modify records for a previous visit.")
        return redirect('inpatient:patient_case_folder', admission_id=admission.id)
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
    
    # Block if not latest visit
    from home.models import Visit
    latest_visit = Visit.objects.filter(patient=admission.patient).order_by('-visit_date').first()
    if admission.visit != latest_visit:
        messages.error(request, "Cannot modify records for a previous visit.")
        return redirect('inpatient:patient_case_folder', admission_id=admission.id)
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
    
    # Block if not latest visit
    from home.models import Visit
    latest_visit = Visit.objects.filter(patient=admission.patient).order_by('-visit_date').first()
    if admission.visit != latest_visit:
        error_msg = "Cannot modify records for a previous visit."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg})
        messages.error(request, error_msg)
        return redirect('inpatient:patient_case_folder', admission_id=admission.id)
    if request.method == 'POST':
        form = MedicationChartForm(request.POST)
        if form.is_valid():
            med = form.save(commit=False)
            med.admission = admission
            med.prescribed_by = request.user
            med.save()
            
            # Auto-generate MAR grid
            from .models import MedicationAdministrationRecord
            
            # Map frequency strings to doses per day
            freq_map = {
                'Once Daily': 1,
                'Twice Daily': 2,
                'Thrice Daily': 3,
                'Four Times Daily': 4,
                'Every 6 Hours': 4,
                'Every 8 Hours': 3,
                'Every 12 Hours': 2,
                'Every 24 Hours': 1,
                'As Needed': 1, # Default to 1 slot for PRN, can be expanded later
            }
            doses_per_day = freq_map.get(med.frequency, 1)
            
            mar_entries = []
            for day in range(1, med.duration_days + 1):
                for dose in range(1, doses_per_day + 1):
                    mar_entries.append(
                        MedicationAdministrationRecord(
                            chart=med,
                            day_number=day,
                            dose_number=dose,
                            status='Pending'
                        )
                    )
            if mar_entries:
                MedicationAdministrationRecord.objects.bulk_create(mar_entries)

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
    
    # Block if not latest visit
    from home.models import Visit
    latest_visit = Visit.objects.filter(patient=admission.patient).order_by('-visit_date').first()
    if admission.visit != latest_visit:
        error_msg = "Cannot modify records for a previous visit."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg})
        messages.error(request, error_msg)
        return redirect('inpatient:patient_case_folder', admission_id=admission.id)
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
    from .models import MedicationAdministrationRecord
    
    # In the new flow, the ID passed is actually the MedicationAdministrationRecord ID
    try:
        record = MedicationAdministrationRecord.objects.get(id=medication_id)
        medication = record.chart
        is_legacy = False
    except MedicationAdministrationRecord.DoesNotExist:
        # Fallback for old prescriptions before we added MAR
        medication = get_object_or_404(MedicationChart, id=medication_id)
        record = None
        is_legacy = True
        
    admission = medication.admission
    
    # Block if not latest visit
    from home.models import Visit
    latest_visit = Visit.objects.filter(patient=admission.patient).order_by('-visit_date').first()
    if admission.visit != latest_visit:
        error_msg = "Cannot modify records for a previous visit."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg})
        messages.error(request, error_msg)
        return redirect('inpatient:patient_case_folder', admission_id=admission.id)
        
    if not is_legacy:
        if record.status != 'Administered':
            record.status = 'Administered'
            record.administered_at = timezone.now()
            record.administered_by = request.user
            record.save()
            
            # Update parent chart to show latest activity
            medication.is_administered = True
            medication.administered_at = record.administered_at
            medication.administered_by = record.administered_by
            medication.save()
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': f'{medication.item.name} Dose {record.dose_number} administered.'})
            messages.success(request, f"Dose {record.dose_number} of {medication.item.name} administered.")
    else:
        # Legacy fallback
        if not medication.is_administered:
            medication.is_administered = True
            medication.administered_at = timezone.now()
            medication.administered_by = request.user
            medication.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': f'{medication.item.name} administered.'})
            messages.success(request, f"Medication {medication.item.name} administered.")
            
    return redirect(f'/inpatient/admissions/{admission.id}/case-folder/?tab=medications')

@login_required
def add_doctor_instruction(request, admission_id):
    if request.user.role != 'Doctor':
        messages.error(request, "Only doctors can record instructions.")
        return redirect('inpatient:patient_case_folder', admission_id=admission_id)
    
    admission = get_object_or_404(Admission, id=admission_id)
    
    # Block if not latest visit
    from home.models import Visit
    latest_visit = Visit.objects.filter(patient=admission.patient).order_by('-visit_date').first()
    if admission.visit != latest_visit:
        messages.error(request, "Cannot modify records for a previous visit.")
        return redirect('inpatient:patient_case_folder', admission_id=admission.id)
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
    admission = instruction.admission
    
    # Block if not latest visit
    from home.models import Visit
    latest_visit = Visit.objects.filter(patient=admission.patient).order_by('-visit_date').first()
    if admission.visit != latest_visit:
        messages.error(request, "Cannot modify records for a previous visit.")
        return redirect('inpatient:patient_case_folder', admission_id=admission.id)
    instruction.is_completed = True
    instruction.completed_at = timezone.now()
    instruction.completed_by = request.user
    instruction.save()
    messages.success(request, "Instruction marked as completed.")
    return redirect('inpatient:patient_case_folder', admission_id=instruction.admission.id)

@login_required
def add_nutrition_order(request, admission_id):
    admission = get_object_or_404(Admission, id=admission_id)
    
    # Block if not latest visit
    from home.models import Visit
    latest_visit = Visit.objects.filter(patient=admission.patient).order_by('-visit_date').first()
    if admission.visit != latest_visit:
        messages.error(request, "Cannot modify records for a previous visit.")
        return redirect('inpatient:patient_case_folder', admission_id=admission.id)
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
    
    # Calculate Billing based on stay duration and logged services
    ward_cost = days_stayed * admission.bed.ward.base_charge_per_day
    
    med_cost = admission.medications.filter(is_dispensed=True).aggregate(
        total=Sum(F('item__selling_price') * F('quantity'))
    )['total'] or 0
    
    service_cost = admission.services.exclude(
        service__department__name='Inpatient'
    ).aggregate(
        total=Sum(F('service__price') * F('quantity'))
    )['total'] or 0
    
    total_bill = ward_cost + med_cost + service_cost

    # Create formset for take-home prescriptions
    PrescriptionItemFormSet = inlineformset_factory(
        Prescription,
        PrescriptionItem,
        form=PrescriptionItemForm,
        extra=3,
        can_delete=True
    )

    if request.method == 'POST':
        form = InpatientDischargeForm(request.POST)
        formset = PrescriptionItemFormSet(request.POST, prefix='meds')
        
        if form.is_valid() and formset.is_valid():
            discharge = form.save(commit=False)
            discharge.admission = admission
            discharge.total_bill_snapshot = total_bill
            discharge.discharged_by = request.user
            discharge.save()
            
            # Handle take-home medications if any
            has_meds = False
            for med_form in formset:
                if med_form.cleaned_data and med_form.cleaned_data.get('medication') and not med_form.cleaned_data.get('DELETE'):
                    has_meds = True
                    break
            
            if has_meds:
                # Create a new Prescription record
                prescription = Prescription.objects.create(
                    patient=admission.patient,
                    visit=admission.visit,
                    prescribed_by=request.user,
                    diagnosis=discharge.final_diagnosis,
                    notes=f"Take-home meds prescribed on discharge from {admission.bed.ward.name}"
                )
                
                # Save associated items
                formset.instance = prescription
                prescription_items = formset.save()
                
                # Create billing for the take-home medications
                if prescription_items:
                    invoice = get_or_create_invoice(visit=admission.visit, user=request.user)
                    
                    for item in prescription_items:
                        if item.medication.selling_price > 0:
                            InvoiceItem.objects.create(
                                invoice=invoice,
                                inventory_item=item.medication,
                                name=item.medication.name,
                                unit_price=item.medication.selling_price,
                                quantity=item.quantity
                            )
                    
                    prescription.invoice = invoice
                    prescription.save()
                    invoice.update_totals()

            # Update admission
            admission.status = 'Discharged'
            admission.discharged_at = now
            admission.discharged_by = request.user
            admission.save()

            # Close associated visit
            visit = admission.visit
            visit.is_active = False
            visit.save()
            
            messages.success(request, f"Patient {admission.patient.full_name} has been discharged and take-home medications recorded.")
            return redirect('inpatient:discharge_summary', pk=discharge.pk)
    else:
        # Pre-fill provisional diagnosis from admission
        form = InpatientDischargeForm(initial={
            'provisional_diagnosis': admission.provisional_diagnosis
        })
        formset = PrescriptionItemFormSet(prefix='meds')

    # Prepare medication metadata for JS calculation (reusing logic from home/views.py)
    from inventory.models import InventoryItem, InventoryCategory
    import json
    
    pharma_category = InventoryCategory.objects.filter(name__icontains='Pharmaceutical').first()
    if pharma_category:
        medications = InventoryItem.objects.filter(category=pharma_category)
    else:
        medications = InventoryItem.objects.all()

    med_data = {}
    for med in medications:
        med_data[med.id] = {
            'price': str(med.selling_price),
            'is_dispensed_as_whole': med.is_dispensed_as_whole
        }
    med_json = json.dumps(med_data)

    return render(request, 'inpatient/discharge_patient.html', {
        'admission': admission,
        'form': form,
        'formset': formset,
        'med_json': med_json,
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
def discharge_summary(request, pk, template_name='inpatient/inpatient_discharge_summary.html'):
    discharge = get_object_or_404(InpatientDischarge, pk=pk)
    admission = discharge.admission
    
    # Fetch Lab results (Department: Lab)
    lab_results = LabResult.objects.filter(
        invoice__visit=admission.visit,
        service__department__name='Lab'
    ).select_related('service', 'performed_by')

    # Fetch Radiology results (Department: Imaging)
    radiology_results = LabResult.objects.filter(
        invoice__visit=admission.visit,
        service__department__name='Imaging'
    ).select_related('service', 'performed_by')

    # Fetch Take-home Medications (Prescription model)
    from home.models import Prescription
    prescriptions = Prescription.objects.filter(
        visit=admission.visit
    ).prefetch_related('items', 'items__medication')

    return render(request, template_name, {
        'discharge': discharge,
        'admission': admission,
        'lab_results': lab_results,
        'radiology_results': radiology_results,
        'prescriptions': prescriptions,
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
