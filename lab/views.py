from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db.models import Q, Count, Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.generic import ListView, DetailView
from django.urls import reverse_lazy
from .models import LabResult, LabReport
from .forms import LabResultForm, LabReportForm, LabResultUpdateForm, ServiceParameterForm
from accounts.models import Invoice, InvoiceItem, Service
from inventory.models import StockRecord, InventoryRequest
from home.models import PatientQue
@login_required
def radiology_dashboard(request):
    user_role = request.user.role
    
    # Determine department focus based on role
    dept_focus = None
    dashboard_title = "Diagnostics Dashboard"
    
    if user_role == 'Lab Technician':
        dept_focus = 'Lab'
        dashboard_title = "Laboratory Dashboard"
    elif user_role == 'Radiographer':
        dept_focus = 'Imaging'
        dashboard_title = "Radiology Dashboard"
    elif request.user.is_staff:
        dashboard_title = "Diagnostics Admin Dashboard"
        # Admin sees everything

    # Get search and Filter parameters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    service_type_filter = request.GET.get('service_type', dept_focus if dept_focus else '')
    payment_filter = request.GET.get('payment_status', '')

    # Get all InvoiceItems related to Diagnostics
    categories = ['Lab', 'Imaging', 'Procedure Room']
    if dept_focus:
        categories = [dept_focus]

    from django.db.models import Prefetch
    lab_items = InvoiceItem.objects.filter(
        service__department__name__in=categories,
        labresult__labreport__isnull=True
    ).select_related('invoice', 'invoice__patient', 'invoice__visit', 'service').prefetch_related(
        Prefetch('labresult_set', queryset=LabResult.objects.all(), to_attr='related_results')
    ).order_by('-created_at')
    
    # Get lab/radiology results
    lab_results = LabResult.objects.filter(service__department__name__in=categories).select_related('patient', 'service', 'requested_by').order_by('-requested_at')
    
    # Inventory Section - Filter by location name matching the focus
    stock_location = 'Lab' # Default
    if user_role == 'Radiographer':
        stock_location = 'Radiology'
    
    lab_stock = StockRecord.objects.filter(current_location__name__icontains=stock_location).select_related('item', 'item__category')
    lab_requests = InventoryRequest.objects.filter(Q(requested_by=request.user) | Q(location__name__icontains=stock_location)).select_related('item', 'requested_by').prefetch_related('acknowledgements').order_by('-requested_at').distinct()
    
    # Apply Filters
    if search_query:
        lab_items = lab_items.filter(
            Q(invoice__patient__first_name__icontains=search_query) |
            Q(invoice__patient__last_name__icontains=search_query) |
            Q(service__name__icontains=search_query)
        )
        lab_results = lab_results.filter(
            Q(patient__first_name__icontains=search_query) |
            Q(patient__last_name__icontains=search_query) |
            Q(service__name__icontains=search_query)
        )
    
    if status_filter:
        lab_results = lab_results.filter(status=status_filter)
    
    if service_type_filter and not dept_focus: # Only allow manual override if not locked by role
        lab_items = lab_items.filter(service__department__name=service_type_filter)
        lab_results = lab_results.filter(service__department__name=service_type_filter)
    
    if payment_filter:
        lab_items = lab_items.filter(invoice__status=payment_filter)

    # Statistics
    total_invoices_count = lab_items.count()
    paid_count = lab_items.filter(invoice__status='Paid').count()
    unpaid_count = lab_items.filter(invoice__status__in=['Pending', 'Partial', 'Draft']).count()
    in_progress_results = lab_results.filter(status='In Progress').count()
    
    context = {
        'dashboard_title': dashboard_title,
        'user_role': user_role,
        'lab_invoices': lab_items[:20],
        'lab_results': lab_results[:20],
        'lab_stock': lab_stock,
        'lab_requests': lab_requests[:20],
        'total_invoices': total_invoices_count,
        'paid_count': paid_count,
        'unpaid_count': unpaid_count,
        'in_progress_results': in_progress_results,
        'search_query': search_query,
        'status_filter': status_filter,
        'service_type_filter': service_type_filter,
        'payment_filter': payment_filter,
        'dept_focus': dept_focus,
        'service_types': [
            ('Lab', 'Laboratory'),
            ('Imaging', 'Imaging/Radiology'),
            ('Procedure Room', 'Procedure'),
            ('Other', 'Other'),
        ],
        'status_choices': LabResult.STATUS_CHOICES,
    }
    
    return render(request, 'lab/radiology_dashboard.html', context)

@login_required
def create_lab_result(request, invoice_id):
    # Depending on how the URL is passed, this might be an Invoice ID or InvoiceItem ID
    # Assuming Invoice for now based on previous code, but typically we want specific Item
    # Let's assume we pass the InvoiceItem ID for granularity, but if the URL expects Invoice ID, we adapt.
    
    # If the previous URL passed Invoice ID, we might need to find the relevant item.
    # However, existing links likely pass what they thought was an invoice ID.
    # Let's try to fetch an InvoiceItem using the ID, if that fails, try Invoice.
    
    try:
        # Case 1: ID refers to an InvoiceItem (Single test) - Preferred
        invoice_item = InvoiceItem.objects.get(id=invoice_id)
        invoice = invoice_item.invoice
        service = invoice_item.service
        
        # Restriction: OPD invoices must be fully paid before tests (skip for SHA)
        if invoice.visit and invoice.visit.visit_type == 'OUT-PATIENT' and invoice.visit.payment_method != 'SHA' and invoice.status != 'Paid':
            messages.error(request, "For OPD, invoice has to be fully paid before tests.")
            return redirect('lab:radiology_dashboard')
        
        # Check if a LabResult already exists for this item
        existing_result = LabResult.objects.filter(invoice_item=invoice_item).first()
        if existing_result:
            return redirect('lab:lab_result_detail', result_id=existing_result.pk)
            
    except InvoiceItem.DoesNotExist:
        # Case 2: ID refers to an Invoice (Group of tests) - Catch-all
        invoice = get_object_or_404(Invoice, id=invoice_id)
        service = None # User picks service from form
    
    if request.method == 'POST':
        form = LabResultForm(request.POST)
        if form.is_valid():
            lab_result = form.save(commit=False)
            lab_result.requested_by = request.user
            lab_result.invoice = invoice
            if 'invoice_item' in locals() and invoice_item:
                lab_result.invoice_item = invoice_item
            if service:
                lab_result.service = service
            lab_result.save()
            
            messages.success(request, f'Lab result created for {invoice.patient.full_name}')
            return redirect('lab:radiology_dashboard')
    else:
        initial_data = {
            'patient': invoice.patient,
            'invoice': invoice,
        }
        if service:
            initial_data['service'] = service
            
        form = LabResultForm(initial=initial_data)
    
    return render(request, 'lab/create_lab_result.html', {
        'form': form,
        'invoice': invoice,
        'title': f'Create Lab Result - {invoice.patient.full_name}'
    })

@login_required
def lab_result_detail(request, result_id):
    lab_result = get_object_or_404(LabResult, id=result_id)
    lab_report = None
    
    try:
        lab_report = lab_result.labreport
    except LabReport.DoesNotExist:
        pass
    
    is_read_only = request.user.role not in ['Lab Technician', 'Radiographer']
    
    # Restriction: OPD invoices must be fully paid before tests (skip for SHA)
    # Only enforce for those who can edit/perform tests
    is_sha = lab_result.invoice and lab_result.invoice.visit and lab_result.invoice.visit.payment_method == 'SHA'
    if not is_read_only and not is_sha and lab_result.invoice and lab_result.invoice.visit and lab_result.invoice.visit.visit_type == 'OUT-PATIENT':
        # Check specific item status first (Granular check)
        if lab_result.invoice_item:
            if not lab_result.invoice_item.is_settled:
                 messages.error(request, f"For OPD, the specific test '{lab_result.service.name}' must be paid before processing.")
                 return redirect('lab:radiology_dashboard')
        # Fallback to smart search if no specific item linked (Legacy/Group creation)
        else:
            # Try to find a paid item for this service on this invoice
            matching_paid_item = InvoiceItem.objects.filter(
                invoice=lab_result.invoice,
                service=lab_result.service
            ).first()
            
            is_item_paid = matching_paid_item.is_settled if matching_paid_item else False
            
            if not is_item_paid and lab_result.invoice.status != 'Paid':
                messages.error(request, "For OPD, invoice has to be fully paid before tests.")
                return redirect('lab:radiology_dashboard')
    
    if request.method == 'POST':
        if is_read_only:
             messages.error(request, "You do not have permission to edit results.")
             return redirect('lab:lab_result_detail', result_id=result_id)

        form = LabResultUpdateForm(instance=lab_result)
        report_form = LabReportForm(instance=lab_report)
        parameter_form = ServiceParameterForm()
        
        if 'update_result' in request.POST:
            form = LabResultUpdateForm(request.POST, instance=lab_result)
            if form.is_valid():
                updated_result = form.save(commit=False)
                if not updated_result.performed_by:
                    updated_result.performed_by = request.user
                if updated_result.status == 'Completed' and not lab_result.completed_at:
                    updated_result.completed_at = timezone.now()
                updated_result.save()
                messages.success(request, 'Lab result updated successfully')
                return redirect('lab:lab_result_detail', result_id=result_id)
            else:
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f"Update Form Error ({field}): {error}")
        
        elif 'create_report' in request.POST:
            report_form = LabReportForm(request.POST, request.FILES, instance=lab_report)
            if report_form.is_valid():
                lab_report = report_form.save(commit=False)
                lab_report.lab_result = lab_result
                lab_report.created_by = request.user
                lab_report.save()

                # Logic to move patient back to Doctor's queue as REVIEW
                if lab_result.invoice and lab_result.invoice.visit:
                    visit = lab_result.invoice.visit
                    
                    # 1. Mark Lab entry as COMPLETED
                    lab_entries = PatientQue.objects.filter(
                        visit=visit,
                        sent_to__name__icontains='Lab',
                        status='PENDING'
                    )
                    
                    # Store where we should go back to
                    return_to_dept = None
                    if lab_entries.exists():
                        return_to_dept = lab_entries.first().qued_from
                    
                    lab_entries.update(status='COMPLETED')

                    # 2. Create/update Consultation entry as REVIEW
                    if not return_to_dept:
                        from home.models import Departments
                        return_to_dept = Departments.objects.filter(name__icontains='Consultation').first()

                    if return_to_dept:
                        # Ensure we don't create multiple PENDING consultation entries
                        PatientQue.objects.update_or_create(
                            visit=visit,
                            sent_to=return_to_dept,
                            status='PENDING',
                            defaults={'queue_type': 'REVIEW'}
                        )

                messages.success(request, 'Lab report processed successfully')
                return redirect('lab:lab_result_detail', result_id=result_id)
            else:
                for field, errors in report_form.errors.items():
                    for error in errors:
                        messages.error(request, f"Report Form Error ({field}): {error}")

        elif 'create_parameter' in request.POST:
            parameter_form = ServiceParameterForm(request.POST)
            if parameter_form.is_valid():
                parameter = parameter_form.save(commit=False)
                parameter.service = lab_result
                parameter.save()
                messages.success(request, 'Parameter added successfully')
                return redirect('lab:lab_result_detail', result_id=result_id)
            else:
                for field, errors in parameter_form.errors.items():
                   for error in errors:
                       messages.error(request, f"Parameter Form Error ({field}): {error}")
        

    else:
        initial_data = {}
        if not lab_result.performed_by:
            initial_data['performed_by'] = request.user
            
        form = LabResultUpdateForm(instance=lab_result, initial=initial_data)
        report_form = LabReportForm(instance=lab_report)
        parameter_form = ServiceParameterForm()
    
    # Get available consumables for the user's department
    from inventory.models import InventoryItem, DispensedItem
    from home.models import Departments, Visit
    from home.views import _get_normalized_history
    
    dept_focus = 'Imaging' if request.user.role == 'Radiographer' else 'Lab'
    
    # Get previously dispensed items for this visit/context
    visit = None
    if lab_result.invoice and lab_result.invoice.visit:
        visit = lab_result.invoice.visit
    else:
        # Fallback to latest active visit for this patient if not linked via invoice
        visit = Visit.objects.filter(patient=lab_result.patient, is_active=True).order_by('-visit_date').first()
        if not visit:
            # Absolute fallback to latest visit
            visit = Visit.objects.filter(patient=lab_result.patient).order_by('-visit_date').first()

    dispensed_items = _get_normalized_history(visit, lab_result.patient) if visit else []

    return render(request, 'lab/lab_result_detail.html', {
        'lab_result': lab_result,
        'lab_report': lab_report,
        'form': form,
        'report_form': report_form,
        'parameter_form': parameter_form,
        'title': f'Lab Result - {lab_result.patient.full_name}',
        'is_read_only': is_read_only,
        'dispensing_departments': Departments.objects.all().order_by('name'),
        'dispensed_items': dispensed_items,
        'visit': visit,
        'patient': lab_result.patient,
    })

class LabResultListView(LoginRequiredMixin, ListView):
    model = LabResult
    template_name = 'lab/lab_result_list.html'
    context_object_name = 'lab_results'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = LabResult.objects.all().select_related('patient', 'service', 'requested_by')
        
        search_query = self.request.GET.get('search')
        status_filter = self.request.GET.get('status')
        priority_filter = self.request.GET.get('priority')
        
        if search_query:
            queryset = queryset.filter(
                Q(patient__first_name__icontains=search_query) |
                Q(patient__last_name__icontains=search_query) |
                Q(service__name__icontains=search_query)
            )
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        if priority_filter:
            queryset = queryset.filter(priority=priority_filter)
        
        return queryset.order_by('-requested_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('search', '')
        context['status_filter'] = self.request.GET.get('status', '')
        context['priority_filter'] = self.request.GET.get('priority', '')
        context['status_choices'] = LabResult.STATUS_CHOICES
        context['priority_choices'] = LabResult.PRIORITY_CHOICES
        return context
