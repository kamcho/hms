from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Sum, Count
from datetime import timedelta
from .models import Prescription, PrescriptionItem
from inventory.models import InventoryItem, StockRecord, InventoryRequest
from home.models import Departments


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
    
    # Get pending prescriptions (not dispensed)
    pending_items = PrescriptionItem.objects.filter(
        dispensed=False
    ).select_related(
        'prescription__patient',
        'prescription__prescribed_by',
        'medication'
    ).order_by('-prescription__prescribed_at')
    
    if search_query:
        pending_items = pending_items.filter(
            Q(prescription__patient__first_name__icontains=search_query) |
            Q(prescription__patient__last_name__icontains=search_query) |
            Q(medication__name__icontains=search_query)
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
    
    # Get pharmacy stock
    pharmacy_stock = StockRecord.objects.filter(
        current_location=pharmacy_dept,
        quantity__gt=0
    ).select_related('item', 'supplier').order_by('item__name')
    
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
    inventory_requests = InventoryRequest.objects.filter(
        location=pharmacy_dept
    ).select_related('item', 'requested_by').order_by('-requested_at')[:20]
    
    # Statistics
    stats = {
        'pending_prescriptions': pending_items.count(),
        'low_stock_count': len(set(low_stock_items)),
        'pending_requests': inventory_requests.filter(status='Pending').count(),
        'dispensed_today': PrescriptionItem.objects.filter(
            dispensed=True,
            dispensed_at__date=today
        ).count(),
    }
    
    context = {
        'pending_items': pending_items,
        'dispensed_items': dispensed_items,
        'pharmacy_stock': pharmacy_stock,
        'low_stock_items': low_stock_items,
        'expiring_soon_items': expiring_soon_items,
        'inventory_requests': inventory_requests,
        'stats': stats,
        'search_query': search_query,
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
