from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DetailView, DeleteView
from django.urls import reverse_lazy
from django.db.models import Q, Sum
from django.utils import timezone
from django.http import JsonResponse
from .models import Deceased, NextOfKin, MorgueAdmission, PerformedMortuaryService, MortuaryDischarge
from .forms import DeceasedForm, DeceasedAdmissionForm, NextOfKinForm, MorgueAdmissionForm, PerformedMortuaryServiceForm, MortuaryDischargeForm


class DeceasedListView(LoginRequiredMixin, ListView):
    """View for listing all deceased persons"""
    model = Deceased
    template_name = 'morgue/deceased_list.html'
    context_object_name = 'deceased_list'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = Deceased.objects.select_related('created_by').prefetch_related('admissions')
        search_query = self.request.GET.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(surname__icontains=search_query) |
                Q(other_names__icontains=search_query) |
                Q(tag__icontains=search_query) |
                Q(id_number__icontains=search_query)
            )
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_count'] = Deceased.objects.filter(is_released=False).count()
        context['released_count'] = Deceased.objects.filter(is_released=True).count()
        return context


class DeceasedDetailView(LoginRequiredMixin, DetailView):
    """View for displaying deceased person details"""
    model = Deceased
    template_name = 'morgue/deceased_detail_modern.html'
    context_object_name = 'deceased'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['next_of_kin'] = self.object.next_of_kin.all()
        context['admissions'] = self.object.admissions.all()
        context['performed_services'] = self.object.performed_services.all().select_related('service', 'performed_by')
        context['service_form'] = PerformedMortuaryServiceForm()
        
        # Invoice data
        from accounts.models import Invoice, InvoiceItem
        
        # Get invoices related to this deceased using the deceased ForeignKey
        invoices = Invoice.objects.filter(
            deceased=self.object
        ).prefetch_related('items').order_by('-created_at')
        
        # Calculate financial summary
        total_services_cost = sum(
            service.subtotal for service in context['performed_services']
        )
        
        total_invoiced = sum(invoice.total_amount for invoice in invoices)
        total_paid = sum(invoice.paid_amount for invoice in invoices)
        outstanding_balance = total_invoiced - total_paid
        
        # Get uninvoiced services
        # We need to track which specific PerformedMortuaryService records have been invoiced
        # We'll store the performed service IDs in the invoice notes
        invoiced_performed_service_ids = set()
        for invoice in invoices:
            # Extract performed service IDs from notes if they exist
            if invoice.notes:
                # Notes format: "Mortuary services for John Doe\nPerformed Service IDs: 1,2,3"
                for line in invoice.notes.split('\n'):
                    if line.startswith('Performed Service IDs:'):
                        ids_str = line.replace('Performed Service IDs:', '').strip()
                        if ids_str:
                            invoiced_performed_service_ids.update(
                                int(id_str) for id_str in ids_str.split(',') if id_str.strip()
                            )
        
        # Filter out performed services that have been invoiced
        uninvoiced_services = [
            service for service in context['performed_services'] 
            if service.id not in invoiced_performed_service_ids
        ]
        
        context['invoices'] = invoices
        context['total_services_cost'] = total_services_cost
        context['total_invoiced'] = total_invoiced
        context['outstanding_balance'] = outstanding_balance
        context['uninvoiced_services'] = uninvoiced_services
        
        return context


@login_required
def log_mortuary_service(request, deceased_pk):
    """Log a mortuary service for a deceased person via AJAX"""
    deceased = get_object_or_404(Deceased, pk=deceased_pk)
    if request.method == 'POST':
        form = PerformedMortuaryServiceForm(request.POST)
        if form.is_valid():
            service_record = form.save(commit=False)
            service_record.deceased = deceased
            service_record.performed_by = request.user
            service_record.save()
            
            # Automatically update invoice
            from accounts.models import Invoice, InvoiceItem
            
            # Get the existing invoice for this deceased (regardless of status)
            existing_invoice = Invoice.objects.filter(deceased=deceased).first()
            
            if existing_invoice:
                # Update existing invoice
                invoice = existing_invoice
                
                # Add new service to invoice items
                InvoiceItem.objects.create(
                    invoice=invoice,
                    service=service_record.service,
                    name=service_record.service.name,
                    quantity=service_record.quantity,
                    unit_price=service_record.service.price
                )
                
                # Update invoice totals
                invoice.update_totals()
                message = 'Service logged and invoice updated successfully.'
                
            else:
                # Create new invoice (only if none exists)
                invoice = Invoice.objects.create(
                    deceased=deceased,
                    created_by=request.user,
                    status='Draft',
                    notes=f"Auto-generated invoice for {deceased.full_name}\nPerformed Service IDs: {service_record.id}"
                )
                
                # Add service to invoice items
                InvoiceItem.objects.create(
                    invoice=invoice,
                    service=service_record.service,
                    name=service_record.service.name,
                    quantity=service_record.quantity,
                    unit_price=service_record.service.price
                )
                
                # Update invoice totals
                invoice.update_totals()
                message = 'Service logged and new invoice created successfully.'
            
            return JsonResponse({'success': True, 'message': message})
        return JsonResponse({'success': False, 'errors': form.errors.as_json()})
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})


@login_required
def create_deceased_invoice(request, deceased_pk):
    """Create or update invoice for mortuary services performed on deceased"""
    from accounts.models import Invoice, InvoiceItem
    
    deceased = get_object_or_404(Deceased, pk=deceased_pk)
    
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        service_ids = data.get('service_ids', [])
        
        if not service_ids:
            return JsonResponse({'success': False, 'message': 'No services selected'})
        
        # Get selected performed services
        selected_services = PerformedMortuaryService.objects.filter(
            id__in=service_ids,
            deceased=deceased
        ).select_related('service')
        
        if not selected_services.exists():
            return JsonResponse({'success': False, 'message': 'No valid services found'})
        
        # Check if an invoice already exists for this deceased
        existing_invoice = Invoice.objects.filter(
            deceased=deceased,
            status__in=['Draft', 'Pending', 'Partial']  # Don't update paid/cancelled invoices
        ).first()
        
        if existing_invoice:
            # Update existing invoice
            invoice = existing_invoice
            message_prefix = "Updated"
            
            # Extract existing performed service IDs from notes
            existing_ids = set()
            if invoice.notes:
                for line in invoice.notes.split('\n'):
                    if line.startswith('Performed Service IDs:'):
                        ids_str = line.replace('Performed Service IDs:', '').strip()
                        if ids_str:
                            existing_ids.update(int(id_str) for id_str in ids_str.split(',') if id_str.strip())
            
            # Add new performed service IDs
            new_ids = {s.id for s in selected_services}
            all_ids = existing_ids | new_ids
            
            # Update notes with all performed service IDs
            invoice.notes = f"Mortuary services for {deceased.full_name}\nPerformed Service IDs: {','.join(str(id) for id in sorted(all_ids))}"
            invoice.save()
        else:
            # Create new invoice
            performed_service_ids = ','.join(str(s.id) for s in selected_services)
            invoice = Invoice.objects.create(
                deceased=deceased,
                status='Pending',
                created_by=request.user,
                notes=f"Mortuary services for {deceased.full_name}\nPerformed Service IDs: {performed_service_ids}"
            )
            message_prefix = "Created"
        
        # Add invoice items for the new services
        for performed_service in selected_services:
            InvoiceItem.objects.create(
                invoice=invoice,
                service=performed_service.service,
                name=performed_service.service.name,
                quantity=performed_service.quantity,
                unit_price=performed_service.service.price
            )
        
        # Update totals
        invoice.update_totals()
        
        return JsonResponse({
            'success': True,
            'message': f'{message_prefix} invoice INV-{invoice.id} successfully',
            'invoice_id': invoice.id
        })
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})


class DeceasedCreateView(LoginRequiredMixin, CreateView):
    """View for creating a new deceased record"""
    model = Deceased
    form_class = DeceasedAdmissionForm
    template_name = 'morgue/deceased_form.html'
    success_url = reverse_lazy('morgue:deceased_list')
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Deceased record created successfully.')
        return super().form_valid(form)


class DeceasedUpdateView(LoginRequiredMixin, UpdateView):
    """View for updating deceased record"""
    model = Deceased
    form_class = DeceasedForm
    template_name = 'morgue/deceased_form.html'
    success_url = reverse_lazy('morgue:deceased_list')
    
    def form_valid(self, form):
        form.instance.updated_at = timezone.now()
        messages.success(self.request, 'Deceased record updated successfully.')
        return super().form_valid(form)


class DeceasedDeleteView(LoginRequiredMixin, DeleteView):
    """View for deleting deceased record"""
    model = Deceased
    template_name = 'morgue/deceased_confirm_delete.html'
    success_url = reverse_lazy('morgue:deceased_list')
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Deceased record deleted successfully.')
        return super().delete(request, *args, **kwargs)


class NextOfKinCreateView(LoginRequiredMixin, CreateView):
    """View for adding next of kin"""
    model = NextOfKin
    form_class = NextOfKinForm
    template_name = 'morgue/next_of_kin_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['deceased'] = get_object_or_404(Deceased, pk=self.kwargs['deceased_pk'])
        return context
    
    def form_valid(self, form):
        form.instance.deceased = get_object_or_404(Deceased, pk=self.kwargs['deceased_pk'])
        messages.success(self.request, 'Next of kin added successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse_lazy('morgue:deceased_detail', kwargs={'pk': self.kwargs['deceased_pk']})


@login_required
def morgue_dashboard(request):
    """Morgue dashboard view"""
    total_deceased = Deceased.objects.filter(is_released=False).count()
    released_today = Deceased.objects.filter(
        is_released=True,
        release_date__date=timezone.now().date()
    ).count()
    admitted_today = Deceased.objects.filter(
        created_at__date=timezone.now().date()
    ).count()
    
    # Storage occupancy
    chamber_occupancy = {}
    for chamber_choice in Deceased.STORAGE_CHAMBER_CHOICES:
        chamber_key = chamber_choice[0]
        chamber_name = chamber_choice[1]
        count = Deceased.objects.filter(
            storage_chamber=chamber_key,
            is_released=False
        ).count()
        chamber_occupancy[chamber_name] = count
    
    # Recent admissions
    recent_admissions = Deceased.objects.filter(
        is_released=False
    ).select_related('created_by').order_by('-created_at')[:5]
    
    context = {
        'total_deceased': total_deceased,
        'released_today': released_today,
        'admitted_today': admitted_today,
        'chamber_occupancy': chamber_occupancy,
        'recent_admissions': recent_admissions,
    }
    
    return render(request, 'morgue/dashboard.html', context)


@login_required
def release_deceased(request, pk):
    """Process formal discharge of deceased from morgue"""
    deceased = get_object_or_404(Deceased, pk=pk)
    
    # Check if already released
    if deceased.is_released:
        messages.warning(request, f"{deceased.full_name} has already been released.")
        return redirect('morgue:deceased_detail', pk=pk)
    
    # Calculate costs
    performed_services = deceased.performed_services.all().select_related('service')
    total_charges = sum(record.subtotal for record in performed_services)
    
    # Check for uninvoiced services - simpler logic
    from accounts.models import InvoiceItem
    
    # Get all invoice items for this deceased
    invoice_items = InvoiceItem.objects.filter(invoice__deceased=deceased)
    
    # Count total performed services and total invoiced quantities by service type
    performed_service_counts = {}
    for service in performed_services:
        service_name = service.service.name
        performed_service_counts[service_name] = performed_service_counts.get(service_name, 0) + service.quantity
    
    invoiced_service_counts = {}
    for item in invoice_items:
        if item.service:
            service_name = item.service.name
            invoiced_service_counts[service_name] = invoiced_service_counts.get(service_name, 0) + item.quantity
    
    # Find services with more performed than invoiced quantities
    uninvoiced_services_list = []
    for service in performed_services:
        service_name = service.service.name
        performed_qty = performed_service_counts.get(service_name, 0)
        invoiced_qty = invoiced_service_counts.get(service_name, 0)
        
        if performed_qty > invoiced_qty:
            # This service type has uninvoiced quantities
            remaining_qty = performed_qty - invoiced_qty
            if remaining_qty > 0:
                uninvoiced_services_list.append({
                    'service': service,
                    'name': service_name,
                    'quantity': remaining_qty,
                    'subtotal': service.service.price * remaining_qty
                })
    
    has_uninvoiced_services = len(uninvoiced_services_list) > 0
    uninvoiced_total = sum(item['subtotal'] for item in uninvoiced_services_list)
    
    # Check invoice payment status
    invoices = deceased.invoices.all()
    total_invoiced = invoices.aggregate(total=Sum('total_amount'))['total'] or 0
    total_paid = invoices.aggregate(paid=Sum('paid_amount'))['paid'] or 0
    outstanding_balance = total_invoiced - total_paid
    
    # Check if there are any unpaid invoices
    has_unpaid_invoices = invoices.filter(status__in=['Draft', 'Pending', 'Partial']).exists()
    fully_paid = all(invoice.status == 'Paid' for invoice in invoices) if invoices.exists() else total_charges == 0
    
    if request.method == 'POST':
        # Additional validation: check for uninvoiced services
        if has_uninvoiced_services:
            messages.error(request, 
                f'Cannot release {deceased.full_name}. There are services that have not been invoiced. '
                f'Please ensure all services are properly invoiced before proceeding with release.'
            )
            return render(request, 'morgue/release_deceased.html', {
                'deceased': deceased,
                'form': MortuaryDischargeForm(request.POST),
                'performed_services': performed_services,
                'uninvoiced_services': uninvoiced_services_list,
                'uninvoiced_total': uninvoiced_total,
                'total_charges': total_charges,
                'invoices': invoices,
                'total_invoiced': total_invoiced,
                'total_paid': total_paid,
                'outstanding_balance': outstanding_balance,
                'has_unpaid_invoices': has_unpaid_invoices,
                'fully_paid': fully_paid,
                'has_uninvoiced_services': has_uninvoiced_services,
                'payment_block': True
            })
        
        # Additional validation: check if fully paid before allowing release
        if has_unpaid_invoices and outstanding_balance > 0:
            messages.error(request, 
                f'Cannot release {deceased.full_name}. Outstanding balance of ${outstanding_balance:.2f} must be paid first. '
                f'Please ensure all invoices are fully paid before proceeding with release.'
            )
            return render(request, 'morgue/release_deceased.html', {
                'deceased': deceased,
                'form': MortuaryDischargeForm(request.POST),
                'performed_services': performed_services,
                'uninvoiced_services': uninvoiced_services_list,
                'uninvoiced_total': uninvoiced_total,
                'total_charges': total_charges,
                'invoices': invoices,
                'total_invoiced': total_invoiced,
                'total_paid': total_paid,
                'outstanding_balance': outstanding_balance,
                'has_unpaid_invoices': has_unpaid_invoices,
                'fully_paid': fully_paid,
                'has_uninvoiced_services': has_uninvoiced_services,
                'payment_block': True
            })
        
        form = MortuaryDischargeForm(request.POST)
        if form.is_valid():
            discharge = form.save(commit=False)
            discharge.deceased = deceased
            discharge.admission = deceased.admissions.filter(status='ADMITTED').first()
            discharge.total_bill_snapshot = total_charges
            discharge.authorized_by = request.user
            discharge.save()
            
            # Update deceased record
            deceased.is_released = True
            deceased.release_date = timezone.now()
            deceased.save()
            
            # Update admission record
            if discharge.admission:
                discharge.admission.status = 'RELEASED'
                discharge.admission.release_date = timezone.now()
                discharge.admission.released_to = discharge.released_to
                discharge.admission.save()
            
            messages.success(request, f'{deceased.full_name} has been formally discharged.')
            return redirect('morgue:discharge_summary', pk=discharge.pk)
    else:
        form = MortuaryDischargeForm(initial={'released_to': deceased.next_of_kin.filter(is_primary=True).first().name if deceased.next_of_kin.filter(is_primary=True).exists() else ''})
    
    return render(request, 'morgue/release_deceased.html', {
        'deceased': deceased,
        'form': form,
        'performed_services': performed_services,
        'uninvoiced_services': uninvoiced_services_list,
        'uninvoiced_total': uninvoiced_total,
        'total_charges': total_charges,
        'invoices': invoices,
        'total_invoiced': total_invoiced,
        'total_paid': total_paid,
        'outstanding_balance': outstanding_balance,
        'has_unpaid_invoices': has_unpaid_invoices,
        'fully_paid': fully_paid,
        'has_uninvoiced_services': has_uninvoiced_services
    })

@login_required
def discharge_summary(request, pk):
    """View final discharge summary and invoice details"""
    discharge = get_object_or_404(MortuaryDischarge, pk=pk)
    performed_services = PerformedMortuaryService.objects.filter(
        deceased=discharge.deceased,
        date_performed__lte=discharge.discharge_date
    ).select_related('service')
    
    return render(request, 'morgue/discharge_summary.html', {
        'discharge': discharge,
        'services': performed_services,
        'title': f'Discharge Summary: {discharge.deceased.full_name}'
    })


def generate_admission_number():
    """Generate unique admission number"""
    prefix = "ADM"
    date_str = timezone.now().strftime("%Y%m%d")
    last_admission = MorgueAdmission.objects.filter(
        admission_number__startswith=f"{prefix}{date_str}"
    ).order_by('-admission_number').first()
    
    if last_admission:
        last_number = int(last_admission.admission_number[-4:])
        new_number = last_number + 1
    else:
        new_number = 1
    
    return f"{prefix}{date_str}{new_number:04d}"


@login_required
def create_admission(request, deceased_pk):
    """Create admission record for deceased"""
    deceased = get_object_or_404(Deceased, pk=deceased_pk)
    
    # Check if admission already exists
    existing_admission = MorgueAdmission.objects.filter(
        deceased=deceased,
        status='ADMITTED'
    ).first()
    
    if existing_admission:
        messages.warning(request, 'Admission record already exists for this deceased.')
        return redirect('morgue:deceased_detail', pk=deceased_pk)
    
    # Create new admission
    admission = MorgueAdmission.objects.create(
        deceased=deceased,
        admission_number=generate_admission_number(),
        admission_datetime=timezone.now(),
        created_by=request.user
    )
    
    messages.success(request, f'Admission record {admission.admission_number} created successfully.')
    return redirect('morgue:deceased_detail', pk=deceased_pk)
