from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from .models import PayrollRun, StaffPayroll, StaffSalary


def _money(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def get_or_create_payroll_run(year, month):
    run, _ = PayrollRun.objects.get_or_create(
        period_year=year,
        period_month=month,
        defaults={'status': 'Draft'},
    )
    return run


def calculate_staff_payroll(user, year, month, *, adjustment=Decimal('0')):
    """Compute payroll line from salary profile (full monthly pay, no attendance deductions)."""
    profile = StaffSalary.objects.filter(user=user).first()
    if not profile:
        return None

    basic = profile.basic_salary
    allowance = profile.allowance
    gross = basic + allowance
    net = _money(gross + Decimal(adjustment))

    return {
        'basic_salary': basic,
        'allowance': allowance,
        'gross_pay': gross,
        'working_days': 0,
        'days_present': 0,
        'days_absent': 0,
        'days_on_leave': 0,
        'deductible_days': 0,
        'deduction': Decimal('0'),
        'adjustment': Decimal(adjustment),
        'net_pay': max(Decimal('0'), net),
    }


def generate_staff_payroll(user, year, month, *, adjustment=Decimal('0'), notes=''):
    """Create or refresh draft payroll line for a staff member."""
    data = calculate_staff_payroll(user, year, month, adjustment=adjustment)
    if not data:
        return None

    run = get_or_create_payroll_run(year, month)
    payroll, created = StaffPayroll.objects.get_or_create(
        payroll_run=run,
        user=user,
        defaults={**data, 'notes': notes, 'status': 'Draft'},
    )
    if not created:
        if payroll.status not in ('Draft',):
            return payroll
        for key, value in data.items():
            setattr(payroll, key, value)
        payroll.notes = notes or payroll.notes
        payroll.save()
    return payroll


def sync_payroll_from_salary(user, year, month):
    """
    Refresh the draft invoice for this month from the current salary profile.
    Skips finalized/paid invoices. Returns (payroll, updated_bool).
    """
    profile = StaffSalary.objects.filter(user=user).first()
    if not profile:
        return None, False

    existing = StaffPayroll.objects.filter(
        user=user,
        payroll_run__period_year=year,
        payroll_run__period_month=month,
    ).first()
    if existing and existing.status != 'Draft':
        return existing, False

    adjustment = existing.adjustment if existing else Decimal('0')
    notes = existing.notes if existing else ''
    payroll = generate_staff_payroll(user, year, month, adjustment=adjustment, notes=notes)
    return payroll, True


def generate_all_staff_payroll(year, month, user_adjustments=None):
    """Create or refresh draft invoices for every staff member with a salary profile."""
    from users.models import User

    user_adjustments = user_adjustments or {}
    updated = 0
    skipped = 0
    for user in User.objects.filter(is_active=True).exclude(role='Admin'):
        if not StaffSalary.objects.filter(user=user).exists():
            continue
        existing = StaffPayroll.objects.filter(
            user=user,
            payroll_run__period_year=year,
            payroll_run__period_month=month,
        ).first()
        if existing and existing.status != 'Draft':
            skipped += 1
            continue

        adj_data = user_adjustments.get(user.pk, {})
        if adj_data:
            adjustment = Decimal(str(adj_data.get('adjustment', 0)))
            notes = adj_data.get('notes', '')
        elif existing:
            adjustment = existing.adjustment
            notes = existing.notes
        else:
            adjustment = Decimal('0')
            notes = ''

        payroll = generate_staff_payroll(user, year, month, adjustment=adjustment, notes=notes)
        if payroll:
            updated += 1
    return updated, skipped


def preview_all_staff_payroll(year, month):
    """Build summary rows for bulk month-end payroll without saving."""
    from datetime import date
    from users.models import User

    period_label = date(year, month, 1).strftime('%B %Y')
    rows = []
    totals = {
        'basic': Decimal('0'),
        'allowance': Decimal('0'),
        'gross': Decimal('0'),
        'adjustment': Decimal('0'),
        'net': Decimal('0'),
    }
    editable_count = 0
    skipped_count = 0

    users = User.objects.filter(is_active=True).exclude(role='Admin').order_by('first_name', 'last_name')
    for user in users:
        profile = StaffSalary.objects.filter(user=user).first()
        if not profile:
            continue

        existing = StaffPayroll.objects.filter(
            user=user,
            payroll_run__period_year=year,
            payroll_run__period_month=month,
        ).first()

        editable = not (existing and existing.status != 'Draft')
        if existing and existing.status != 'Draft':
            skipped_count += 1
            adjustment = existing.adjustment
            notes = existing.notes
            data = {
                'basic_salary': existing.basic_salary,
                'allowance': existing.allowance,
                'gross_pay': existing.gross_pay,
                'adjustment': adjustment,
                'net_pay': existing.net_pay,
            }
            status = existing.status
        else:
            editable_count += 1
            adjustment = existing.adjustment if existing else Decimal('0')
            notes = existing.notes if existing else ''
            data = calculate_staff_payroll(user, year, month, adjustment=adjustment)
            status = existing.status if existing else 'New'

        rows.append({
            'user_id': user.pk,
            'name': user.get_full_name(),
            'role': user.role,
            'basic': str(data['basic_salary']),
            'allowance': str(data['allowance']),
            'gross': str(data['gross_pay']),
            'adjustment': str(adjustment),
            'net_pay': str(data['net_pay']),
            'notes': notes,
            'editable': editable,
            'status': status,
        })

        if editable:
            totals['basic'] += data['basic_salary']
            totals['allowance'] += data['allowance']
            totals['gross'] += data['gross_pay']
            totals['adjustment'] += adjustment
            totals['net'] += data['net_pay']

    return {
        'period_year': year,
        'period_month': month,
        'period_label': period_label,
        'rows': rows,
        'summary': {
            'staff_count': len(rows),
            'editable_count': editable_count,
            'skipped_count': skipped_count,
            'total_basic': str(totals['basic']),
            'total_allowance': str(totals['allowance']),
            'total_gross': str(totals['gross']),
            'total_adjustment': str(totals['adjustment']),
            'total_net': str(totals['net']),
        },
    }


def finalize_staff_payroll(payroll):
    if payroll.status != 'Draft':
        return payroll
    payroll.status = 'Finalized'
    payroll.finalized_at = timezone.now()
    payroll.save(update_fields=['status', 'finalized_at', 'updated_at'])
    return payroll


def refresh_payroll_run_status(run):
    """Sync PayrollRun.status from its staff lines."""
    lines = run.lines.all()
    if not lines.exists():
        run.status = 'Draft'
        run.save(update_fields=['status'])
        return run
    if not lines.exclude(status='Paid').exists():
        run.status = 'Paid'
        run.save(update_fields=['status'])
        return run
    if lines.filter(status__in=('Finalized', 'Partial', 'Paid')).exists() and run.finalized_at:
        if run.status != 'Paid':
            run.status = 'Finalized'
            run.save(update_fields=['status'])
    return run


def payroll_run_report(year, month):
    """Summary and line queryset for a monthly payroll run."""
    from django.db.models import Sum
    from users.models import User

    run = PayrollRun.objects.filter(
        period_year=year, period_month=month,
    ).select_related('finalized_by').first()
    lines = StaffPayroll.objects.filter(
        payroll_run__period_year=year,
        payroll_run__period_month=month,
    ).select_related('user', 'payroll_run').order_by('user__first_name', 'user__last_name')

    totals = lines.aggregate(
        total_basic=Sum('basic_salary'),
        total_allowance=Sum('allowance'),
        total_gross=Sum('gross_pay'),
        total_adjustment=Sum('adjustment'),
        total_net=Sum('net_pay'),
        total_paid=Sum('paid_amount'),
    )
    for key in totals:
        totals[key] = totals[key] or Decimal('0')
    totals['total_balance'] = totals['total_net'] - totals['total_paid']

    status_counts = {
        'draft': lines.filter(status='Draft').count(),
        'finalized': lines.filter(status='Finalized').count(),
        'partial': lines.filter(status='Partial').count(),
        'paid': lines.filter(status='Paid').count(),
        'total': lines.count(),
    }
    staff_with_salary = StaffSalary.objects.filter(
        user__is_active=True,
    ).exclude(user__role='Admin').count()
    status_counts['missing'] = max(0, staff_with_salary - status_counts['total'])

    return run, lines, totals, status_counts


def finalize_payroll_run(year, month, *, finalized_by=None):
    """
    Lock all draft staff invoices for the month and mark the run finalized.
    Returns (run, finalized_count, skipped_draft_count).
    """
    run = get_or_create_payroll_run(year, month)
    if run.status == 'Paid':
        return run, 0, 0

    draft_lines = list(run.lines.filter(status='Draft'))
    finalized_count = 0
    for payroll in draft_lines:
        finalize_staff_payroll(payroll)
        finalized_count += 1

    if finalized_count or run.lines.filter(status__in=('Finalized', 'Partial', 'Paid')).exists():
        run.status = 'Finalized'
        run.finalized_at = timezone.now()
        run.finalized_by = finalized_by
        run.save(update_fields=['status', 'finalized_at', 'finalized_by'])

    refresh_payroll_run_status(run)
    return run, finalized_count, len(draft_lines) - finalized_count


def record_payroll_payment(payroll, amount, payment_method, reference='', notes='', recorded_by=None):
    amount = _money(amount)
    if amount <= 0:
        raise ValueError('Payment amount must be positive.')
    if payroll.status not in ('Finalized', 'Partial'):
        raise ValueError('Payroll must be finalized before payment.')
    if amount > payroll.balance_due:
        raise ValueError('Payment exceeds balance due.')

    payment = payroll.payments.create(
        amount=amount,
        payment_method=payment_method,
        reference=reference,
        notes=notes,
        recorded_by=recorded_by,
    )
    payroll.sync_paid_amount()

    run = payroll.payroll_run
    refresh_payroll_run_status(run)

    return payment
