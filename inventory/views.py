from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import InventoryItem, InventoryCategory, Supplier, StockRecord, InventoryRequest, StockAdjustment
from .forms import InventoryItemForm, InventoryCategoryForm, SupplierForm, StockRecordForm, InventoryRequestForm, MedicationForm, ConsumableDetailForm
from home.models import Departments

from django.db.models import Sum

@login_required
def item_list(request):
    # Start with all items, annotate with total stock
    items = InventoryItem.objects.annotate(
        total_stock=Sum('stock_records__quantity')
    ).select_related('category')
    
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
            return redirect('inventory:item_list')
    else:
        form = InventoryRequestForm()
    
    return render(request, 'inventory/create_request.html', {
        'form': form,
        'title': 'Create Inventory Request'
    })

@login_required
def request_list(request):
    requests = InventoryRequest.objects.select_related('item', 'requested_by').order_by('-requested_at')
    return render(request, 'inventory/request_list.html', {'requests': requests})

@login_required
def update_request_status(request, request_id):
    if request.method == 'POST':
        inventory_request = get_object_or_404(InventoryRequest, pk=request_id)
        action = request.POST.get('action')
        
        if action == 'approve':
            try:
                adjusted_qty = int(request.POST.get('adjusted_quantity', inventory_request.quantity))
                
                # Retrieve Main Store
                try:
                    main_store = Departments.objects.get(name='Main Store')
                except Departments.DoesNotExist:
                    messages.error(request, 'Main Store department not found.')
                    return redirect('inventory:item_list')

                # Check if enough stock in Main Store
                total_stock = StockRecord.objects.filter(
                    item=inventory_request.item, 
                    current_location=main_store
                ).aggregate(Sum('quantity'))['quantity__sum'] or 0
                
                if total_stock < adjusted_qty:
                    messages.error(request, f'Insufficient stock in Main Store. Available: {total_stock}')
                    return redirect('inventory:item_list')

                # Proceed with Transfer
                remaining_qty = adjusted_qty
                # Get batches from Main Store (FIFO)
                source_records = StockRecord.objects.filter(
                    item=inventory_request.item, 
                    current_location=main_store, 
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
                        adjusted_from=main_store
                    )
                    StockAdjustment.objects.create(
                        item=inventory_request.item,
                        quantity=qty_to_take,
                        adjustment_type='Transfer In',
                        reason=f'Approved Request from Main Store',
                        adjusted_by=request.user,
                        adjusted_from=inventory_request.location
                    )

                    remaining_qty -= qty_to_take

                inventory_request.adjusted_quantity = adjusted_qty
                inventory_request.status = 'Approved'
                messages.success(request, f'Request approved. {adjusted_qty} units transferred to {inventory_request.location.name}.')
            except ValueError:
                messages.error(request, 'Invalid quantity provided.')
                return redirect('inventory:item_list')
        elif action == 'reject':
            inventory_request.status = 'Rejected'
            messages.info(request, f'Request for {inventory_request.item.name} rejected.')
        
        inventory_request.save()
        return redirect('inventory:item_list')
    
    return redirect('inventory:item_list')

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
    if len(query) < 2:
        return JsonResponse({'results': []})
        
    items = InventoryItem.objects.filter(name__icontains=query).select_related('category')[:20]
    results = []
    for item in items:
        results.append({
            'id': item.id,
            'text': f"{item.name} ({item.dispensing_unit})",
            'category': item.category.name
        })
    return JsonResponse({'results': results})

@login_required
@require_POST
def dispense_item(request):
    """
    Handle item dispensing via AJAX.
    """
    item_id = request.POST.get('item_id')
    patient_id = request.POST.get('patient_id')
    visit_id = request.POST.get('visit_id')
    quantity_str = request.POST.get('quantity', '0')
    department_id = request.POST.get('department_id')

    try:
        quantity = int(quantity_str)
        if quantity <= 0:
            return JsonResponse({'status': 'error', 'message': 'Invalid quantity'}, status=400)
            
        with transaction.atomic():
            item = get_object_or_404(InventoryItem, id=item_id)
            patient = get_object_or_404(Patient, id=patient_id)
            visit = Visit.objects.filter(id=visit_id).first() if visit_id else None
            
            # Determine Department (Default to Main Store if not provided for now, or error)
            # In a real scenario, we should get the logged-in user's department.
            department = None
            if department_id:
                department = Departments.objects.filter(id=department_id).first()
            
            if not department:
                 # Fallback: Try to find 'Main Store'
                department = Departments.objects.filter(name='Main Store').first()
            
            if not department:
                return JsonResponse({'status': 'error', 'message': 'Department not identified'}, status=400)

            # Check Stock in Department
            stock_records = StockRecord.objects.filter(
                item=item,
                current_location=department,
                quantity__gt=0
            ).order_by('expiry_date').select_for_update()

            total_available = sum(record.quantity for record in stock_records)
            if total_available < quantity:
                return JsonResponse({
                    'status': 'error', 
                    'message': f'Insufficient stock in {department.name}. Available: {total_available}'
                }, status=400)

            # Deduct Stock (FEFO)
            remaining_qty = quantity
            for record in stock_records:
                if remaining_qty <= 0:
                    break
                
                take = min(record.quantity, remaining_qty)
                record.quantity -= take
                record.save()
                
                # Log Usage
                StockAdjustment.objects.create(
                    item=item,
                    quantity=-take,
                    adjustment_type='Usage',
                    reason=f'Dispensed to {patient.full_name}',
                    adjusted_by=request.user,
                    adjusted_from=department
                )
                remaining_qty -= take
            
            # Create Dispensed Record
            DispensedItem.objects.create(
                item=item,
                patient=patient,
                visit=visit,
                quantity=quantity,
                dispensed_by=request.user,
                department=department
            )
            
            return JsonResponse({
                'status': 'success', 
                'message': f'Successfully dispensed {quantity} {item.dispensing_unit}(s) of {item.name}'
            })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
@login_required
def procurement_dashboard(request):
    """Dashboard for managing Stock Intake (GRN)"""
    from datetime import datetime
    
    # Imports inside function to avoid circular imports if any
    from accounts.models import InventoryPurchase, SupplierInvoice
    
    # Get date filters
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    purchases = InventoryPurchase.objects.all().select_related('supplier', 'invoice_ref', 'recorded_by').order_by('-date')
    
    if from_date:
        purchases = purchases.filter(date__gte=from_date)
    if to_date:
        purchases = purchases.filter(date__lte=to_date)
        
    # Form for adding purchase (GRN)
    # We need to import the form here or ensure it's available
    from .forms import InventoryPurchaseForm
    
    context = {
        'purchases': purchases,
        'from_date': from_date,
        'to_date': to_date,
        'purchase_form': InventoryPurchaseForm(),
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
    added_items = purchase.stock_records.all().select_related('item', 'item__category', 'current_location')
    
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
