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
