from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.http import HttpResponseForbidden
from .models import InventoryItem, InventoryCategory, Supplier, StockRecord, InventoryRequest, StockAdjustment
from .forms import InventoryItemForm, InventoryCategoryForm, SupplierForm, StockRecordForm, InventoryRequestForm, MedicationForm, ConsumableDetailForm, GeneralUsageForm
from home.models import Departments, Patient, Visit
from accounts.utils import get_or_create_invoice

from django.db.models import Sum, Count, Q, Case, When, Value, IntegerField
from django.db import transaction
from django.utils import timezone

@login_required
def item_list(request):
    # Start with all items, annotate with total stock
    items = InventoryItem.objects.annotate(
        total_stock=Sum('stock_records__quantity')
    ).select_related('category').order_by('name')
    
    # Get filter parameters from GET request
    category_filter = request.GET.get('category', '')
    name_search = request.GET.get('name', '')
    stock_less_than = request.GET.get('stock_less_than', '')
    price_above = request.GET.get('price_above', '')
    
    # Apply filters
    if category_filter:
        items = items.filter(category_id=category_filter)
    
    if name_search:
        items = items.filter(name__icontains=name_search)
    
    if stock_less_than:
        try:
            stock_limit = int(stock_less_than)
            items = items.filter(total_stock__lt=stock_limit)
        except ValueError:
            pass  # Ignore invalid input
    
    if price_above:
        try:
            price_limit = float(price_above)
            items = items.filter(selling_price__gte=price_limit)
        except ValueError:
            pass  # Ignore invalid input
    
    # Get all categories for filter dropdown
    categories = InventoryCategory.objects.all().order_by('name')
    
    context = {
        'items': items,
        'categories': categories,
        'current_filters': {
            'category': category_filter,
            'name': name_search,
            'stock_less_than': stock_less_than,
            'price_above': price_above,
        },
        'inventory_requests': InventoryRequest.objects.all().order_by('-requested_at')
    }
    
    return render(request, 'inventory/item_list.html', context)
@login_required
@require_POST
def delete_item(request, item_id):
    item = get_object_or_404(InventoryItem, id=item_id)
    item_name = item.name
    item.delete()
    messages.success(request, f'Item "{item_name}" deleted successfully.')
    return redirect('inventory:item_list')

@login_required
@require_POST
def update_item_details(request, item_id):
    item = get_object_or_404(InventoryItem, id=item_id)
    new_price = request.POST.get('new_price')
    is_dispensed_as_whole = request.POST.get('is_dispensed_as_whole') == 'true'
    
    try:
        new_price_val = float(new_price)
        if new_price_val < 0:
            raise ValueError("Price cannot be negative")
        
        item.selling_price = new_price_val
        item.is_dispensed_as_whole = is_dispensed_as_whole
        item.is_updated = True
        item.save()
        messages.success(request, f'Item "{item.name}" updated successfully.')
    except (ValueError, TypeError):
        messages.error(request, 'Invalid selling price provided.')
    
    return redirect('inventory:item_list')

@login_required
def add_item(request):
    if request.method == 'POST':
        item_form = InventoryItemForm(request.POST)
        med_form = MedicationForm(request.POST)
        con_form = ConsumableDetailForm(request.POST)
        
        if item_form.is_valid():
            # Get the category to determine what type of item this is
            category = item_form.cleaned_data.get('category')
            category_name = category.name.lower() if category else ''
            
            # Sub-model validation: Only check forms for the SELECTED category
            item = None
            if 'pharmaceutical' in category_name or 'medicine' in category_name:
                if med_form.is_valid():
                    item = item_form.save()
                    medication = med_form.save(commit=False)
                    medication.item = item
                    medication.save()
                else:
                    messages.error(request, 'Please fill in all required medication details.')
            elif 'consumable' in category_name:
                if con_form.is_valid():
                    item = item_form.save()
                    consumable = con_form.save(commit=False)
                    consumable.item = item
                    consumable.save()
                else:
                    messages.error(request, 'Please fill in all required consumable details.')
            else:
                # General Supply - no extra form needed
                item = item_form.save()

            if item:
                messages.success(request, f'Item "{item.name}" registered successfully.')
                return redirect('inventory:item_list')
    else:
        item_form = InventoryItemForm()
        med_form = MedicationForm()
        con_form = ConsumableDetailForm()
    
    return render(request, 'inventory/add_item.html', {
        'form': item_form,
        'med_form': med_form,
        'con_form': con_form,
        'title': 'Add New Inventory Item'
    })

@login_required
def add_stock(request, item_id):
    item = get_object_or_404(InventoryItem, id=item_id)
    if request.method == 'POST':
        form = StockRecordForm(request.POST)
        if form.is_valid():
            stock = form.save(commit=False)
            stock.item = item
            
            # Calculate purchase price per unit from total purchase price
            quantity = form.cleaned_data.get('quantity')
            total_purchase_price = form.cleaned_data.get('purchase_price')
            
            if quantity and total_purchase_price:
                # Store price per unit instead of total
                stock.purchase_price = total_purchase_price / quantity
            
            stock.save()
            
            # Check if user wants to update selling price
            new_selling_price = request.POST.get('new_selling_price')
            if new_selling_price:
                try:
                    new_price = float(new_selling_price)
                    old_price = item.selling_price
                    item.selling_price = new_price
                    item.save()
                    messages.success(
                        request,
                        f'Stock for "{item.name}" added successfully. '
                        f'Selling price updated from KES {old_price} to KES {new_price}.'
                    )
                except (ValueError, TypeError):
                    messages.warning(request, 'Invalid selling price provided. Stock added but price not updated.')
            else:
                messages.success(request, f'Stock for "{item.name}" added successfully.')
            
            return redirect('inventory:item_list')
    else:
        form = StockRecordForm()
    
    return render(request, 'inventory/add_stock.html', {
        'form': form,
        'item': item,
        'title': f'Add Stock: {item.name}'
    })

@login_required
def create_request(request):
    if request.method == 'POST':
        form = InventoryRequestForm(request.POST)
        if form.is_valid():
            inventory_request = form.save(commit=False)
            inventory_request.requested_by = request.user
            inventory_request.save()
            messages.success(request, f'Inventory request for "{inventory_request.item.name}" submitted successfully.')
            return redirect('inventory:create_request')
    else:
        form = InventoryRequestForm()
    
    return render(request, 'inventory/create_request.html', {
        'form': form,
        'title': 'Create Inventory Request',
        'inventory_items': InventoryItem.objects.all().order_by('name')
    })

@login_required
def request_list(request):
    # Separate requests by status
    pending_requests = InventoryRequest.objects.filter(
        status='Pending'
    ).select_related('item', 'requested_by', 'location', 'requested_from').order_by('-requested_at')
    
    processed_requests = InventoryRequest.objects.filter(
        status__in=['Approved', 'Rejected']
    ).select_related('item', 'requested_by', 'location', 'requested_from').order_by('-requested_at')
    
    return render(request, 'inventory/request_list.html', {
        'pending_requests': pending_requests,
        'processed_requests': processed_requests
    })

@login_required
def update_request_status(request, request_id):
    if request.method == 'POST':
        inventory_request = get_object_or_404(InventoryRequest, pk=request_id)
        action = request.POST.get('action')
        
        if action == 'approve':
            try:
                adjusted_qty = int(request.POST.get('adjusted_quantity', inventory_request.quantity))
                
                # Retrieve Source Department (Requested From or default to Main Store)
                source_dept = inventory_request.requested_from
                if not source_dept:
                    try:
                        source_dept = Departments.objects.get(name='Main Store')
                    except Departments.DoesNotExist:
                        messages.error(request, 'Default source department (Main Store) not found.')
                        return redirect('inventory:request_list')

                # Check if enough stock in Source Department
                total_stock = StockRecord.objects.filter(
                    item=inventory_request.item, 
                    current_location=source_dept
                ).aggregate(Sum('quantity'))['quantity__sum'] or 0
                
                if total_stock < adjusted_qty:
                    messages.error(request, f'Insufficient stock in {source_dept.name}. Available: {total_stock}')
                    return redirect('inventory:request_list')

                # Proceed with Transfer
                remaining_qty = adjusted_qty
                # Get batches from Source Department (FIFO)
                source_records = StockRecord.objects.filter(
                    item=inventory_request.item, 
                    current_location=source_dept, 
                    quantity__gt=0
                ).order_by('expiry_date')

                for record in source_records:
                    if remaining_qty <= 0:
                        break
                    
                    qty_to_take = min(record.quantity, remaining_qty)
                    
                    # Deduct from source
                    record.quantity -= qty_to_take
                    record.save()
                    
                    # Add to destination
                    dest_record, created = StockRecord.objects.get_or_create(
                        item=inventory_request.item,
                        current_location=inventory_request.location,
                        batch_number=record.batch_number,
                        defaults={
                            'quantity': 0,
                            'expiry_date': record.expiry_date,
                            'supplier': record.supplier,
                            'purchase_price': record.purchase_price
                        }
                    )
                    dest_record.quantity += qty_to_take
                    dest_record.save()
                    
                    # Log Adjustments
                    StockAdjustment.objects.create(
                        item=inventory_request.item,
                        quantity=-qty_to_take,
                        adjustment_type='Transfer Out',
                        reason=f'Approved Request to {inventory_request.location.name}',
                        adjusted_by=request.user,
                        adjusted_from=source_dept
                    )
                    StockAdjustment.objects.create(
                        item=inventory_request.item,
                        quantity=qty_to_take,
                        adjustment_type='Transfer In',
                        reason=f'Approved Request from {source_dept.name}',
                        adjusted_by=request.user,
                        adjusted_from=inventory_request.location
                    )

                    remaining_qty -= qty_to_take

                inventory_request.adjusted_quantity = adjusted_qty
                inventory_request.status = 'Approved'
                messages.success(request, f'Request approved. {adjusted_qty} units transferred to {inventory_request.location.name} from {source_dept.name}.')
            except ValueError:
                messages.error(request, 'Invalid quantity provided.')
                return redirect('inventory:request_list')
        elif action == 'reject':
            item_name = inventory_request.item.name
            inventory_request.delete()
            messages.info(request, f'Request for {item_name} rejected.')
            return redirect('inventory:request_list')
        
        inventory_request.save()
        return redirect('inventory:request_list')
    
    return redirect('inventory:request_list')

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from .models import DispensedItem
from home.models import Patient, Visit

@login_required
def search_inventory(request):
    """
    JSON API for searching inventory items.
    """
    query = request.GET.get('q', '')
    department_id = request.GET.get('department_id')
    exclude_pharmaceuticals = request.GET.get('exclude_pharmaceuticals') == 'true'
    
    if len(query) < 2:
        return JsonResponse({'results': []})
        
    items = InventoryItem.objects.filter(name__icontains=query)
    
    if exclude_pharmaceuticals:
        # Items that don't have a linked Medication record
        items = items.filter(medication__isnull=True)
        
    items = items.select_related('category').order_by('name')[:20]
    
    results = []
    for item in items:
        # Calculate stock for this item in the specific department
        stock = 0
        if department_id:
            stock = StockRecord.objects.filter(
                item=item, 
                current_location_id=department_id
            ).aggregate(total=Sum('quantity'))['total'] or 0
            
        results.append({
            'id': item.id,
            'text': f"{item.name} ({item.dispensing_unit})",
            'name': item.name,
            'category': item.category.name if item.category else 'General',
            'stock': stock,
            'stock_quantity': stock, # Added for compatibility
            'selling_price': str(item.selling_price) if item.selling_price else '0' # Added for compatibility
        })
    return JsonResponse({'results': results})

@login_required
@require_POST
def dispense_item(request):
    """
    Handle consumable billing via AJAX.
    Creates an InvoiceItem for the consumable — NO stock deduction.
    Stock is deducted later by the pharmacist via the Dispense All action.
    """
    from accounts.models import Invoice, InvoiceItem

    item_id = request.POST.get('item_id')
    patient_id = request.POST.get('patient_id')
    visit_id = request.POST.get('visit_id')
    department_id = request.POST.get('department_id')
    quantity_str = request.POST.get('quantity', '0')
    instructions = request.POST.get('instructions', '').strip()
    procedure_item_id = request.POST.get('procedure_item_id')

    try:
        quantity = int(quantity_str)
        if quantity <= 0:
            return JsonResponse({'status': 'error', 'message': 'Invalid quantity'}, status=400)

        with transaction.atomic():
            item = get_object_or_404(InventoryItem, id=item_id)
            patient = get_object_or_404(Patient, id=patient_id)
            visit = Visit.objects.filter(id=visit_id).first() if visit_id else None
            
            # Resolve department
            department = None
            if department_id:
                department = Departments.objects.filter(id=department_id).first()

            if not visit:
                return JsonResponse({'status': 'error', 'message': 'Visit not identified'}, status=400)

            # Optional linkage for procedure pages: block dispensing if selected procedure is already done.
            if procedure_item_id:
                from accounts.models import InvoiceItem
                from home.models import ProcedureCompletion
                procedure_item = get_object_or_404(
                    InvoiceItem.objects.select_related('invoice__visit', 'service__department'),
                    id=procedure_item_id,
                    invoice__visit=visit,
                    service__isnull=False,
                    service__department__name='Procedure Room',
                )
                if ProcedureCompletion.objects.filter(invoice_item=procedure_item).exists():
                    return JsonResponse({
                        'status': 'error',
                        'message': f"Cannot dispense items. Procedure '{procedure_item.name}' is already marked as done."
                    }, status=400)

            # Block if visit is not active (optional, but keep for data integrity)
            if not visit.is_active:
                 # messages.warning(request, "Note: Dispensing to a closed visit.")
                 pass

            # Optional: Warning if not the latest visit, but DO NOT block.
            # Clinicians/Technicians might be finishing up a specific visit's records.
            latest_visit = Visit.objects.filter(patient=patient).order_by('-visit_date').first()

            from .models import DispensedItem, StockRecord
            from inpatient.models import Admission, InpatientConsumable
            active_admission = Admission.objects.filter(visit=visit, status='Admitted').first()

            # Record Physical Dispensing (Inventory Stock Movement)
            # ONLY for departments other than Pharmacy/Mini Pharmacy
            # because those two are handled at pickup.
            # Strict check: only the main 'Pharmacy' handles deferred dispensing/billing.
            # All other departments (including Mini Pharmacy) bill and adjust stock immediately.
            is_pharmacy = department and department.name == 'Pharmacy'
            
            
            if not is_pharmacy:
                # Check absolute stock before recording anything
                if department:
                    available_stock = StockRecord.objects.filter(
                        item=item, 
                        current_location=department
                    ).aggregate(total=Sum('quantity'))['total'] or 0
                    
                    if available_stock < quantity:
                        return JsonResponse({
                            'status': 'error', 
                            'message': f'Insufficient stock in {department.name}. Available: {available_stock}'
                        }, status=400)
                    
                    # Deduct Stock immediately for non-pharmacy departments (FEFO/FIFO)
                    remaining_to_deduct = quantity
                    batches = StockRecord.objects.filter(
                        item=item, 
                        current_location=department, 
                        quantity__gt=0
                    ).order_by('expiry_date', 'received_date')
                    
                    for batch in batches:
                        if remaining_to_deduct <= 0:
                            break
                        
                        deduction = min(batch.quantity, remaining_to_deduct)
                        batch.quantity -= deduction
                        batch.save()
                        remaining_to_deduct -= deduction

                    # Create audit trail for immediate stock reduction (Non-Pharmacy)
                    StockAdjustment.objects.create(
                        item=item,
                        quantity=-quantity,
                        adjustment_type='Usage',
                        reason=f'Dispensed to Patient: {patient.full_name} (Visit: {visit.id if visit else "N/A"})',
                        adjusted_by=request.user,
                        adjusted_from=department
                    )

                # 1. Physical Stock Movement (Audit Trail)
                DispensedItem.objects.create(
                    item=item,
                    patient=patient,
                    visit=visit,
                    quantity=quantity,
                    department=department,
                    dispensed_by=request.user
                )

                if active_admission:
                    # Satisfy existing pending requests for this item first
                    remaining_to_fulfill = quantity
                    pending_requests = InpatientConsumable.objects.filter(
                        admission=active_admission,
                        item=item,
                        is_dispensed=False
                    ).order_by('prescribed_at')

                    for req in pending_requests:
                        if remaining_to_fulfill <= 0:
                            break
                        
                        can_fulfill = req.total_quantity - req.quantity_dispensed
                        fill_qty = min(can_fulfill, remaining_to_fulfill)
                        
                        req.quantity_dispensed += fill_qty
                        if req.quantity_dispensed >= req.total_quantity:
                            req.is_dispensed = True
                            req.dispensed_at = timezone.now()
                            req.dispensed_by = request.user
                        req.save()
                        remaining_to_fulfill -= fill_qty

                    # If there's surplus quantity (not satisfying a specific request), 
                    # create a new "Immediate" clinical record
                    if remaining_to_fulfill > 0:
                        InpatientConsumable.objects.create(
                            admission=active_admission,
                            item=item,
                            quantity=remaining_to_fulfill,
                            total_quantity=remaining_to_fulfill,
                            quantity_dispensed=remaining_to_fulfill if not is_pharmacy else 0,
                            instructions=instructions or "Direct dispense",
                            prescribed_by=request.user,
                            request_location=department if is_pharmacy else None,
                            is_dispensed=not is_pharmacy,
                            dispensed_at=timezone.now() if not is_pharmacy else None,
                            dispensed_by=request.user if not is_pharmacy else None
                        )
                    
                    # 2. Explicitly Bill if NOT pharmacy
                    if not is_pharmacy:
                        invoice = get_or_create_invoice(visit=visit, user=request.user)
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            inventory_item=item,
                            name=f"{item.name} (IPD Dispense)",
                            quantity=quantity,
                            unit_price=item.selling_price,
                            created_by=request.user
                        )

                    status_msg = "dispensed and recorded" if not is_pharmacy else "requested"
                    return JsonResponse({
                        'status': 'success',
                        'message': f'{item.name} x{quantity} {status_msg} successfully.'
                    })

            # OPD Flow: Get or Create Consolidate Visit Invoice
            invoice = get_or_create_invoice(visit=visit, user=request.user)

            # Create InvoiceItem for the consumable (Billing)
            item_name = f"{item.name} (Consumable)"
            if department:
                item_name = f"{item.name} (from {department.name})"

            InvoiceItem.objects.create(
                invoice=invoice,
                inventory_item=item,
                name=item_name,
                quantity=quantity,
                unit_price=item.selling_price,
                created_by=request.user
            )

            return JsonResponse({
                'status': 'success',
                'message': f'{item.name} x{quantity} dispensed and added to invoice INV-{invoice.id}'
            })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
@login_required
def procurement_dashboard(request):
    """Dashboard for managing Stock Intake (GRN)"""
    from datetime import datetime
    
    # Imports inside function to avoid circular imports if any
    from accounts.models import InventoryPurchase, SupplierInvoice
    from .forms import InventoryPurchaseForm
    
    # Get date filters
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    purchases = InventoryPurchase.objects.all().select_related('supplier', 'invoice_ref', 'recorded_by').order_by('-date')
    
    if from_date:
        purchases = purchases.filter(date__gte=from_date)
    if to_date:
        purchases = purchases.filter(date__lte=to_date)
        
    # Calculations for stats
    from django.db.models import Sum
    total_value = purchases.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_suppliers = purchases.values('supplier').distinct().count()
    
    context = {
        'purchases': purchases,
        'from_date': from_date,
        'to_date': to_date,
        'purchase_form': InventoryPurchaseForm(),
        'total_value': total_value,
        'total_suppliers': total_suppliers,
    }
    return render(request, 'inventory/procurement_dashboard.html', context)

@login_required
def add_inventory_purchase(request):
    from .forms import InventoryPurchaseForm
    from accounts.models import SupplierInvoice
    if request.method == 'POST':
        form = InventoryPurchaseForm(request.POST)
        if form.is_valid():
            purchase = form.save(commit=False)
            purchase.recorded_by = request.user

            # Auto-create a SupplierInvoice for this GRN
            invoice_number = form.cleaned_data.get('invoice_number', '').strip()
            invoice = SupplierInvoice.objects.create(
                supplier=purchase.supplier,
                invoice_number=invoice_number,
                date=purchase.date,
                total_amount=purchase.total_amount,
                status='Pending',
                recorded_by=request.user,
            )
            purchase.invoice_ref = invoice
            purchase.save()

            messages.success(request, f"GRN Created: {purchase.supplier.name} on {purchase.date}. Invoice #{invoice_number} recorded. Now add items.")
            return redirect('inventory:add_grn_item', grn_id=purchase.id)
        else:
            messages.error(request, f"Error recording purchase: {form.errors}")
    return redirect('inventory:procurement_dashboard')

@login_required
def add_grn_item(request, grn_id):
    """View to add Stock Record items to a specific GRN (InventoryPurchase).
    Mirrors the add_stock view's full workflow: StockRecordForm with
    profit/loss calculator and selling price update option.
    """
    from accounts.models import InventoryPurchase
    from .forms import StockRecordForm
    
    purchase = get_object_or_404(InventoryPurchase, id=grn_id)
    
    if request.method == 'POST':
        form = StockRecordForm(request.POST)
        # Supplier comes from the GRN header, not the form
        form.fields['supplier'].required = False
        if form.is_valid():
            stock = form.save(commit=False)
            stock.purchase_ref = purchase
            # Override supplier with GRN supplier
            stock.supplier = purchase.supplier
            
            # Manually set item (not in StockRecordForm fields)
            item_id = request.POST.get('item')
            if item_id:
                stock.item = get_object_or_404(InventoryItem, id=item_id)
            
            # Calculate purchase price per unit from total purchase price
            quantity = form.cleaned_data.get('quantity')
            total_purchase_price = form.cleaned_data.get('purchase_price')
            
            if quantity and total_purchase_price:
                stock.purchase_price = total_purchase_price / quantity
            
            stock.save()
            
            # Check if user wants to update selling price
            new_selling_price = request.POST.get('new_selling_price')
            item = stock.item
            if new_selling_price:
                try:
                    new_price = float(new_selling_price)
                    old_price = item.selling_price
                    item.selling_price = new_price
                    item.save()
                    messages.success(
                        request,
                        f'Stock for "{item.name}" added to GRN. '
                        f'Selling price updated from KES {old_price} to KES {new_price}.'
                    )
                except (ValueError, TypeError):
                    messages.warning(request, 'Invalid selling price provided. Stock added but price not updated.')
            else:
                messages.success(request, f'Stock for "{item.name}" added to GRN successfully.')
            
            return redirect('inventory:add_grn_item', grn_id=purchase.id)
        else:
            messages.error(request, f"Error adding stock: {form.errors}")
    else:
        form = StockRecordForm()
        form.fields['supplier'].required = False
    
    # Get items already added to this GRN
    added_items = purchase.stock_records.all().select_related('item', 'item__category', 'current_location').order_by('item__name')
    
    # All items for the dropdown and JS profit calculator
    import json
    inventory_items = InventoryItem.objects.all().order_by('name')
    all_items_prices_json = json.dumps({
        str(item.id): float(item.selling_price) if item.selling_price else 0
        for item in inventory_items
    })
    
    context = {
        'purchase': purchase,
        'form': form,
        'added_items': added_items,
        'inventory_items': inventory_items,
        'all_items_prices_json': all_items_prices_json,
    }
    return render(request, 'inventory/add_grn_item.html', context)

@login_required
def inventory_distribution(request, item_id):
    """
    View to show and edit inventory item distribution and details.
    """
    item = get_object_or_404(InventoryItem, id=item_id)
    
    if request.method == 'POST':
        item_form = InventoryItemForm(request.POST, instance=item)
        
        # Determine which sub-form to use based on item's category or existing link
        med_form = None
        con_form = None
        
        category_name = item.category.name.lower() if item.category else ''
        
        if hasattr(item, 'medication'):
            med_form = MedicationForm(request.POST, instance=item.medication)
        elif 'pharmaceutical' in category_name or 'medicine' in category_name:
            med_form = MedicationForm(request.POST)
            
        if hasattr(item, 'consumable_detail'):
            con_form = ConsumableDetailForm(request.POST, instance=item.consumable_detail)
        elif 'consumable' in category_name:
            con_form = ConsumableDetailForm(request.POST)

        if item_form.is_valid():
            item_form.save()
            
            if med_form and med_form.is_valid():
                medication = med_form.save(commit=False)
                medication.item = item
                medication.save()
            
            if con_form and con_form.is_valid():
                consumable = con_form.save(commit=False)
                consumable.item = item
                consumable.save()
                
            messages.success(request, f'Item "{item.name}" updated successfully.')
            return redirect('inventory:inventory_distribution', item_id=item.id)

    # Prepare forms for GET request
    item_form = InventoryItemForm(instance=item)
    med_form = MedicationForm(instance=getattr(item, 'medication', None))
    con_form = ConsumableDetailForm(instance=getattr(item, 'consumable_detail', None))
    
    # Aggregate stock by location
    distribution = StockRecord.objects.filter(
        item=item, 
        quantity__gt=0
    ).values(
        'current_location__name', 
        'current_location__id'
    ).annotate(
        total_quantity=Sum('quantity'),
        batch_count=Count('id')
    ).order_by('-total_quantity')
    
    # Get total stock across all locations
    total_stock = sum(d['total_quantity'] for d in distribution)
    
    # Get recent adjustments for this item with filters
    adj_qs = StockAdjustment.objects.filter(item=item).select_related('adjusted_by', 'adjusted_from')
    
    # Get Filter Parameters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    user_id = request.GET.get('user')
    min_qty = request.GET.get('min_qty')
    max_qty = request.GET.get('max_qty')
    
    if date_from:
        adj_qs = adj_qs.filter(adjusted_at__date__gte=date_from)
    if date_to:
        adj_qs = adj_qs.filter(adjusted_at__date__lte=date_to)
    if user_id:
        adj_qs = adj_qs.filter(adjusted_by_id=user_id)
    if min_qty:
        adj_qs = adj_qs.filter(quantity__gte=min_qty)
    if max_qty:
        adj_qs = adj_qs.filter(quantity__lte=max_qty)
        
    recent_adjustments = adj_qs.order_by('-adjusted_at')[:30]
    
    # Get all users who have made adjustments for this item for the filter dropdown
    active_users = StockAdjustment.objects.filter(item=item).values_list('adjusted_by', flat=True).distinct()
    from django.contrib.auth import get_user_model
    User = get_user_model()
    users = User.objects.filter(id__in=active_users).order_by('first_name')
    
    context = {
        'item': item,
        'item_form': item_form,
        'med_form': med_form,
        'con_form': con_form,
        'distribution': distribution,
        'total_stock': total_stock,
        'recent_adjustments': recent_adjustments,
        'users': users,
        'filters': {
            'date_from': date_from,
            'date_to': date_to,
            'user': user_id,
            'min_qty': min_qty,
            'max_qty': max_qty,
        },
        'title': f'Distribution: {item.name}'
    }
    return render(request, 'inventory/inventory_distribution.html', context)

@login_required
def record_usage(request):
    """
    View to record general stock usage not linked to a patient.
    """
    # Permission Check: Nurse (includes Triage Nurse), Pharmacist, Admin
    user_role = getattr(request.user, 'role', None) or ('Admin' if request.user.is_superuser else None)
    if user_role not in ['Admin', 'Nurse', 'Pharmacist', 'Triage Nurse'] and not request.user.is_superuser:
         return HttpResponseForbidden("You do not have permission to access this page.")

    if request.method == 'POST':
        form = GeneralUsageForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                usage = form.save(commit=False)
                usage.adjusted_by = request.user
                usage.adjustment_type = 'Usage'
                
                # Use reason_type directly as it's now strictly internal and has no "Other"
                usage.reason = form.cleaned_data.get('reason_type')
                
                item = usage.item
                quantity = usage.quantity
                department = usage.adjusted_from
                
                # Deduct Stock (FEFO/FIFO)
                available_stock = StockRecord.objects.filter(
                    item=item, 
                    current_location=department
                ).aggregate(total=Sum('quantity'))['total'] or 0
                
                if available_stock < quantity:
                    messages.error(request, f'Insufficient stock in {department.name}. Available: {available_stock}')
                else:
                    remaining_to_deduct = quantity
                    batches = StockRecord.objects.filter(
                        item=item, 
                        current_location=department, 
                        quantity__gt=0
                    ).order_by('expiry_date', 'received_date')
                    
                    for batch in batches:
                        if remaining_to_deduct <= 0:
                            break
                        
                        deduction = min(batch.quantity, remaining_to_deduct)
                        batch.quantity -= deduction
                        batch.save()
                        remaining_to_deduct -= deduction
                    
                    # Set quantity to negative for the adjustment record
                    usage.quantity = -quantity
                    usage.save()
                    
                    messages.success(request, f'Recorded usage of {quantity} {item.dispensing_unit}(s) of {item.name}.')
                    return redirect('inventory:record_usage')
    else:
        form = GeneralUsageForm()
    
    # Get recent general usages (those that match the internal options in this page)
    internal_reasons = [c[0] for c in GeneralUsageForm.REASON_CHOICES]
    recent_usages = StockAdjustment.objects.filter(
        adjustment_type='Usage',
        reason__in=internal_reasons
    ).select_related('item', 'adjusted_by', 'adjusted_from').order_by('-adjusted_at')[:30]
    
    inventory_items = InventoryItem.objects.all().order_by('name')
    
    # Calculate stock by department for all items
    stock_records = StockRecord.objects.filter(quantity__gt=0).values(
        'item_id', 'current_location_id', 'current_location__name'
    ).annotate(total_quantity=Sum('quantity'))
    
    stock_by_department = {}
    for record in stock_records:
        dept_id = str(record['current_location_id'])
        if dept_id not in stock_by_department:
            stock_by_department[dept_id] = {
                'name': record['current_location__name'],
                'items': []
            }
        stock_by_department[dept_id]['items'].append({
            'item_id': record['item_id'],
            'total_quantity': record['total_quantity']
        })

    return render(request, 'inventory/record_usage.html', {
        'form': form,
        'recent_usages': recent_usages,
        'inventory_items': inventory_items,
        'stock_by_department': stock_by_department,
        'title': 'Record Stock Usage'
    })

def is_admin(user):
    return user.is_authenticated and (user.role == 'Admin')

@login_required
@user_passes_test(is_admin)
@require_POST
def reconcile_stock(request, item_id, location_id):
    """
    Adjust system stock count for an item in a specific department 
    to match the physical/actual count.
    """
    item = get_object_or_404(InventoryItem, id=item_id)
    location = get_object_or_404(Departments, id=location_id)
    actual_count_raw = request.POST.get('actual_count', '0')
    
    try:
        actual_count = int(actual_count_raw)
        if actual_count < 0:
            raise ValueError("Count cannot be negative.")
        
        # Get all active records for this item at this location
        records = StockRecord.objects.filter(item=item, current_location=location).order_by('expiry_date', 'received_date')
        current_total = records.aggregate(total=Sum('quantity'))['total'] or 0
        diff = actual_count - current_total
        
        if diff == 0:
            messages.info(request, f"System was already at {actual_count}. No adjustment made.")
            return redirect('inventory:inventory_distribution', item_id=item.id)

        with transaction.atomic():
            if diff < 0:
                # Reduce stock (Loss, etc.)
                to_reduce = abs(diff)
                for record in records:
                    if record.quantity >= to_reduce:
                        record.quantity -= to_reduce
                        record.save()
                        to_reduce = 0
                        break
                    else:
                        to_reduce -= record.quantity
                        record.quantity = 0
                        record.save()
            else:
                # Stock addition
                # Find the most recent record to add the surplus to, or create one if none exist
                target_record = records.last()
                if target_record:
                    target_record.quantity += diff
                    target_record.save()
                else:
                    StockRecord.objects.create(
                        item=item,
                        batch_number="RECONCILIATION",
                        quantity=diff,
                        current_location=location,
                        received_date=timezone.now().date()
                    )

            # Record in adjustment log
            StockAdjustment.objects.create(
                item=item,
                quantity=diff,
                adjustment_type='Correction',
                reason=f"Stock Reconciliation: Physical count was {actual_count}, system was {current_total}",
                adjusted_by=request.user,
                adjusted_from=location
            )
        
        messages.success(request, f"Reconciliation successful for {location.name}. New total: {actual_count}")
    except (ValueError, TypeError) as e:
        messages.error(request, f"Error: {str(e)}")
    
    return redirect('inventory:inventory_distribution', item_id=item.id)

def is_pharmacist_or_admin(user):
    return user.is_authenticated and (user.is_superuser or user.role in ['Pharmacist', 'Admin'])

@login_required
@user_passes_test(is_pharmacist_or_admin)
def transfer_stock(request):
    """
    View to handle stock transfers between departments.
    """
    from .forms import StockTransferForm

    if request.method == 'POST':
        form = StockTransferForm(request.POST)
        if form.is_valid():
            item = form.cleaned_data['item']
            source = form.cleaned_data['source_location']
            destination = form.cleaned_data['destination_location']
            quantity = form.cleaned_data['quantity']
            batch_query = form.cleaned_data.get('batch_number')

            # 1. Validate Stock Availability
            # If batch specified, check specific batch
            stock_filter = {
                'item': item,
                'current_location': source,
                'quantity__gt': 0
            }
            if batch_query:
                stock_filter['batch_number__icontains'] = batch_query

            available_stock = StockRecord.objects.filter(**stock_filter).aggregate(total=Sum('quantity'))['total'] or 0

            if available_stock < quantity:
                messages.error(request, f"Insufficient stock in {source.name}. Requested: {quantity}, Available: {available_stock}")
            else:
                try:
                    with transaction.atomic():
                        # 2. Get Source Records (FEFO)
                        source_records = StockRecord.objects.filter(**stock_filter).order_by('expiry_date').select_for_update()
                        
                        remaining_qty = quantity
                        for record in source_records:
                            if remaining_qty <= 0:
                                break
                            
                            take = min(record.quantity, remaining_qty)
                            
                            # Deduct from source
                            record.quantity -= take
                            record.save()
                            
                            # Add to destination
                            dest_record, created = StockRecord.objects.get_or_create(
                                item=item,
                                current_location=destination,
                                batch_number=record.batch_number,
                                defaults={
                                    'quantity': 0,
                                    'expiry_date': record.expiry_date,
                                    'supplier': record.supplier,
                                    'purchase_price': record.purchase_price
                                }
                            )
                            # If existing record, lock it too? get_or_create doesn't select_for_update easily.
                            # Just update quantity.
                            dest_record.quantity += take
                            dest_record.save()
                            
                            # Log Adjustments
                            StockAdjustment.objects.create(
                                item=item,
                                quantity=-take,
                                adjustment_type='Usage', # Or maybe a new type 'Transfer Out'? usage implies consumption.
                                reason=f'Transfer to {destination.name}',
                                adjusted_by=request.user,
                                adjusted_from=source
                            )
                            StockAdjustment.objects.create(
                                item=item,
                                quantity=take,
                                adjustment_type='Addition', # 'Transfer In'
                                reason=f'Transfer from {source.name}',
                                adjusted_by=request.user,
                                adjusted_from=destination
                            )

                            remaining_qty -= take
                        
                        messages.success(request, f"Successfully transferred {quantity} units of {item.name} from {source.name} to {destination.name}.")
                        return redirect('inventory:transfer_stock')

                except Exception as e:
                    messages.error(request, f"Transfer failed: {str(e)}")

    else:
        form = StockTransferForm()

    # Get stock information for all items by department
    stock_by_department = {}
    departments = Departments.objects.all()
    
    for dept in departments:
        stock_info = StockRecord.objects.filter(
            current_location=dept,
            quantity__gt=0
        ).select_related('item', 'supplier').values(
            'item_id',
            'item__name',
            'quantity'
        ).annotate(
            total_quantity=Sum('quantity')
        ).order_by('item__name')
        
        stock_by_department[dept.id] = {
            'name': dept.name,
            'items': list(stock_info)
        }

    return render(request, 'inventory/transfer_stock.html', {
        'form': form, 
        'title': 'Stock Transfer',
        'inventory_items': InventoryItem.objects.all().order_by('name'),
        'stock_by_department': stock_by_department
    })

@login_required
def ipd_pharmacy_dashboard(request):
    """
    Dashboard for pharmacists to dispense items to inpatients.
    Shows pending partial fulfillments grouped by visit/patient.
    """
    from inpatient.models import MedicationChart, InpatientConsumable
    from home.models import Departments
    from django.db.models import F
    from collections import OrderedDict
    
    # Pharmacist, Nurse, and Admin can access this page.
    if request.user.role not in ['Pharmacist', 'Nurse', 'Admin'] and not request.user.is_superuser:
        return HttpResponseForbidden("Access denied.")

    # Identify and lock to the user's dispensing department.
    user_dept = None
    if request.user.role == 'Pharmacist':
        user_dept = Departments.objects.filter(name='Pharmacy').first()
    elif request.user.role == 'Nurse':
        user_dept = Departments.objects.filter(name='Mini Pharmacy').first()
    elif request.user.role == 'Admin' or request.user.is_superuser:
        user_dept = Departments.objects.filter(name='Pharmacy').first()
    
    # Search filter
    search_query = request.GET.get('q', '').strip()
    
    # Fetch pending meds (only for currently admitted patients)
    pending_meds = MedicationChart.objects.filter(
        quantity_dispensed__lt=F('total_quantity'),
        is_active=True,
        admission__status='Admitted'
    ).select_related('admission__patient', 'admission__visit', 'admission__bed__ward', 'item', 'request_location')
    
    # Fetch pending consumables (only for currently admitted patients)
    pending_consumables = InpatientConsumable.objects.filter(
        quantity_dispensed__lt=F('total_quantity'),
        admission__status='Admitted'
    ).select_related('admission__patient', 'admission__visit', 'admission__bed__ward', 'item', 'request_location')

    # Apply search filter — split into words so "John Doe" works
    if search_query:
        search_terms = search_query.split()
        med_filter = Q()
        for term in search_terms:
            med_filter &= (Q(admission__patient__first_name__icontains=term) | Q(admission__patient__last_name__icontains=term) | Q(admission__patient__id_number__icontains=term) | Q(admission__patient__phone__icontains=term) | Q(item__name__icontains=term))
        pending_meds = pending_meds.filter(med_filter)
        pending_consumables = pending_consumables.filter(med_filter)

    # Group medications by visit
    visits_meds = OrderedDict()
    for med in pending_meds.order_by('admission__patient__first_name', 'admission__visit__id'):
        visit = med.admission.visit
        key = visit.id if visit else f'no-visit-{med.admission.id}'
        if key not in visits_meds:
            visits_meds[key] = {
                'visit': visit,
                'patient': med.admission.patient,
                'admission': med.admission,
                'meds': [],
                'consumables': [],
            }
        visits_meds[key]['meds'].append(med)
    
    # Group consumables by visit  
    for con in pending_consumables.order_by('admission__patient__first_name', 'admission__visit__id'):
        visit = con.admission.visit
        key = visit.id if visit else f'no-visit-{con.admission.id}'
        if key not in visits_meds:
            visits_meds[key] = {
                'visit': visit,
                'patient': con.admission.patient,
                'admission': con.admission,
                'meds': [],
                'consumables': [],
            }
        visits_meds[key]['consumables'].append(con)

    total_pending_meds = sum(len(v['meds']) for v in visits_meds.values())
    total_pending_consumables = sum(len(v['consumables']) for v in visits_meds.values())

    # Get Mini Pharmacy department
    mini_pharmacy = Departments.objects.filter(name='Mini Pharmacy').first()
    
    # Get available stock in Mini Pharmacy
    mini_pharmacy_stock = []
    if mini_pharmacy:
        mini_pharmacy_stock = StockRecord.objects.filter(
            current_location=mini_pharmacy
        ).values(
            'item__name', 'item__dispensing_unit'
        ).annotate(
            total_quantity=Sum('quantity')
        ).filter(total_quantity__gt=0).order_by('item__name')
    
    # Get stock requests where target location is Mini Pharmacy
    mini_pharmacy_requests = []
    if mini_pharmacy:
        mini_pharmacy_requests = InventoryRequest.objects.filter(
            location=mini_pharmacy,
            status='Pending'
        ).select_related('item', 'requested_by', 'location', 'requested_from').order_by('-requested_at')

    context = {
        'visits_grouped': visits_meds,
        'total_pending_meds': total_pending_meds,
        'total_pending_consumables': total_pending_consumables,
        'total_patients': len(visits_meds),
        'mini_pharmacy_stock': mini_pharmacy_stock,
        'mini_pharmacy_requests': mini_pharmacy_requests,
        'search_query': search_query,
        'title': 'IPD Pharmacy Fulfillment',
        'all_pharmacies': [user_dept] if user_dept else [],
        'locked_department': user_dept,
    }
    return render(request, 'inventory/ipd_pharmacy_dashboard.html', context)

@login_required
@require_POST
def confirm_ipd_fulfillment(request):
    """
    Handle partial dispensing to IPD patients.
    Deducts stock and creates an InvoiceItem.
    """
    from inpatient.models import MedicationChart, InpatientConsumable
    from accounts.models import InvoiceItem
    from accounts.utils import get_or_create_invoice
    from home.models import Departments
    from .models import StockRecord, StockAdjustment
    from django.db.models import Sum
    
    item_type = request.POST.get('type') # 'med' or 'consumable'
    item_id = request.POST.get('id')
    dispense_qty_raw = request.POST.get('quantity', '0')
    department_id = request.POST.get('department_id')
    
    try:
        dispense_qty = int(dispense_qty_raw)
        if dispense_qty <= 0:
            messages.error(request, "Invalid quantity.")
            return redirect('inventory:ipd_pharmacy_dashboard')

        with transaction.atomic():
            if item_type == 'med':
                obj = get_object_or_404(MedicationChart, id=item_id)
            else:
                obj = get_object_or_404(InpatientConsumable, id=item_id)
                
            # Enforce dispensing location by logged-in role, regardless of posted dropdown value.
            if request.user.role == 'Pharmacist':
                department = Departments.objects.filter(name='Pharmacy').first()
            elif request.user.role == 'Nurse':
                department = Departments.objects.filter(name='Mini Pharmacy').first()
            elif request.user.role == 'Admin' or request.user.is_superuser:
                department = Departments.objects.filter(name='Pharmacy').first()
            else:
                messages.error(request, "Access denied.")
                return redirect('inventory:ipd_pharmacy_dashboard')

            if not department:
                messages.error(request, "Assigned dispensing location was not found.")
                return redirect('inventory:ipd_pharmacy_dashboard')
            admission = obj.admission
            visit = admission.visit
            
            if not visit:
                 messages.error(request, "Admissions visit not found. Billing cannot proceed.")
                 return redirect('inventory:ipd_pharmacy_dashboard')

            # 1. Check Stock
            available_stock = StockRecord.objects.filter(
                item=obj.item, 
                current_location=department
            ).aggregate(total=Sum('quantity'))['total'] or 0
            
            if available_stock < dispense_qty:
                messages.error(request, f"Insufficient stock in {department.name}. Available: {available_stock}")
                return redirect('inventory:ipd_pharmacy_dashboard')
                
            # 2. Deduct Stock (FEFO)
            remaining_to_deduct = dispense_qty
            batches = StockRecord.objects.filter(
                item=obj.item, 
                current_location=department, 
                quantity__gt=0
            ).order_by('expiry_date', 'received_date')
            
            for batch in batches:
                if remaining_to_deduct <= 0: break
                take = min(batch.quantity, remaining_to_deduct)
                batch.quantity -= take
                batch.save()
                remaining_to_deduct -= take
                
            # 3. Create Stock Adjustment Record
            StockAdjustment.objects.create(
                item=obj.item,
                quantity=-dispense_qty,
                adjustment_type='Usage',
                reason=f'IPD Dispense: {admission.patient.full_name} (Admission #{admission.id})',
                adjusted_by=request.user,
                adjusted_from=department
            )
            
            # 4. Billing (Invoice Item)
            invoice = get_or_create_invoice(visit=visit, user=request.user)
            InvoiceItem.objects.create(
                invoice=invoice,
                inventory_item=obj.item,
                name=f"{obj.item.name} (IPD Dispense)",
                quantity=dispense_qty,
                unit_price=obj.item.selling_price,
                created_by=request.user
            )
            
            # 5. Update Object
            obj.quantity_dispensed += dispense_qty
            if obj.quantity_dispensed >= obj.total_quantity:
                obj.is_dispensed = True
                obj.dispensed_at = timezone.now()
                obj.dispensed_by = request.user
            obj.save()
            
            messages.success(request, f"Successfully dispensed {dispense_qty} units of {obj.item.name} to {admission.patient.full_name}.")
            
    except Exception as e:
        messages.error(request, f"Dispensing failed: {str(e)}")
        
    return redirect('inventory:ipd_pharmacy_dashboard')
@login_required
def stock_activity(request):
    """
    View to track how inventory has been used by patients.
    Includes filtering by item and date.
    """
    item_id = request.GET.get('item_id')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')

    # Base queryset for activities
    activities = DispensedItem.objects.all().select_related(
        'item', 'patient', 'dispensed_by', 'department', 'visit'
    )

    # Apply filters
    if item_id:
        activities = activities.filter(item_id=item_id)
    
    if from_date:
        activities = activities.filter(dispensed_at__date__gte=from_date)
    if to_date:
        activities = activities.filter(dispensed_at__date__lte=to_date)

    # All items for the filter search (or use the JSON search API)
    items = InventoryItem.objects.all().order_by('name')

    # Calculate Total Quantity if filtered by item
    total_quantity = 0
    if item_id:
        from django.db.models import Sum
        total_quantity = activities.aggregate(total=Sum('quantity'))['total'] or 0

    context = {
        'activities': activities[:200],  # Limit to 200 for performance
        'total_quantity': total_quantity,
        'items': items,
        'selected_item_id': int(item_id) if item_id and item_id.isdigit() else None,
        'from_date': from_date,
        'to_date': to_date,
        'title': 'Stock Activity'
    }
    return render(request, 'inventory/stock_activity.html', context)
