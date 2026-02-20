from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from .utils import get_or_create_invoice
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import timedelta, datetime
from django.http import HttpResponse, JsonResponse
from decimal import Decimal
from django.views.decorators.http import require_POST
from django.contrib import messages
from .models import (
    Invoice, Payment, Service, Expense, InventoryPurchase, 
    ExpenseCategory, SupplierInvoice, SupplierPayment, InvoiceItem
)
from .forms import (
    ExpenseForm, InventoryPurchaseForm, ExpenseCategoryForm, 
    SupplierInvoiceForm, SupplierPaymentForm
)
from home.models import Patient, Departments, Visit
from morgue.models import Deceased, MorgueAdmission
from inpatient.models import Admission, Ward, MedicationChart, ServiceAdmissionLink
from inventory.models import StockRecord, Supplier
import json
import csv

def is_accountant(user):
    return user.is_authenticated and (user.role == 'Accountant' or user.is_superuser)

def is_receptionist(user):
    return user.is_authenticated and (user.role == 'Receptionist' or user.is_superuser)

def is_billing_staff(user):
    return user.is_authenticated and (user.role in ['Accountant', 'Receptionist', 'SHA Manager', 'SHA'] or user.is_superuser)

@login_required
@user_passes_test(is_accountant)
def accountant_dashboard(request):
    # Get date filters from request
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    # Date ranges for analytics
    today = timezone.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)
    
    # Base querysets
    invoices = Invoice.objects.all()
    payments = Payment.objects.all()
    
    # New Expense system
    general_expenses = Expense.objects.all()
    inventory_purchases = InventoryPurchase.objects.all()
    supplier_invoices = SupplierInvoice.objects.all()
    
    # Apply date filters if provided
    if from_date:
        try:
            from_date = timezone.datetime.strptime(from_date, '%Y-%m-%d').date()
            invoices = invoices.filter(created_at__date__gte=from_date)
            payments = payments.filter(payment_date__date__gte=from_date)
            general_expenses = general_expenses.filter(date__gte=from_date)
            inventory_purchases = inventory_purchases.filter(date__gte=from_date)
            supplier_invoices = supplier_invoices.filter(date__gte=from_date)
        except ValueError:
            from_date = None
    
    if to_date:
        try:
            to_date = timezone.datetime.strptime(to_date, '%Y-%m-%d').date()
            invoices = invoices.filter(created_at__date__lte=to_date)
            payments = payments.filter(payment_date__date__lte=to_date)
            general_expenses = general_expenses.filter(date__lte=to_date)
            inventory_purchases = inventory_purchases.filter(date__lte=to_date)
            supplier_invoices = supplier_invoices.filter(date__lte=to_date)
        except ValueError:
            to_date = None
    
    # --- 1. Revenue Metrics ---
    total_revenue = payments.aggregate(Sum('amount'))['amount__sum'] or 0
    total_general_expenses = general_expenses.aggregate(Sum('amount'))['amount__sum'] or 0
    total_inventory_purchases = inventory_purchases.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    # Supplier Metrics (AP)
    total_invoice_debt = supplier_invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_invoice_paid = supplier_invoices.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
    total_payable = total_invoice_debt - total_invoice_paid
    
    total_expenses = total_general_expenses + total_invoice_debt # Accrual basis: Operational + Invoiced Debt
    net_profit = total_revenue - (total_general_expenses + total_invoice_paid) # Cash basis profit

    # Weekly/Monthly Revenue (only if no custom filter)
    if not from_date and not to_date:
        weekly_revenue = Payment.objects.filter(payment_date__date__gte=start_of_week).aggregate(Sum('amount'))['amount__sum'] or 0
        monthly_revenue = Payment.objects.filter(payment_date__date__gte=start_of_month).aggregate(Sum('amount'))['amount__sum'] or 0
    else:
        weekly_revenue = 0
        monthly_revenue = 0

    # --- 2. Payment Method Reconciliation ---
    payment_methods = payments.values('payment_method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')

    # --- 3. In-Patient vs Out-Patient Revenue ---
    visit_revenue = invoices.values('visit__visit_type').annotate(
        total=Sum('paid_amount')
    ).order_by('-total')

    # --- 4. Aging Debtors (Unpaid Invoices) ---
    unpaid_invoices = invoices.filter(status__in=['Pending', 'Partial', 'Draft'])
    aging_debtors = {
        '0-7 Days': 0,
        '8-30 Days': 0,
        '30+ Days': 0
    }
    
    for inv in unpaid_invoices:
        age = (today - inv.created_at.date()).days
        balance = inv.balance
        if age <= 7:
            aging_debtors['0-7 Days'] += float(balance)
        elif age <= 30:
            aging_debtors['8-30 Days'] += float(balance)
        else:
            aging_debtors['30+ Days'] += float(balance)

    # --- 5. Cashier Accountability ---
    cashier_stats = payments.values(
        'created_by__id_number'
    ).annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')

    # --- Chart Data Preparation ---
    
    # Revenue Trend (Daily or Monthly)
    daily_revenue_data = []
    daily_labels = []
    for i in range(30, 0, -1):
        date = today - timedelta(days=i)
        daily_labels.append(date.strftime('%b %d'))
        day_rev = Payment.objects.filter(payment_date__date=date).aggregate(Sum('amount'))['amount__sum'] or 0
        daily_revenue_data.append(float(day_rev))
        
    # Service Type Breakdown (Revenue by Service Category)
    service_breakdown = invoices.filter(items__service__isnull=False).values(
        'items__service__department__name'
    ).annotate(
        revenue=Sum(F('items__quantity') * F('items__unit_price'))
    ).order_by('-revenue')
    
    service_labels = [item['items__service__department__name'] for item in service_breakdown]
    service_data = [float(item['revenue']) for item in service_breakdown]

    # Recent Transactions
    recent_transactions = payments.select_related('invoice', 'invoice__patient').order_by('-payment_date')[:10]

    # Handle Export
    if request.GET.get('export') == 'csv':
        return export_accountant_csv(payments, invoices, total_revenue, total_expenses, payment_methods)

    context = {
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'total_payable': total_payable,
        'total_general_expenses': total_general_expenses,
        'total_inventory_purchases': total_inventory_purchases,
        'net_profit': net_profit,
        'weekly_revenue': weekly_revenue,
        'monthly_revenue': monthly_revenue,
        
        'payment_methods': payment_methods,
        'visit_revenue': visit_revenue,
        'aging_debtors': aging_debtors,
        'cashier_stats': cashier_stats,
        'recent_transactions': recent_transactions,
        
        'from_date': from_date,
        'to_date': to_date,
        
        # JSON Data for Charts
        'daily_labels': json.dumps(daily_labels),
        'daily_revenue_data': json.dumps(daily_revenue_data),
        'service_labels': json.dumps(service_labels),
        'service_data': json.dumps(service_data),
        'payment_method_labels': json.dumps([p['payment_method'] for p in payment_methods]),
        'payment_method_data': json.dumps([float(p['total']) for p in payment_methods]),
    }
    
    return render(request, 'accounts/accountant_dashboard.html', context)

@login_required
@user_passes_test(is_billing_staff)
def insurance_manager(request):
    search_query = request.GET.get('search', '')
    
    # Filter for unpaid or partially paid invoices
    unpaid_invoices = Invoice.objects.filter(
        status__in=['Pending', 'Partial']
    ).select_related('patient', 'visit', 'deceased').order_by('-created_at')
    
    if search_query:
        unpaid_invoices = unpaid_invoices.filter(
            Q(patient__first_name__icontains=search_query) |
            Q(patient__last_name__icontains=search_query) |
            Q(deceased__first_name__icontains=search_query) |
            Q(deceased__last_name__icontains=search_query) |
            Q(id__icontains=search_query)
        )

    # Grouping by visit type
    opd_invoices = unpaid_invoices.filter(visit__visit_type='OUT-PATIENT')
    ipd_invoices = unpaid_invoices.filter(visit__visit_type='IN-PATIENT')
    
    # Invoices without a visit (e.g., external lab requests or mortuary)
    other_invoices = unpaid_invoices.filter(visit__isnull=True)

    context = {
        'opd_invoices': opd_invoices,
        'ipd_invoices': ipd_invoices,
        'other_invoices': other_invoices,
        'search_query': search_query,
        'title': 'Insurance & Credit Manager'
    }
    
    return render(request, 'accounts/insurance_manager.html', context)

@login_required
@user_passes_test(is_billing_staff)
def get_invoice_items(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)
    items_data = []
    for item in invoice.items.all().order_by('created_at'):
        items_data.append({
            'id': item.id,
            'name': item.name,
            'quantity': item.quantity,
            'unit_price': float(item.unit_price),
            'amount': float(item.amount),
            'paid_amount': float(item.paid_amount),
            'balance': float(item.balance),
            'is_settled': item.is_settled
        })
    
    # For IPD invoices, include admission days and per-diem info
    admission_info = None
    if invoice.visit and invoice.visit.visit_type == 'IN-PATIENT':
        admission = Admission.objects.filter(visit=invoice.visit).first()
        if admission:
            if admission.discharged_at:
                days = max(1, (admission.discharged_at - admission.admitted_at).days)
            else:
                days = max(1, (timezone.now() - admission.admitted_at).days)
            per_diem_rate = 2400
            admission_info = {
                'days': days,
                'per_diem_rate': per_diem_rate,
                'per_diem_total': days * per_diem_rate,
                'total_billed': float(invoice.total_amount),
                'current_adjustment': float(invoice.insurance_adjustment),
            }
    
    return JsonResponse({'items': items_data, 'admission_info': admission_info})

@login_required
@user_passes_test(is_billing_staff)
@require_POST
def process_insurance_claim(request):
    try:
        data = json.loads(request.body)
        invoice_id = data.get('invoice_id')
        item_ids = data.get('item_ids')
        claim_id = data.get('claim_id', '')
        custom_amount = data.get('amount')
        adjustment = data.get('adjustment', 0)

        invoice = get_object_or_404(Invoice, id=invoice_id)
        selected_items = invoice.items.filter(id__in=item_ids)
        
        # Apply insurance adjustment if provided (per-diem gap/profit)
        # Note: adjustment can be negative if we claim more than we billed
        if adjustment is not None:
            invoice.insurance_adjustment = Decimal(str(adjustment))
            invoice.save()
            invoice.update_totals()
        
        # Calculate selected items total as a sanity check
        selected_total = selected_items.aggregate(total=Sum('amount'))['total'] or 0
        
        # Use custom amount if provided, otherwise fallback to selected total
        claim_amount = Decimal(str(custom_amount)) if custom_amount is not None else selected_total
        
        if claim_amount <= 0:
            return JsonResponse({'success': False, 'error': 'Claim amount must be greater than zero.'})
            
        # Re-check balance after adjustment application
        if claim_amount > invoice.balance:
            return JsonResponse({'success': False, 'error': f'Claim amount (Ksh {claim_amount}) exceeds remaining invoice balance (Ksh {invoice.balance}). If this is a per-diem profit, the adjustment should have handled it.'})

        # Create Payment
        payment = Payment.objects.create(
            invoice=invoice,
            amount=claim_amount,
            payment_method='Insurance',
            transaction_reference=claim_id,
            notes=f"Insurance claim for items: {', '.join([item.name for item in selected_items])}",
            created_by=request.user
        )
        
        return JsonResponse({
            'success': True, 
            'payment_id': payment.id,
            'amount': float(claim_amount),
            'adjustment': float(invoice.insurance_adjustment)
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def export_accountant_csv(payments, invoices, total_revenue, total_expenses, payment_methods):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="fms_report_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['FMS FINANCIAL REPORT'])
    writer.writerow(['Generated:', timezone.now().strftime('%Y-%m-%d %H:%M')])
    writer.writerow([])
    
    writer.writerow(['SUMMARY'])
    writer.writerow(['Total Revenue', total_revenue])
    writer.writerow(['Total Expenses', total_expenses])
    writer.writerow(['Net Profit', total_revenue - total_expenses])
    writer.writerow([])
    
    writer.writerow(['PAYMENT RECONCILIATION'])
    for pm in payment_methods:
        writer.writerow([pm['payment_method'], pm['total'], f"{pm['count']} txns"])
    writer.writerow([])

    writer.writerow(['RECENT TRANSACTIONS'])
    writer.writerow(['Date', 'Receipt #', 'Patient', 'Method', 'Amount', 'Cashier'])
    for p in payments.order_by('-payment_date')[:50]:
        writer.writerow([
            p.payment_date.strftime('%Y-%m-%d %H:%M'),
            p.transaction_reference or f"PAY-{p.id}",
            p.invoice.patient.full_name,
            p.payment_method,
            p.amount,
            p.created_by.id_number if p.created_by else 'System'
        ])
        
    return response

@login_required
@user_passes_test(is_billing_staff)
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    
    # Check for active admission/morgue admission linked to this invoice
    can_authorize = False
    admission_type = None
    
    if invoice.status == 'Paid':
        if invoice.patient and invoice.visit:
            if Admission.objects.filter(visit=invoice.visit, status='Admitted').exists():
                can_authorize = True
                admission_type = 'IPD'
        elif invoice.deceased:
            if MorgueAdmission.objects.filter(deceased=invoice.deceased, status='ADMITTED').exists():
                can_authorize = True
                admission_type = 'Morgue'
                
    context = {
        'invoice': invoice,
        'can_authorize': can_authorize,
        'admission_type': admission_type,
        'can_record_payment': is_receptionist(request.user),
    }
    return render(request, 'accounts/invoice_detail.html', context)

@login_required
@user_passes_test(is_receptionist)
def record_payment(request, pk):
    if request.method == 'POST':
        invoice = get_object_or_404(Invoice, pk=pk)
        amount = request.POST.get('amount')
        payment_method = request.POST.get('payment_method')
        reference = request.POST.get('reference')
        
        try:
            payment = Payment.objects.create(
                invoice=invoice,
                amount=amount,
                payment_method=payment_method,
                transaction_reference=reference,
                created_by=request.user
            )
            from django.contrib import messages
            messages.success(request, f"Payment of {amount} recorded successfully.")
            return HttpResponse(json.dumps({'success': True}), content_type="application/json")
        except Exception as e:
            return HttpResponse(json.dumps({'success': False, 'error': str(e)}), content_type="application/json")
    return HttpResponse(status=405)

@login_required
@user_passes_test(is_billing_staff)
def delete_invoice(request, pk):
    if request.method == 'POST':
        invoice = get_object_or_404(Invoice, pk=pk)
        
        # Check if the user is the creator
        if invoice.created_by != request.user:
            return JsonResponse({'success': False, 'error': 'Only the person who created this invoice can delete it.'})
        
        # Check if the invoice has any payments
        if invoice.payments.exists():
            return JsonResponse({'success': False, 'error': 'Cannot delete an invoice that has existing payment records.'})
        
        try:
            patient_id = invoice.patient.id if invoice.patient else None
            invoice.delete()
            from django.contrib import messages
            messages.success(request, "Invoice deleted successfully.")
            return JsonResponse({'success': True, 'patient_id': patient_id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    return HttpResponse(status=405)

@login_required
@user_passes_test(is_billing_staff)
def delete_invoice_item(request, item_id):
    if request.method == 'POST':
        item = get_object_or_404(InvoiceItem, pk=item_id)
        invoice = item.invoice
        
        # Permission Check: Admin or Invoice Creator or Item Creator
        if request.user.is_superuser or invoice.created_by == request.user or item.created_by == request.user:
             pass
        else:
            return JsonResponse({'success': False, 'error': 'Only the item creator or invoice creator can delete items.'})
        
        # State Check: Unpaid only
        if item.paid_amount > 0:
            return JsonResponse({'success': False, 'error': 'Cannot delete an item that has been partially or fully paid.'})
            
        try:
            item.delete()
            invoice.update_totals() # Recalculate invoice totals
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    return HttpResponse(status=405)

@login_required
@user_passes_test(is_billing_staff)
def invoice_list(request):
    """List all invoices with filtering options"""
    invoices = Invoice.objects.all().select_related('patient', 'deceased', 'created_by')
    
    # Filter by deceased if specified
    deceased_id = request.GET.get('deceased')
    if deceased_id:
        invoices = invoices.filter(deceased_id=deceased_id)
    
    # Filter by patient if specified
    patient_id = request.GET.get('patient')
    if patient_id:
        invoices = invoices.filter(patient_id=patient_id)
    
    # Filter by status
    status = request.GET.get('status')
    if status:
        invoices = invoices.filter(status=status)
    
    # Search functionality
    search = request.GET.get('search')
    if search:
        invoices = invoices.filter(
            Q(patient__full_name__icontains=search) |
            Q(deceased__full_name__icontains=search) |
            Q(id__icontains=search)
        )
    
    # Order by most recent
    invoices = invoices.order_by('-created_at')
    
    context = {
        'invoices': invoices,
        'deceased_filter': deceased_id,
        'patient_filter': patient_id,
        'status_filter': status,
        'search_query': search,
    }
    return render(request, 'accounts/invoice_list.html', context)

@login_required
@user_passes_test(is_billing_staff)
def create_invoice(request):
    """Create a new invoice for patient or deceased"""
    if request.method == 'POST':
        # Check if this is an AJAX request from the modal
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                # Handle modal form submission
                deceased_id = request.POST.get('deceased')
                patient_id = request.POST.get('patient')
                notes = request.POST.get('notes', '')
                due_date = request.POST.get('due_date')
                total_amount = request.POST.get('total_amount', '0')
                
                if deceased_id:
                    deceased = get_object_or_404(Deceased, pk=deceased_id)
                    invoice = get_or_create_invoice(deceased=deceased, user=request.user)
                    
                    # Update fields if provided
                    if notes: invoice.notes = notes
                    if due_date: invoice.due_date = due_date
                    if total_amount: invoice.total_amount = total_amount
                    invoice.save()
                    return JsonResponse({
                        'success': True, 
                        'invoice_id': invoice.id,
                        'message': f'Invoice created for {deceased.full_name}'
                    })
                elif patient_id:
                    patient = get_object_or_404(Patient, pk=patient_id)
                    from home.models import Visit
                    visit = Visit.objects.filter(patient=patient, is_active=True).last()
                    
                    invoice = get_or_create_invoice(visit=visit, user=request.user)
                    if not invoice:
                        # Fallback for visit-less invoice if really needed, though get_or_create_invoice handles visit=None poorly right now
                        invoice = Invoice.objects.create(patient=patient, created_by=request.user, status='Draft')

                    if notes: invoice.notes = notes
                    if due_date: invoice.due_date = due_date
                    if total_amount: invoice.total_amount = total_amount
                    invoice.save()
                    return JsonResponse({
                        'success': True, 
                        'invoice_id': invoice.id,
                        'message': f'Invoice created for {patient.full_name}'
                    })
                else:
                    return JsonResponse({'success': False, 'error': 'No patient or deceased specified'})
                    
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
        
        # Handle regular form submission (original logic)
        invoice_type = request.POST.get('type')
        entity_id = request.POST.get('entity_id')
        
        try:
            if invoice_type == 'deceased':
                deceased = get_object_or_404(Deceased, pk=entity_id)
                invoice = get_or_create_invoice(deceased=deceased, user=request.user)
                messages.success(request, f'Invoice retrieval/creation successful for {deceased.full_name}')
                return redirect('accounts:invoice_detail', pk=invoice.pk)
            elif invoice_type == 'patient':
                patient = get_object_or_404(Patient, pk=entity_id)
                from home.models import Visit
                visit = Visit.objects.filter(patient=patient, is_active=True).last()
                invoice = get_or_create_invoice(visit=visit, user=request.user)
                if not invoice:
                    invoice = Invoice.objects.create(patient=patient, created_by=request.user, status='Draft')
                messages.success(request, f'Invoice retrieval/creation successful for {patient.full_name}')
                return redirect('accounts:invoice_detail', pk=invoice.pk)
        except Exception as e:
            messages.error(request, f'Error creating invoice: {str(e)}')
    
    # If GET request, show the form to select entity
    deceased_id = request.GET.get('deceased')
    patient_id = request.GET.get('patient')
    
    context = {
        'deceased_id': deceased_id,
        'patient_id': patient_id,
    }
    return render(request, 'accounts/create_invoice.html', context)

@login_required
@user_passes_test(is_billing_staff)
def expense_dashboard(request):
    # Filters
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    expenses = Expense.objects.all().select_related('category', 'recorded_by')
    purchases = InventoryPurchase.objects.all().select_related('supplier', 'invoice_ref', 'recorded_by')
    supplier_invoices = SupplierInvoice.objects.all().select_related('supplier', 'recorded_by')
    
    if from_date:
        expenses = expenses.filter(date__gte=from_date)
        purchases = purchases.filter(date__gte=from_date)
        supplier_invoices = supplier_invoices.filter(date__gte=from_date)
    if to_date:
        expenses = expenses.filter(date__lte=to_date)
        purchases = purchases.filter(date__lte=to_date)
        supplier_invoices = supplier_invoices.filter(date__lte=to_date)

    # Metrics
    total_expenses = expenses.aggregate(Sum('amount'))['amount__sum'] or 0
    total_purchases = purchases.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_invoice_debt = supplier_invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_invoice_paid = supplier_invoices.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
    total_payable = total_invoice_debt - total_invoice_paid

    # Category Breakdown
    category_data = expenses.values('category__name').annotate(total=Sum('amount')).order_by('-total')
    
    # Trends (Last 14 days)
    today = timezone.now().date()
    trend_labels = []
    trend_data = []
    for i in range(14, -1, -1):
        date = today - timedelta(days=i)
        trend_labels.append(date.strftime('%b %d'))
        exp_sum = Expense.objects.filter(date=date).aggregate(Sum('amount'))['amount__sum'] or 0
        pur_sum = InventoryPurchase.objects.filter(date=date).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        trend_data.append(float(exp_sum + pur_sum))

    context = {
        'expenses': expenses[:50],
        'purchases': purchases[:50],
        'supplier_invoices': supplier_invoices[:50],
        'total_expenses': total_expenses,
        'total_purchases': total_purchases,
        'total_payable': total_payable,
        'combined_total': total_expenses + total_purchases,
        'category_data': category_data,
        'trend_labels': json.dumps(trend_labels),
        'trend_data': json.dumps(trend_data),
        'categories': ExpenseCategory.objects.all(),
        'suppliers': Supplier.objects.all(),
        'expense_form': ExpenseForm(),
        'purchase_form': InventoryPurchaseForm(),
        'category_form': ExpenseCategoryForm(),
        'invoice_form': SupplierInvoiceForm(),
        'payment_form': SupplierPaymentForm(),
        'from_date': from_date,
        'to_date': to_date,
        'today': today,
    }
    return render(request, 'accounts/expense_dashboard.html', context)

@login_required
@user_passes_test(is_accountant)
def add_supplier_invoice(request):
    if request.method == 'POST':
        form = SupplierInvoiceForm(request.POST, request.FILES)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.recorded_by = request.user
            invoice.save()
            messages.success(request, f"Invoice {invoice.invoice_number} recorded.")
        else:
            messages.error(request, f"Error: {form.errors}")
    return redirect('accounts:expense_dashboard')

@login_required
@user_passes_test(is_accountant)
def record_supplier_payment(request):
    if request.method == 'POST':
        form = SupplierPaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.recorded_by = request.user
            payment.save()
            messages.success(request, f"Payment of {payment.amount} recorded for {payment.invoice.invoice_number}.")
        else:
            messages.error(request, f"Error: {form.errors}")
    return redirect('accounts:expense_dashboard')

@login_required
@user_passes_test(is_accountant)
def add_expense(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.recorded_by = request.user
            expense.save()
            messages.success(request, "Expense recorded successfully.")
        else:
            messages.error(request, f"Error recording expense: {form.errors}")
    return redirect('accounts:expense_dashboard')


@login_required
@user_passes_test(is_accountant)
def add_expense_category(request):
    if request.method == 'POST':
        form = ExpenseCategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense category added.")
        else:
            messages.error(request, "Error adding category.")
    return redirect('accounts:expense_dashboard')

@login_required
@user_passes_test(is_billing_staff)
def discharge_billing_dashboard(request):
    """Dashboard showing active IPD and Morgue admissions for billing"""
    ipd_admissions = Admission.objects.filter(status='Admitted').select_related('patient', 'bed', 'bed__ward')
    morgue_admissions = MorgueAdmission.objects.filter(status='ADMITTED').select_related('deceased')
    
    context = {
        'ipd_admissions': ipd_admissions,
        'morgue_admissions': morgue_admissions,
    }
    return render(request, 'accounts/discharge_dashboard.html', context)

@login_required
@user_passes_test(is_billing_staff)
def discharge_billing_detail(request, admission_type, admission_id):
    """Detailed billing view for IPD or Morgue discharge"""
    today = timezone.now()
    
    if admission_type == 'ipd':
        admission = get_object_or_404(Admission, pk=admission_id)
        patient = admission.patient
        entity_name = patient.full_name
        admission_date = admission.admitted_at
        
        # Calculate stay days (minimum 1)
        stay_days = max(1, (today - admission_date).days)
        daily_rate = admission.bed.ward.base_charge_per_day if (admission.bed and admission.bed.ward) else 0
        stay_total = stay_days * daily_rate
        
        # Get all services linked to this admission
        admission_services = admission.services.all().select_related('service')
        
    elif admission_type == 'morgue':
        admission = get_object_or_404(MorgueAdmission, pk=admission_id)
        deceased = admission.deceased
        entity_name = deceased.full_name
        admission_date = admission.admission_datetime
        
        # Calculate stay days (minimum 1)
        stay_days = max(1, (today - admission_date).days)
        # Search for a mortuary stay service
        mortuary_service = Service.objects.filter(name__icontains='Mortuary').first()
        daily_rate = mortuary_service.price if mortuary_service else 500 # Default if not found
        stay_total = stay_days * daily_rate
        
        admission_services = deceased.performed_services.all().select_related('service')
    else:
        return redirect('accounts:discharge_dashboard')

    # Get or create active discharge invoice
    if admission_type == 'ipd':
        # Every IPD visit should ideally have one main invoice
        invoice = Invoice.objects.filter(visit=admission.visit).exclude(status='Cancelled').first()
    else:
        # For morgue, we look for an active invoice linked to the deceased
        invoice = Invoice.objects.filter(
            deceased=deceased,
            status__in=['Draft', 'Pending', 'Partial']
        ).first()
    
    if not invoice:
        # Create a new discharge invoice if none exists
        if admission_type == 'ipd':
            invoice = get_or_create_invoice(visit=admission.visit, user=request.user)
            if invoice.notes: invoice.notes += f'\nDISCHARGE BILLING - Admission ID: {admission.id}'
            else: invoice.notes = f'DISCHARGE BILLING - Admission ID: {admission.id}'
            invoice.save()
        else:
            invoice = get_or_create_invoice(deceased=deceased, user=request.user)
            if invoice.notes: invoice.notes += f'\nDISCHARGE BILLING - Morgue Admission ID: {admission.id}'
            else: invoice.notes = f'DISCHARGE BILLING - Morgue Admission ID: {admission.id}'
            invoice.save()

    # REFACTORED SYNC LOGIC: Ensure all services and meds are on the invoice
    existing_items = invoice.items.all()
    existing_service_ids = set(existing_items.filter(service__isnull=False).values_list('service_id', flat=True))
    existing_inventory_ids = set(existing_items.filter(inventory_item__isnull=False).values_list('inventory_item_id', flat=True))
    existing_names = set(existing_items.values_list('name', flat=True))

    # 1. Sync Accommodation/Stay Charges if not already present
    # Check for any item that looks like a stay charge (Daily, Bed, Ward, Accommodation)
    has_stay_charges = existing_items.filter(service__department__name='Inpatient').exists() or any(
        keyword in name.lower() 
        for keyword in ['daily', 'bed', 'ward', 'accommodation', 'stay'] 
        for name in existing_names
    )
    
    if not has_stay_charges:
        stay_service_name = f"Accommodation Charges ({stay_days} Days @ {daily_rate})"
        InvoiceItem.objects.create(
            invoice=invoice,
            name=stay_service_name,
            unit_price=daily_rate,
            quantity=stay_days
        )
    
    # 2. Sync Performed Services (ServiceAdmissionLink)
    for adm_service in admission_services:
        if adm_service.service.id not in existing_service_ids:
            InvoiceItem.objects.create(
                invoice=invoice,
                service=adm_service.service,
                name=adm_service.service.name,
                unit_price=adm_service.service.price,
                quantity=adm_service.quantity
            )
            
    # 3. Sync Administered Medications (IPD only)
    if admission_type == 'ipd':
        administered_meds = MedicationChart.objects.filter(
            admission=admission, 
            is_administered=True
        ).select_related('item')
        
        for med in administered_meds:
            # Create a unique name to track specific medication administration instances
            med_entry_name = f"Medication: {med.item.name} ({med.dosage}) - #{med.id}"
            if med_entry_name not in existing_names:
                InvoiceItem.objects.create(
                    invoice=invoice,
                    inventory_item=med.item,
                    name=med_entry_name,
                    unit_price=med.item.selling_price,
                    quantity=1
                )

    invoice.update_totals()
            
    return redirect('accounts:invoice_detail', pk=invoice.id)

@login_required
@user_passes_test(is_billing_staff)
def authorize_discharge(request, pk):
    """Authorize formal discharge/release once invoice is paid"""
    invoice = get_object_or_404(Invoice, pk=pk)
    
    if invoice.status != 'Paid':
        messages.error(request, "Cannot authorize discharge. Invoice balance is not zero.")
        return redirect('accounts:invoice_detail', pk=pk)
    
    try:
        if invoice.patient and invoice.visit:
            # Handle Inpatient Discharge
            admission = Admission.objects.filter(visit=invoice.visit, status='Admitted').first()
            if admission:
                from inpatient.models import InpatientDischarge
                admission.status = 'Discharged'
                admission.discharged_at = timezone.now()
                admission.discharged_by = request.user
                admission.save()
                
                # Release the bed
                if admission.bed:
                    admission.bed.is_occupied = False
                    admission.bed.save()
                
                # Create formal discharge record if not exists
                InpatientDischarge.objects.get_or_create(
                    admission=admission,
                    defaults={
                        'discharged_by': request.user,
                        'total_bill_at_discharge': invoice.total_amount,
                        'discharge_summary': invoice.notes or "Automatic discharge via billing"
                    }
                )
                messages.success(request, f"Patient {invoice.patient.full_name} has been formally discharged.")
            else:
                messages.warning(request, "Admission record not found or already discharged.")
                
        elif invoice.deceased:
            # Handle Morgue Release
            admission = MorgueAdmission.objects.filter(deceased=invoice.deceased, status='ADMITTED').first()
            if admission:
                from morgue.models import MortuaryDischarge
                admission.status = 'RELEASED'
                admission.release_date = timezone.now()
                admission.save()
                
                # Mark deceased as released
                invoice.deceased.is_released = True
                invoice.deceased.release_date = timezone.now()
                invoice.deceased.save()
                
                # Create formal release record
                MortuaryDischarge.objects.get_or_create(
                    deceased=invoice.deceased,
                    admission=admission,
                    defaults={
                        'authorized_by': request.user,
                        'total_bill_snapshot': invoice.total_amount,
                        'released_to': "See Next of Kin", # Placeholder
                        'relationship': "Family",
                        'receiver_id_number': "N/A"
                    }
                )
                messages.success(request, f"Deceased {invoice.deceased.full_name} has been formally released.")
            else:
                messages.warning(request, "Morgue admission record not found or already released.")
                
    except Exception as e:
        messages.error(request, f"Error during authorization: {str(e)}")
        
    return redirect('accounts:discharge_billing_dashboard')
@login_required
def search_procedures(request):
    """
    JSON API for searching procedures.
    """
    from .models import Service
    query = request.GET.get('q', '')
    if len(query) < 2:
        return JsonResponse({'results': []})
        
    procedures = Service.objects.filter(department__name='Procedure Room', name__icontains=query, is_active=True)[:20]
    results = []
    for proc in procedures:
        results.append({
            'id': proc.id,
            'text': f"{proc.name} (KES {proc.price})",
            'price': str(proc.price)
        })
    return JsonResponse({'results': results})

@login_required
@require_POST
def charge_procedure(request):
    """
    Handle procedure charging via AJAX.
    """
    from .models import Service, Invoice, InvoiceItem
    
    procedure_id = request.POST.get('procedure_id')
    patient_id = request.POST.get('patient_id')
    visit_id = request.POST.get('visit_id')
    notes = request.POST.get('notes', '')

    try:
        service = get_object_or_404(Service, id=procedure_id, department__name='Procedure Room')
        patient = get_object_or_404(Patient, id=patient_id)
        visit = Visit.objects.filter(id=visit_id).first() if visit_id else None

        # Find or Create Active Invoice for this Visit
        invoice = get_or_create_invoice(visit=visit, user=request.user)
        if invoice and not invoice.notes:
             invoice.notes = f"Procedure Charge: {service.name}"
             invoice.save()

        # Create Invoice Item
        InvoiceItem.objects.create(
            invoice=invoice,
            service=service,
            name=service.name,
            unit_price=service.price,
            quantity=1,
            created_by=request.user
        )
        
        # Update Invoice Totals
        invoice.update_totals()
        
        return JsonResponse({
            'status': 'success', 
            'message': f'Successfully charged {procedure.name}'
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
