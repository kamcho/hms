from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import InventoryItem, InventoryCategory, Supplier, StockRecord, InventoryRequest
from .forms import InventoryItemForm, InventoryCategoryForm, SupplierForm, StockRecordForm, InventoryRequestForm, MedicationForm, ConsumableDetailForm

from django.db.models import Sum

@login_required
def item_list(request):
    items = InventoryItem.objects.annotate(
        total_stock=Sum('stock_records__quantity')
    ).select_related('category')
    return render(request, 'inventory/item_list.html', {'items': items})

@login_required
def add_item(request):
    if request.method == 'POST':
        item_form = InventoryItemForm(request.POST)
        med_form = MedicationForm(request.POST)
        con_form = ConsumableDetailForm(request.POST)
        
        if item_form.is_valid():
            item_type = item_form.cleaned_data.get('item_type')
            
            # Sub-model validation: Only check forms for the SELECTED type
            item = None
            if item_type == 'Medicine':
                if med_form.is_valid():
                    item = item_form.save()
                    medication = med_form.save(commit=False)
                    medication.item = item
                    medication.save()
            elif item_type == 'Consumable':
                if con_form.is_valid():
                    item = item_form.save()
                    consumable = con_form.save(commit=False)
                    consumable.item = item
                    consumable.save()
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
            stock.save()
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
            return redirect('lab:radiology_dashboard')
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
