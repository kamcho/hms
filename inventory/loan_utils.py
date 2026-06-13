"""Stock loan issue, return, and write-off with StockRecord + StockAdjustment updates."""

from django.db import transaction
from django.db.models import Sum

from .models import StockRecord, StockAdjustment, StockLoan, StockLoanLine


class InsufficientStockError(Exception):
    pass


def _available_stock(item, department, batch_number=None):
    filt = {'item': item, 'current_location': department, 'quantity__gt': 0}
    if batch_number:
        filt['batch_number__icontains'] = batch_number
    return (
        StockRecord.objects.filter(**filt).aggregate(total=Sum('quantity'))['total'] or 0
    )


def issue_loan_lines(loan, item, quantity, user, batch_number=None):
    """
    Deduct stock (FEFO) and create StockLoanLine + StockAdjustment (Loan Out) per batch.
    Returns list of created lines.
    """
    if quantity <= 0:
        return []

    available = _available_stock(item, loan.source_department, batch_number)
    if available < quantity:
        raise InsufficientStockError(
            f'Insufficient stock for {item.name} at {loan.source_department.name}. '
            f'Requested: {quantity}, available: {available}.'
        )

    stock_filter = {
        'item': item,
        'current_location': loan.source_department,
        'quantity__gt': 0,
    }
    if batch_number:
        stock_filter['batch_number__icontains'] = batch_number

    source_records = (
        StockRecord.objects.filter(**stock_filter)
        .order_by('expiry_date', 'received_date')
        .select_for_update()
    )

    created_lines = []
    remaining = quantity
    institution_name = loan.institution.name
    expected = loan.expected_return_date
    expected_txt = f' — expected return {expected}' if expected else ''

    for record in source_records:
        if remaining <= 0:
            break

        take = min(record.quantity, remaining)
        record.quantity -= take
        record.save(update_fields=['quantity'])

        line = StockLoanLine.objects.create(
            loan=loan,
            item=item,
            batch_number=record.batch_number,
            quantity_lent=take,
            expiry_date=record.expiry_date,
            purchase_price=record.purchase_price,
            supplier=record.supplier,
        )

        StockAdjustment.objects.create(
            item=item,
            quantity=-take,
            adjustment_type='Loan Out',
            reason=(
                f'Loan #{loan.id} to {institution_name}{expected_txt} '
                f'(batch {record.batch_number})'
            ),
            adjusted_by=user,
            adjusted_from=loan.source_department,
            stock_loan_line=line,
        )

        created_lines.append(line)
        remaining -= take

    if remaining > 0:
        raise InsufficientStockError(
            f'Could not fulfill full quantity for {item.name} (short {remaining}).'
        )

    return created_lines


def return_loan_line(line, quantity, user):
    """Return stock to the loan source department."""
    if quantity <= 0:
        raise ValueError('Return quantity must be positive.')

    outstanding = line.outstanding
    if quantity > outstanding:
        raise ValueError(f'Cannot return {quantity}; only {outstanding} outstanding.')

    loan = line.loan
    department = loan.source_department

    dest_record, _created = StockRecord.objects.get_or_create(
        item=line.item,
        current_location=department,
        batch_number=line.batch_number,
        defaults={
            'quantity': 0,
            'expiry_date': line.expiry_date,
            'supplier': line.supplier,
            'purchase_price': line.purchase_price,
        },
    )
    dest_record.quantity += quantity
    dest_record.save(update_fields=['quantity'])

    line.quantity_returned += quantity
    line.save(update_fields=['quantity_returned'])

    StockAdjustment.objects.create(
        item=line.item,
        quantity=quantity,
        adjustment_type='Loan Return',
        reason=(
            f'Return against Loan #{loan.id} from {loan.institution.name} '
            f'(batch {line.batch_number})'
        ),
        adjusted_by=user,
        adjusted_from=department,
        stock_loan_line=line,
    )

    loan.refresh_status()
    return line


def write_off_loan_line(line, quantity, user, reason=''):
    """Mark units as not returned; stock was already deducted on loan out."""
    if quantity <= 0:
        raise ValueError('Write-off quantity must be positive.')

    outstanding = line.outstanding
    if quantity > outstanding:
        raise ValueError(f'Cannot write off {quantity}; only {outstanding} outstanding.')

    loan = line.loan
    line.quantity_written_off += quantity
    line.save(update_fields=['quantity_written_off'])

    detail = reason.strip() or 'Not returned by borrowing institution'
    StockAdjustment.objects.create(
        item=line.item,
        quantity=0,
        adjustment_type='Loan Write-off',
        reason=(
            f'Write-off {quantity} unit(s) — Loan #{loan.id} to {loan.institution.name}, '
            f'batch {line.batch_number}. {detail} (stock already deducted on loan out).'
        ),
        adjusted_by=user,
        adjusted_from=loan.source_department,
        stock_loan_line=line,
    )

    loan.refresh_status()
    return line


def create_stock_loan(institution, source_department, user, line_items, expected_return_date=None, notes=''):
    """
    line_items: list of dicts with keys item (InventoryItem), quantity, optional batch_number
    """
    from .models import InventoryItem

    with transaction.atomic():
        loan = StockLoan.objects.create(
            institution=institution,
            source_department=source_department,
            expected_return_date=expected_return_date,
            notes=notes,
            issued_by=user,
            status='Open',
        )

        for entry in line_items:
            item = entry['item']
            if isinstance(item, int):
                item = InventoryItem.objects.get(pk=item)
            qty = int(entry['quantity'])
            batch_number = entry.get('batch_number') or None
            issue_loan_lines(loan, item, qty, user, batch_number=batch_number)

        loan.refresh_status()
    return loan
