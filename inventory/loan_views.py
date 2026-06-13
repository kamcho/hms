import json
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from home.models import Departments

from .forms import (
    ExternalInstitutionForm,
    LoanReturnForm,
    LoanWriteOffForm,
    StockLoanHeaderForm,
)
from .loan_utils import (
    InsufficientStockError,
    create_stock_loan,
    return_loan_line,
    write_off_loan_line,
    _available_stock,
)
from .models import (
    ExternalInstitution,
    InventoryItem,
    StockLoan,
    StockLoanLine,
)


def _user_can_manage_stock_loans(user):
    """Stock loans: Admin and Pharmacist roles only."""
    return user.is_authenticated and user.role in ('Admin', 'Pharmacist')


def stock_loan_role_required(view_func):
    """Block access unless user is Admin or Pharmacist."""

    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not _user_can_manage_stock_loans(request.user):
            messages.error(request, 'Only Admin and Pharmacist can access stock loans.')
            return redirect('users:dashboard')
        return view_func(request, *args, **kwargs)

    return wrapper


@stock_loan_role_required
def loan_institution_list(request):
    institutions = ExternalInstitution.objects.annotate(
        loan_count=Count('loans'),
    ).order_by('name')

    return render(request, 'inventory/loan_institution_list.html', {
        'institutions': institutions,
        'title': 'Partner Hospitals',
    })


@stock_loan_role_required
def loan_institution_create(request):
    if request.method == 'POST':
        form = ExternalInstitutionForm(request.POST)
        if form.is_valid():
            inst = form.save()
            messages.success(request, f'Partner hospital "{inst.name}" registered.')
            return redirect('inventory:loan_institution_detail', pk=inst.pk)
    else:
        form = ExternalInstitutionForm()
    return render(request, 'inventory/loan_institution_form.html', {
        'form': form,
        'title': 'Register Partner Hospital',
        'is_edit': False,
    })


@stock_loan_role_required
def loan_institution_edit(request, pk):
    institution = get_object_or_404(ExternalInstitution, pk=pk)
    if request.method == 'POST':
        form = ExternalInstitutionForm(request.POST, instance=institution)
        if form.is_valid():
            form.save()
            messages.success(request, 'Partner hospital updated.')
            return redirect('inventory:loan_institution_detail', pk=institution.pk)
    else:
        form = ExternalInstitutionForm(instance=institution)
    return render(request, 'inventory/loan_institution_form.html', {
        'form': form,
        'institution': institution,
        'title': f'Edit {institution.name}',
        'is_edit': True,
    })


@stock_loan_role_required
def loan_institution_detail(request, pk):
    """All items currently loaned to this hospital."""
    institution = get_object_or_404(ExternalInstitution, pk=pk)

    outstanding_lines = (
        StockLoanLine.objects.filter(loan__institution=institution)
        .annotate(
            outstanding_qty=F('quantity_lent') - F('quantity_returned') - F('quantity_written_off'),
        )
        .filter(outstanding_qty__gt=0)
        .select_related('item', 'loan', 'loan__source_department')
        .order_by('-loan__loan_date', 'item__name')
    )

    loans = (
        StockLoan.objects.filter(institution=institution)
        .select_related('source_department', 'issued_by')
        .order_by('-loan_date')[:50]
    )

    total_outstanding_units = sum(line.outstanding for line in outstanding_lines)

    return render(request, 'inventory/loan_institution_detail.html', {
        'institution': institution,
        'outstanding_lines': outstanding_lines,
        'loans': loans,
        'total_outstanding_units': total_outstanding_units,
        'title': institution.name,
    })


@stock_loan_role_required
def stock_loan_list(request):
    status_filter = request.GET.get('status', '')
    institution_id = request.GET.get('institution', '')

    loans = StockLoan.objects.select_related(
        'institution', 'source_department', 'issued_by',
    ).order_by('-loan_date')

    if status_filter:
        loans = loans.filter(status=status_filter)
    if institution_id:
        loans = loans.filter(institution_id=institution_id)

    institutions = ExternalInstitution.objects.filter(is_active=True).order_by('name')

    return render(request, 'inventory/stock_loan_list.html', {
        'loans': loans[:100],
        'institutions': institutions,
        'status_filter': status_filter,
        'institution_filter': institution_id,
        'title': 'Stock Loans',
    })


@stock_loan_role_required
def stock_loan_create(request):
    if request.method == 'POST':
        header_form = StockLoanHeaderForm(request.POST)
        items_json = request.POST.get('items_json', '[]')
        try:
            items_data = json.loads(items_json)
        except json.JSONDecodeError:
            items_data = []

        if header_form.is_valid() and items_data:
            line_items = []
            for row in items_data:
                try:
                    item_id = int(row.get('item_id'))
                    qty = int(row.get('quantity', 0))
                except (TypeError, ValueError):
                    continue
                if qty <= 0:
                    continue
                line_items.append({
                    'item': item_id,
                    'quantity': qty,
                    'batch_number': (row.get('batch_number') or '').strip() or None,
                })

            if not line_items:
                messages.error(request, 'Add at least one item with a valid quantity.')
            else:
                try:
                    loan = create_stock_loan(
                        institution=header_form.cleaned_data['institution'],
                        source_department=header_form.cleaned_data['source_department'],
                        user=request.user,
                        line_items=line_items,
                        expected_return_date=header_form.cleaned_data.get('expected_return_date'),
                        notes=header_form.cleaned_data.get('notes') or '',
                    )
                    messages.success(
                        request,
                        f'Loan #{loan.id} created — stock issued to {loan.institution.name}.',
                    )
                    return redirect('inventory:stock_loan_detail', pk=loan.pk)
                except InsufficientStockError as e:
                    messages.error(request, str(e))
                except Exception as e:
                    messages.error(request, f'Could not create loan: {e}')
        elif not items_data:
            messages.error(request, 'Add at least one item to the loan.')
        else:
            messages.error(request, 'Please correct the form errors.')
    else:
        institution_id = request.GET.get('institution')
        header_form = StockLoanHeaderForm()
        if institution_id:
            header_form.fields['institution'].initial = institution_id

    inventory_items = InventoryItem.objects.select_related('category').order_by('name')
    departments = Departments.objects.all().order_by('name')

    return render(request, 'inventory/stock_loan_create.html', {
        'header_form': header_form,
        'inventory_items': inventory_items,
        'departments': departments,
        'title': 'New Stock Loan',
    })


@stock_loan_role_required
def stock_loan_detail(request, pk):
    loan = get_object_or_404(
        StockLoan.objects.select_related('institution', 'source_department', 'issued_by'),
        pk=pk,
    )
    lines = loan.lines.select_related('item').prefetch_related('adjustments').order_by('id')

    return render(request, 'inventory/stock_loan_detail.html', {
        'loan': loan,
        'lines': lines,
        'return_form': LoanReturnForm(),
        'writeoff_form': LoanWriteOffForm(),
        'title': f'Loan #{loan.id}',
    })


@stock_loan_role_required
@require_POST
def stock_loan_return(request, pk, line_id):
    loan = get_object_or_404(StockLoan, pk=pk)
    line = get_object_or_404(StockLoanLine, pk=line_id, loan=loan)
    form = LoanReturnForm(request.POST)
    if form.is_valid():
        try:
            return_loan_line(line, form.cleaned_data['quantity'], request.user)
            messages.success(request, f'Returned {form.cleaned_data["quantity"]} × {line.item.name}.')
        except ValueError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, 'Invalid return quantity.')
    return redirect('inventory:stock_loan_detail', pk=loan.pk)


@stock_loan_role_required
@require_POST
def stock_loan_writeoff(request, pk, line_id):
    loan = get_object_or_404(StockLoan, pk=pk)
    line = get_object_or_404(StockLoanLine, pk=line_id, loan=loan)
    form = LoanWriteOffForm(request.POST)
    if form.is_valid():
        try:
            write_off_loan_line(
                line,
                form.cleaned_data['quantity'],
                request.user,
                reason=form.cleaned_data.get('reason') or '',
            )
            messages.success(request, f'Written off {form.cleaned_data["quantity"]} × {line.item.name}.')
        except ValueError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, 'Invalid write-off quantity.')
    return redirect('inventory:stock_loan_detail', pk=loan.pk)


@login_required
def api_loan_item_stock(request):
    """JSON: available qty for item at department (Admin / Pharmacist only)."""
    if not _user_can_manage_stock_loans(request.user):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    item_id = request.GET.get('item_id')
    dept_id = request.GET.get('department_id')
    if not item_id or not dept_id:
        return JsonResponse({'available': 0})

    item = get_object_or_404(InventoryItem, pk=item_id)
    dept = get_object_or_404(Departments, pk=dept_id)
    available = _available_stock(item, dept)
    return JsonResponse({
        'available': available,
        'item_name': item.name,
        'department': dept.name,
    })
