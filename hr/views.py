from decimal import Decimal

from datetime import datetime
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.http import JsonResponse

from users.models import User


def _parse_year_month(value):
    if value and '-' in value:
        try:
            year_str, month_str = value.split('-', 1)
            year, month = int(year_str), int(month_str)
            if 1 <= month <= 12:
                return year, month
        except ValueError:
            pass
    return None, None


def _payroll_period_gte(year, month):
    return Q(payroll_run__period_year__gt=year) | Q(
        payroll_run__period_year=year,
        payroll_run__period_month__gte=month,
    )


def _payroll_period_lte(year, month):
    return Q(payroll_run__period_year__lt=year) | Q(
        payroll_run__period_year=year,
        payroll_run__period_month__lte=month,
    )


def _salary_edit_query_params(request, year, month):
    params = {'year': year, 'month': month}
    history_from = (request.POST.get('history_from') or request.GET.get('history_from', '')).strip()
    history_to = (request.POST.get('history_to') or request.GET.get('history_to', '')).strip()
    if history_from:
        params['history_from'] = history_from
    if history_to:
        params['history_to'] = history_to
    return params


def _salary_edit_url(request, user_id, year, month):
    return f"{reverse('hr:salary_edit', args=[user_id])}?{urlencode(_salary_edit_query_params(request, year, month))}"


from .attendance_service import (
    attendance_logs_for_user_day,
    attendance_metrics_for_date,
    build_user_attendance_calendar,
    compute_attendance_day,
    process_attendance_for_date,
)
from .forms import (
    AttendanceDeviceForm,
    LeaveRequestForm,
    LeaveTypeForm,
    ManualAttendanceForm,
    PublicHolidayForm,
    StaffAttendanceProfileForm,
    StaffLeaveEntitlementForm,
    StaffOffDayForm,
    StaffPayrollPaymentForm,
    StaffSalaryForm,
)
from .models import (
    AttendanceDay,
    AttendanceDevice,
    AttendanceLog,
    LeaveRequest,
    LeaveType,
    PayrollRun,
    PublicHoliday,
    StaffAttendanceProfile,
    StaffLeaveEntitlement,
    StaffOffDay,
    StaffPayroll,
    StaffPayrollPayment,
    StaffSalary,
)
from .leave_utils import (
    get_leave_entitlement,
    leave_balance_for_user,
    leave_days_by_year,
    validate_leave_balance,
)
from .permissions import (
    can_edit_salaries,
    can_manage_attendance,
    can_manage_hr_settings,
    can_view_salaries,
    can_write_hr,
    hr_access_required,
    hr_read_required,
    hr_settings_required,
    hr_write_required,
    is_staff_self_service,
    user_may_cancel_leave,
    user_may_edit_leave,
    user_may_view_attendance_user,
    user_may_view_leave,
    user_may_view_off_day,
)
from .pagination import paginate_queryset
from .payroll_service import (
    finalize_payroll_run,
    finalize_staff_payroll,
    generate_all_staff_payroll,
    generate_staff_payroll,
    payroll_run_report,
    preview_all_staff_payroll,
    record_payroll_payment,
    sync_payroll_from_salary,
)
from .zkteco_sync import sync_and_process, sync_device


@hr_access_required
def hr_dashboard(request):
    today = timezone.localdate()
    if is_staff_self_service(request.user):
        user = request.user
        own_leave = LeaveRequest.objects.filter(user=user).select_related('leave_type').order_by('-start_date')[:5]
        weeks, att_summary = build_user_attendance_calendar(user, today.year, today.month)
        return render(request, 'hr/dashboard.html', {
            'is_self_dashboard': True,
            'own_leave': own_leave,
            'own_pending': LeaveRequest.objects.filter(user=user, status='Pending').count(),
            'own_approved': LeaveRequest.objects.filter(user=user, status='Approved').count(),
            'att_summary': att_summary,
            'balance_rows': leave_balance_for_user(user, today.year),
            'today': today,
        })

    active_staff = User.objects.filter(is_active=True).exclude(role='Admin')
    salary_profiles = StaffSalary.objects.select_related('user')
    with_salary = salary_profiles.count()
    without_salary = active_staff.count() - with_salary
    payroll_total = salary_profiles.aggregate(
        total=Sum('basic_salary'),
        allowance=Sum('allowance'),
    )
    gross = (payroll_total['total'] or Decimal('0')) + (payroll_total['allowance'] or Decimal('0'))

    pending_leave = LeaveRequest.objects.filter(status='Pending').count()
    today = timezone.localdate()
    upcoming_off = (
        PublicHoliday.objects.filter(date__gte=today).count()
        + StaffOffDay.objects.filter(date__gte=today, status='Approved').count()
    )
    att_metrics, _ = attendance_metrics_for_date(today)

    return render(request, 'hr/dashboard.html', {
        'active_staff_count': active_staff.count(),
        'with_salary_count': with_salary,
        'without_salary_count': max(0, without_salary),
        'monthly_payroll_gross': gross,
        'pending_leave_count': pending_leave,
        'upcoming_off_count': upcoming_off,
        'attendance_metrics': att_metrics,
        'recent_salaries': salary_profiles.order_by('-updated_at')[:5],
        'recent_leave': LeaveRequest.objects.select_related('user', 'leave_type').order_by('-requested_at')[:5],
        'today': today,
    })


@hr_access_required
def salary_list(request):
    if not can_view_salaries(request.user):
        raise PermissionDenied
    q = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '')
    today = timezone.localdate()

    if request.method == 'POST' and request.POST.get('action') == 'generate_all_payroll':
        if not can_edit_salaries(request.user):
            raise PermissionDenied
        period = request.POST.get('period', '')
        if period and '-' in period:
            year, month = map(int, period.split('-'))
        else:
            year, month = today.year, today.month

        user_adjustments = {}
        for key, value in request.POST.items():
            if key.startswith('adjustment_'):
                try:
                    user_id = int(key.replace('adjustment_', ''))
                except ValueError:
                    continue
                user_adjustments.setdefault(user_id, {})['adjustment'] = value
            elif key.startswith('notes_'):
                try:
                    user_id = int(key.replace('notes_', ''))
                except ValueError:
                    continue
                user_adjustments.setdefault(user_id, {})['notes'] = value.strip()

        updated, skipped = generate_all_staff_payroll(year, month, user_adjustments=user_adjustments)
        skipped_msg = ''
        if skipped:
            skipped_msg = f' {skipped} had finalized invoices and were skipped.'
        messages.success(
            request,
            f'Month-end invoices updated for {updated} staff.{skipped_msg}',
        )
        return redirect('hr:salary_list')

    staff = User.objects.filter(is_active=True).exclude(role='Admin').select_related('salary_profile').order_by('first_name', 'last_name')
    if q:
        staff = staff.filter(
            Q(id_number__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )
    if role_filter:
        staff = staff.filter(role=role_filter)

    staff_page = paginate_queryset(request, staff)

    return render(request, 'hr/salary_list.html', {
        'staff_list': staff_page,
        'page_obj': staff_page,
        'q': q,
        'role_filter': role_filter,
        'roles': User.roles,
        'today': today,
    })


@hr_write_required
@require_GET
def bulk_payroll_preview(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid period.'}, status=400)
    if not 1 <= month <= 12:
        return JsonResponse({'error': 'Invalid month.'}, status=400)

    return JsonResponse(preview_all_staff_payroll(year, month))


@hr_access_required
def payroll_run_detail(request):
    if not can_view_salaries(request.user):
        raise PermissionDenied
    today = timezone.localdate()
    month_str = request.GET.get('month', '') or request.POST.get('period', '')
    if month_str and '-' in month_str:
        parts = month_str.split('-')
        payroll_year = int(parts[0])
        payroll_month = int(parts[1])
    else:
        payroll_year = int(request.GET.get('year', today.year))
        try:
            payroll_month = int(request.GET.get('month') or today.month)
        except (TypeError, ValueError):
            payroll_month = today.month

    if request.method == 'POST' and request.POST.get('action') == 'finalize_run':
        if not can_edit_salaries(request.user):
            raise PermissionDenied
        run, finalized_count, _ = finalize_payroll_run(
            payroll_year, payroll_month, finalized_by=request.user,
        )
        if finalized_count:
            messages.success(
                request,
                f'Locked {finalized_count} draft invoice(s) for {run.period_label}.',
            )
        else:
            messages.info(request, f'No draft invoices to lock for {run.period_label}.')
        return redirect(f"{reverse('hr:payroll_run_detail')}?year={payroll_year}&month={payroll_month}")

    run, lines, totals, status_counts = payroll_run_report(payroll_year, payroll_month)
    lines_page = paginate_queryset(request, lines, per_page=50)

    from datetime import date as date_cls
    month_label = date_cls(payroll_year, payroll_month, 1).strftime('%B %Y')

    return render(request, 'hr/payroll_run_detail.html', {
        'run': run,
        'lines': lines_page,
        'page_obj': lines_page,
        'totals': totals,
        'status_counts': status_counts,
        'payroll_year': payroll_year,
        'payroll_month': payroll_month,
        'month_label': month_label,
        'today': today,
        'can_edit': can_edit_salaries(request.user),
    })


@hr_access_required
def salary_edit(request, user_id):
    if not can_view_salaries(request.user):
        raise PermissionDenied
    staff_user = get_object_or_404(User, pk=user_id, is_active=True)
    profile = StaffSalary.objects.filter(user=staff_user).first()
    is_create = profile is None
    today = timezone.localdate()
    month_str = request.GET.get('month', '')
    if month_str and '-' in month_str:
        parts = month_str.split('-')
        payroll_year = int(parts[0])
        payroll_month = int(parts[1])
    else:
        payroll_year = int(request.GET.get('year', today.year))
        payroll_month = int(month_str) if month_str.isdigit() else today.month

    if request.method == 'POST':
        if not can_edit_salaries(request.user):
            raise PermissionDenied
        action = request.POST.get('action', 'save_salary')

        if action == 'save_salary':
            form = StaffSalaryForm(request.POST, instance=profile)
            if form.is_valid():
                salary = form.save(commit=False)
                salary.user = staff_user
                salary.updated_by = request.user
                salary.save()
                payroll, synced = sync_payroll_from_salary(staff_user, payroll_year, payroll_month)
                if synced and payroll:
                    messages.success(
                        request,
                        f'Salary saved and {payroll.payroll_run.period_label} invoice updated '
                        f'(balance KES {payroll.balance_due:,.2f}).',
                    )
                elif payroll and payroll.status != 'Draft':
                    messages.success(
                        request,
                        f'Salary saved. {payroll.payroll_run.period_label} invoice is already '
                        f'{payroll.status.lower()} and was not changed.',
                    )
                else:
                    messages.success(request, f'Salary saved for {staff_user.get_full_name()}.')
                return redirect(_salary_edit_url(request, user_id, payroll_year, payroll_month))
        elif action == 'generate_payroll':
            if not profile:
                messages.error(request, 'Set a salary profile before generating payroll.')
            else:
                adjustment = request.POST.get('adjustment', '0') or '0'
                notes = request.POST.get('payroll_notes', '').strip()
                try:
                    adj = Decimal(adjustment)
                except Exception:
                    adj = Decimal('0')
                year = int(request.POST.get('period_year', today.year))
                month = int(request.POST.get('period_month', today.month))
                payroll = generate_staff_payroll(
                    staff_user, year, month, adjustment=adj, notes=notes,
                )
                if payroll:
                    messages.success(request, f'Payroll updated for {payroll.payroll_run.period_label}.')
                else:
                    messages.error(request, 'Could not generate payroll.')
            return redirect(_salary_edit_url(request, user_id, year, month))
        elif action == 'finalize_payroll':
            payroll = get_object_or_404(StaffPayroll, pk=request.POST.get('payroll_id'), user=staff_user)
            finalize_staff_payroll(payroll)
            messages.success(request, f'Balance finalized for {payroll.payroll_run.period_label}.')
            return redirect(_salary_edit_url(
                request, user_id, payroll.payroll_run.period_year, payroll.payroll_run.period_month,
            ))
        elif action == 'record_payment':
            payroll = get_object_or_404(StaffPayroll, pk=request.POST.get('payroll_id'), user=staff_user)
            pay_form = StaffPayrollPaymentForm(request.POST)
            if pay_form.is_valid():
                try:
                    record_payroll_payment(
                        payroll,
                        pay_form.cleaned_data['amount'],
                        pay_form.cleaned_data['payment_method'],
                        reference=pay_form.cleaned_data.get('reference', ''),
                        notes=pay_form.cleaned_data.get('notes', ''),
                        recorded_by=request.user,
                    )
                    messages.success(request, f'Payment recorded for {payroll.payroll_run.period_label}.')
                except ValueError as exc:
                    messages.error(request, str(exc))
            else:
                messages.error(request, pay_form.errors.as_text())
            return redirect(_salary_edit_url(
                request, user_id, payroll.payroll_run.period_year, payroll.payroll_run.period_month,
            ))

    initial = {'effective_from': timezone.localdate()}
    form = StaffSalaryForm(instance=profile, initial=initial if is_create else None)

    payrolls_qs = StaffPayroll.objects.filter(user=staff_user).select_related('payroll_run').prefetch_related('payments')
    for p in payrolls_qs:
        if p.payments.exists():
            p.sync_paid_amount()
    current_payroll = payrolls_qs.filter(
        payroll_run__period_year=payroll_year,
        payroll_run__period_month=payroll_month,
    ).first()
    payment_form = StaffPayrollPaymentForm()

    history_from = request.GET.get('history_from', '').strip()
    history_to = request.GET.get('history_to', '').strip()
    history_payrolls = payrolls_qs.order_by('-payroll_run__period_year', '-payroll_run__period_month')
    from_year, from_month = _parse_year_month(history_from)
    to_year, to_month = _parse_year_month(history_to)
    if from_year and from_month:
        history_payrolls = history_payrolls.filter(_payroll_period_gte(from_year, from_month))
    if to_year and to_month:
        history_payrolls = history_payrolls.filter(_payroll_period_lte(to_year, to_month))

    entitlements = StaffLeaveEntitlement.objects.filter(user=staff_user).select_related('leave_type')
    entitlement_map = {item.leave_type_id: item for item in entitlements}
    entitlement_rows = []
    for leave_type in LeaveType.objects.filter(is_active=True):
        override = entitlement_map.get(leave_type.pk)
        entitlement_rows.append({
            'leave_type': leave_type,
            'override': override,
            'effective_days': get_leave_entitlement(staff_user, leave_type),
        })

    return render(request, 'hr/salary_form.html', {
        'form': form,
        'staff_user': staff_user,
        'is_create': is_create,
        'payrolls': history_payrolls,
        'history_from': history_from,
        'history_to': history_to,
        'current_payroll': current_payroll,
        'payroll_year': payroll_year,
        'payroll_month': payroll_month,
        'payment_form': payment_form,
        'today': today,
        'read_only': not can_edit_salaries(request.user),
        'entitlement_rows': entitlement_rows,
    })


def _action_redirect(request, detail_name, pk, list_name):
    if request.POST.get('next') == 'list':
        return redirect(list_name)
    return redirect(detail_name, pk=pk)


def _recalc_leave_days(leave):
    """Recompute AttendanceDay for every date covered by a leave request."""
    from datetime import timedelta
    day = leave.start_date
    while day <= leave.end_date:
        compute_attendance_day(leave.user, day, force=True)
        day += timedelta(days=1)


@hr_access_required
def leave_list(request):
    status_filter = request.GET.get('status', '')
    q = request.GET.get('q', '').strip()
    leave_type_id = request.GET.get('leave_type', '')

    leaves = LeaveRequest.objects.select_related('user', 'leave_type', 'reviewed_by')
    metrics_base = LeaveRequest.objects.all()
    if is_staff_self_service(request.user):
        leaves = leaves.filter(user=request.user)
        metrics_base = metrics_base.filter(user=request.user)
    if status_filter:
        leaves = leaves.filter(status=status_filter)
    if leave_type_id:
        leaves = leaves.filter(leave_type_id=leave_type_id)
    if q:
        leaves = leaves.filter(
            Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__id_number__icontains=q)
        )

    metrics = {
        'pending': metrics_base.filter(status='Pending').count(),
        'approved': metrics_base.filter(status='Approved').count(),
        'rejected': metrics_base.filter(status='Rejected').count(),
        'total': metrics_base.count(),
    }

    leaves_page = paginate_queryset(request, leaves)

    return render(request, 'hr/leave_list.html', {
        'leaves': leaves_page,
        'page_obj': leaves_page,
        'status_filter': status_filter,
        'leave_type_filter': leave_type_id,
        'q': q,
        'leave_types': LeaveType.objects.filter(is_active=True),
        'metrics': metrics,
        'is_self_view': is_staff_self_service(request.user),
    })


@hr_access_required
def leave_detail(request, pk):
    leave = get_object_or_404(
        LeaveRequest.objects.select_related('user', 'leave_type', 'reviewed_by'),
        pk=pk,
    )
    if not user_may_view_leave(request.user, leave):
        raise PermissionDenied
    today = timezone.localdate()
    other_leaves = LeaveRequest.objects.filter(user=leave.user).exclude(pk=leave.pk).select_related('leave_type')[:5]
    days_by_year = leave_days_by_year(leave.start_date, leave.end_date)
    balance_years = []
    for year in sorted(days_by_year):
        balance_years.append({
            'year': year,
            'request_days': days_by_year[year],
            'rows': leave_balance_for_user(leave.user, year),
        })
    approval_blocked = False
    if leave.status == 'Pending':
        approval_blocked = bool(validate_leave_balance(
            leave.user,
            leave.leave_type,
            leave.start_date,
            leave.end_date,
            exclude_pk=leave.pk,
        ))
    return render(request, 'hr/leave_detail.html', {
        'leave': leave,
        'other_leaves': other_leaves,
        'today': today,
        'balance_years': balance_years,
        'approval_blocked': approval_blocked,
        'can_edit': user_may_edit_leave(request.user, leave),
        'can_approve': can_write_hr(request.user),
    })


@hr_access_required
def leave_create(request):
    restrict_user = request.user if is_staff_self_service(request.user) else None
    if request.method == 'POST':
        form = LeaveRequestForm(request.POST, restrict_user=restrict_user)
        if form.is_valid():
            leave = form.save()
            messages.success(request, f'Leave request recorded for {leave.user.get_full_name()}.')
            return redirect('hr:leave_detail', pk=leave.pk)
    else:
        form = LeaveRequestForm(restrict_user=restrict_user)
    return render(request, 'hr/leave_form.html', {
        'form': form,
        'is_self_view': restrict_user is not None,
    })


@hr_access_required
def leave_edit(request, pk):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if not user_may_edit_leave(request.user, leave):
        raise PermissionDenied
    restrict_user = request.user if is_staff_self_service(request.user) else None
    if request.method == 'POST':
        form = LeaveRequestForm(request.POST, instance=leave, restrict_user=restrict_user)
        if form.is_valid():
            leave = form.save()
            _recalc_leave_days(leave)
            messages.success(request, f'Leave request updated for {leave.user.get_full_name()}.')
            return redirect('hr:leave_detail', pk=leave.pk)
    else:
        form = LeaveRequestForm(instance=leave, restrict_user=restrict_user)
    return render(request, 'hr/leave_form.html', {
        'form': form,
        'leave': leave,
        'is_edit': True,
        'is_self_view': restrict_user is not None,
    })


@hr_access_required
@require_GET
def leave_balance_json(request):
    user_id = request.GET.get('user')
    leave_type_id = request.GET.get('leave_type')
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')

    if not all([user_id, leave_type_id, start_str, end_str]):
        return JsonResponse({'error': 'Missing parameters.'}, status=400)

    try:
        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format.'}, status=400)

    if end_date < start_date:
        return JsonResponse({'error': 'End date must be on or after start date.'}, status=400)

    user = get_object_or_404(User, pk=user_id, is_active=True)
    if is_staff_self_service(request.user) and user.pk != request.user.pk:
        return JsonResponse({'error': 'Forbidden.'}, status=403)
    leave_type = get_object_or_404(LeaveType, pk=leave_type_id, is_active=True)

    years = {}
    errors = []
    for year, requested_days in leave_days_by_year(start_date, end_date).items():
        rows = leave_balance_for_user(user, year)
        type_row = next((row for row in rows if row['leave_type_id'] == leave_type.pk), None)
        if not type_row:
            continue
        would_exceed = requested_days > type_row['remaining']
        years[str(year)] = {
            'requested': requested_days,
            'entitlement': type_row['entitlement'],
            'used': type_row['used'],
            'pending': type_row['pending'],
            'remaining': type_row['remaining'],
            'would_exceed': would_exceed,
        }
        if would_exceed:
            errors.append(
                f'{leave_type.name} for {year}: requesting {requested_days} day(s) but only '
                f'{type_row["remaining"]} remain.'
            )

    return JsonResponse({
        'ok': not errors,
        'years': years,
        'errors': errors,
    })


@hr_access_required
def leave_approve(request, pk):
    if request.method != 'POST':
        return redirect('hr:leave_detail', pk=pk)
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if leave.status != 'Pending':
        messages.error(request, 'Only pending requests can be approved.')
        return _action_redirect(request, 'hr:leave_detail', pk, 'hr:leave_list')
    if not can_write_hr(request.user):
        raise PermissionDenied
    balance_errors = validate_leave_balance(
        leave.user,
        leave.leave_type,
        leave.start_date,
        leave.end_date,
        exclude_pk=leave.pk,
    )
    if balance_errors:
        messages.error(request, balance_errors[0])
        return _action_redirect(request, 'hr:leave_detail', pk, 'hr:leave_list')
    leave.status = 'Approved'
    leave.reviewed_by = request.user
    leave.reviewed_at = timezone.now()
    leave.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    _recalc_leave_days(leave)
    messages.success(request, f'Leave approved for {leave.user.get_full_name()}.')
    return _action_redirect(request, 'hr:leave_detail', pk, 'hr:leave_list')


@hr_access_required
def leave_reject(request, pk):
    if request.method != 'POST':
        return redirect('hr:leave_detail', pk=pk)
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if leave.status != 'Pending':
        messages.error(request, 'Only pending requests can be rejected.')
        return _action_redirect(request, 'hr:leave_detail', pk, 'hr:leave_list')
    if not can_write_hr(request.user):
        raise PermissionDenied
    notes = request.POST.get('review_notes', '').strip()
    leave.status = 'Rejected'
    leave.reviewed_by = request.user
    leave.reviewed_at = timezone.now()
    leave.review_notes = notes
    leave.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes'])
    _recalc_leave_days(leave)
    messages.success(request, f'Leave rejected for {leave.user.get_full_name()}.')
    return _action_redirect(request, 'hr:leave_detail', pk, 'hr:leave_list')


@hr_access_required
def leave_cancel(request, pk):
    if request.method != 'POST':
        return redirect('hr:leave_detail', pk=pk)
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if not user_may_cancel_leave(request.user, leave):
        raise PermissionDenied
    if leave.status not in ('Pending', 'Approved'):
        messages.error(request, 'This leave cannot be cancelled.')
        return _action_redirect(request, 'hr:leave_detail', pk, 'hr:leave_list')
    leave.status = 'Cancelled'
    leave.reviewed_by = request.user
    leave.reviewed_at = timezone.now()
    leave.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    _recalc_leave_days(leave)
    messages.success(request, f'Leave cancelled for {leave.user.get_full_name()}.')
    return _action_redirect(request, 'hr:leave_detail', pk, 'hr:leave_list')


@hr_access_required
def off_day_list(request):
    if is_staff_self_service(request.user):
        return redirect('hr:off_day_queue')
    return _render_off_days(request, default_tab='holidays')


@hr_access_required
def off_day_queue(request):
    return _render_off_days(request, default_tab='staff')


def _render_off_days(request, default_tab):
    today = timezone.localdate()
    tab = request.GET.get('tab', default_tab)
    upcoming_only = request.GET.get('upcoming', '') == '1'
    status_filter = request.GET.get('status', '')

    holidays = PublicHoliday.objects.all()
    staff_offs = StaffOffDay.objects.select_related('user', 'created_by', 'reviewed_by')
    if is_staff_self_service(request.user):
        staff_offs = staff_offs.filter(user=request.user)
    if upcoming_only:
        holidays = holidays.filter(date__gte=today)
        staff_offs = staff_offs.filter(date__gte=today)
    if status_filter:
        staff_offs = staff_offs.filter(status=status_filter)

    off_metrics = {
        'pending': StaffOffDay.objects.filter(status='Pending').count(),
        'approved': StaffOffDay.objects.filter(status='Approved').count(),
        'rejected': StaffOffDay.objects.filter(status='Rejected').count(),
        'total': StaffOffDay.objects.count(),
    }

    holidays_page = paginate_queryset(request, holidays, page_param='hpage')
    staff_offs_page = paginate_queryset(request, staff_offs, page_param='page')

    return render(request, 'hr/off_day_list.html', {
        'tab': tab,
        'upcoming_only': upcoming_only,
        'status_filter': status_filter,
        'holidays': holidays_page,
        'holidays_page': holidays_page,
        'staff_offs': staff_offs_page,
        'page_obj': staff_offs_page,
        'off_metrics': off_metrics,
        'today': today,
        'is_self_view': is_staff_self_service(request.user),
        'can_manage': can_write_hr(request.user),
    })


@hr_write_required
def holiday_create(request):
    if request.method == 'POST':
        form = PublicHolidayForm(request.POST)
        if form.is_valid():
            holiday = form.save(commit=False)
            holiday.created_by = request.user
            holiday.save()
            messages.success(request, f'Public holiday "{holiday.name}" added.')
            return redirect('hr:off_day_list')
    else:
        form = PublicHolidayForm()
    return render(request, 'hr/holiday_form.html', {'form': form})


@hr_access_required
def holiday_detail(request, pk):
    if is_staff_self_service(request.user):
        raise PermissionDenied
    holiday = get_object_or_404(PublicHoliday.objects.select_related('created_by'), pk=pk)
    today = timezone.localdate()
    return render(request, 'hr/holiday_detail.html', {
        'holiday': holiday,
        'today': today,
        'can_manage': can_write_hr(request.user),
    })


@hr_write_required
def holiday_edit(request, pk):
    holiday = get_object_or_404(PublicHoliday, pk=pk)
    if request.method == 'POST':
        form = PublicHolidayForm(request.POST, instance=holiday)
        if form.is_valid():
            holiday = form.save()
            messages.success(request, f'Public holiday "{holiday.name}" updated.')
            return redirect('hr:holiday_detail', pk=holiday.pk)
    else:
        form = PublicHolidayForm(instance=holiday)
    return render(request, 'hr/holiday_form.html', {
        'form': form,
        'holiday': holiday,
        'is_edit': True,
    })


@hr_write_required
def holiday_delete(request, pk):
    holiday = get_object_or_404(PublicHoliday, pk=pk)
    if request.method == 'POST':
        name = holiday.name
        holiday.delete()
        messages.success(request, f'Removed holiday "{name}".')
        return redirect('hr:off_day_list')
    return redirect('hr:holiday_detail', pk=pk)


@hr_access_required
def staff_off_detail(request, pk):
    off = get_object_or_404(
        StaffOffDay.objects.select_related('user', 'created_by', 'reviewed_by'),
        pk=pk,
    )
    if not user_may_view_off_day(request.user, off):
        raise PermissionDenied
    today = timezone.localdate()
    other_offs = StaffOffDay.objects.filter(user=off.user).exclude(pk=off.pk).order_by('-date')[:5]
    return render(request, 'hr/staff_off_detail.html', {
        'off': off,
        'other_offs': other_offs,
        'today': today,
        'can_manage': can_write_hr(request.user),
    })


@hr_access_required
def staff_off_create(request):
    restrict_user = request.user if is_staff_self_service(request.user) else None
    if request.method == 'POST':
        form = StaffOffDayForm(request.POST, restrict_user=restrict_user)
        if form.is_valid():
            off = form.save(commit=False)
            off.created_by = request.user
            off.save()
            messages.success(request, f'Off day request submitted for {off.user.get_full_name()}.')
            return redirect('hr:staff_off_detail', pk=off.pk)
    else:
        form = StaffOffDayForm(restrict_user=restrict_user)
    return render(request, 'hr/staff_off_form.html', {
        'form': form,
        'is_self_view': restrict_user is not None,
    })


@hr_write_required
def staff_off_delete(request, pk):
    off = get_object_or_404(StaffOffDay, pk=pk)
    if request.method == 'POST':
        off.delete()
        messages.success(request, 'Staff off day removed.')
        return redirect('hr:off_day_queue')
    return redirect('hr:staff_off_detail', pk=pk)


@hr_write_required
def staff_off_approve(request, pk):
    if request.method != 'POST':
        return redirect('hr:staff_off_detail', pk=pk)
    off = get_object_or_404(StaffOffDay, pk=pk)
    if off.status != 'Pending':
        messages.error(request, 'Only pending requests can be approved.')
        return _action_redirect(request, 'hr:staff_off_detail', pk, 'hr:off_day_queue')
    off.status = 'Approved'
    off.reviewed_by = request.user
    off.reviewed_at = timezone.now()
    off.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    compute_attendance_day(off.user, off.date, force=True)
    messages.success(request, f'Off day approved for {off.user.get_full_name()}.')
    return _action_redirect(request, 'hr:staff_off_detail', pk, 'hr:off_day_queue')


@hr_write_required
def staff_off_reject(request, pk):
    if request.method != 'POST':
        return redirect('hr:staff_off_detail', pk=pk)
    off = get_object_or_404(StaffOffDay, pk=pk)
    if off.status != 'Pending':
        messages.error(request, 'Only pending requests can be rejected.')
        return _action_redirect(request, 'hr:staff_off_detail', pk, 'hr:off_day_queue')
    notes = request.POST.get('review_notes', '').strip()
    off.status = 'Rejected'
    off.reviewed_by = request.user
    off.reviewed_at = timezone.now()
    off.review_notes = notes
    off.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes'])
    compute_attendance_day(off.user, off.date, force=True)
    messages.success(request, f'Off day rejected for {off.user.get_full_name()}.')
    return _action_redirect(request, 'hr:staff_off_detail', pk, 'hr:off_day_queue')


@hr_access_required
def staff_off_cancel(request, pk):
    if request.method != 'POST':
        return redirect('hr:staff_off_detail', pk=pk)
    off = get_object_or_404(StaffOffDay, pk=pk)
    if not user_may_view_off_day(request.user, off):
        raise PermissionDenied
    if not can_write_hr(request.user) and off.user_id != request.user.pk:
        raise PermissionDenied
    if off.status not in ('Pending', 'Approved'):
        messages.error(request, 'This off day cannot be cancelled.')
        return _action_redirect(request, 'hr:staff_off_detail', pk, 'hr:off_day_queue')
    off.status = 'Cancelled'
    off.reviewed_by = request.user
    off.reviewed_at = timezone.now()
    off.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    compute_attendance_day(off.user, off.date, force=True)
    messages.success(request, f'Off day cancelled for {off.user.get_full_name()}.')
    return _action_redirect(request, 'hr:staff_off_detail', pk, 'hr:off_day_queue')


def _parse_attendance_date(request):
    date_str = request.GET.get('date', '') or request.POST.get('date', '')
    if date_str:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    return timezone.localdate()


@hr_access_required
def attendance_dashboard(request):
    if is_staff_self_service(request.user):
        return redirect('hr:attendance_user_detail', user_id=request.user.pk)
    day = _parse_attendance_date(request)
    status_filter = request.GET.get('status', '')
    q = request.GET.get('q', '').strip()

    if request.method == 'POST' and request.POST.get('action') == 'process':
        if not can_manage_attendance(request.user):
            raise PermissionDenied
        process_attendance_for_date(day, force=request.POST.get('force') == '1')
        messages.success(request, f'Attendance recalculated for {day.strftime("%d %b %Y")}.')
        return redirect(f"{request.path}?date={day.isoformat()}")

    metrics, records = attendance_metrics_for_date(day)
    if status_filter:
        records = records.filter(status=status_filter)
    if q:
        records = records.filter(
            Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__id_number__icontains=q)
        )

    return render(request, 'hr/attendance_dashboard.html', {
        'day': day,
        'metrics': metrics,
        'records': records,
        'status_filter': status_filter,
        'q': q,
        'devices': AttendanceDevice.objects.filter(is_active=True),
        'can_manage': can_manage_attendance(request.user),
    })


@hr_access_required
def attendance_user_detail(request, user_id):
    staff_user = get_object_or_404(User, pk=user_id, is_active=True)
    if not user_may_view_attendance_user(request.user, staff_user):
        raise PermissionDenied
    today = timezone.localdate()
    month_str = request.GET.get('month', '')
    if month_str and '-' in month_str:
        parts = month_str.split('-')
        cal_year = int(parts[0])
        cal_month = int(parts[1])
    else:
        cal_year = int(request.GET.get('year', today.year))
        try:
            cal_month = int(request.GET.get('month') or today.month)
        except (TypeError, ValueError):
            cal_month = today.month

    weeks, summary = build_user_attendance_calendar(staff_user, cal_year, cal_month)
    profile = StaffAttendanceProfile.objects.filter(user=staff_user).first()

    selected_date = None
    selected_day = None
    day_logs = []
    date_str = request.GET.get('date', '')
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            selected_day = AttendanceDay.objects.filter(user=staff_user, date=selected_date).first()
            day_logs = attendance_logs_for_user_day(staff_user, selected_date)
        except ValueError:
            selected_date = None

    if cal_month == 12:
        next_year, next_month = cal_year + 1, 1
    else:
        next_year, next_month = cal_year, cal_month + 1
    if cal_month == 1:
        prev_year, prev_month = cal_year - 1, 12
    else:
        prev_year, prev_month = cal_year, cal_month - 1

    from datetime import date as date_cls
    month_label = date_cls(cal_year, cal_month, 1).strftime('%B %Y')

    return render(request, 'hr/attendance_user_detail.html', {
        'staff_user': staff_user,
        'profile': profile,
        'weeks': weeks,
        'summary': summary,
        'cal_year': cal_year,
        'cal_month': cal_month,
        'month_label': month_label,
        'prev_year': prev_year,
        'prev_month': prev_month,
        'next_year': next_year,
        'next_month': next_month,
        'selected_date': selected_date,
        'selected_day': selected_day,
        'day_logs': day_logs,
        'today': today,
        'can_manage': can_manage_attendance(request.user),
    })


@hr_access_required
def attendance_logs(request):
    if is_staff_self_service(request.user):
        raise PermissionDenied
    q = request.GET.get('q', '').strip()
    logs = AttendanceLog.objects.select_related('user', 'device').order_by('-punch_time')
    if q:
        logs = logs.filter(
            Q(device_user_id__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
        )
    logs_page = paginate_queryset(request, logs, per_page=50)
    return render(request, 'hr/attendance_logs.html', {
        'logs': logs_page,
        'page_obj': logs_page,
        'q': q,
        'unmapped_count': AttendanceLog.objects.filter(user__isnull=True).count(),
    })


@hr_write_required
def attendance_devices(request):
    devices = AttendanceDevice.objects.all()
    return render(request, 'hr/attendance_devices.html', {'devices': devices})


@hr_write_required
def attendance_device_create(request):
    if request.method == 'POST':
        form = AttendanceDeviceForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Device added.')
            return redirect('hr:attendance_devices')
    else:
        form = AttendanceDeviceForm()
    return render(request, 'hr/attendance_device_form.html', {'form': form, 'is_create': True})


@hr_write_required
def attendance_device_edit(request, pk):
    device = get_object_or_404(AttendanceDevice, pk=pk)
    if request.method == 'POST':
        form = AttendanceDeviceForm(request.POST, instance=device)
        if form.is_valid():
            form.save()
            messages.success(request, 'Device updated.')
            return redirect('hr:attendance_devices')
    else:
        form = AttendanceDeviceForm(instance=device)
    return render(request, 'hr/attendance_device_form.html', {'form': form, 'device': device, 'is_create': False})


@hr_write_required
def attendance_device_sync(request, pk):
    if request.method != 'POST':
        return redirect('hr:attendance_devices')
    device = get_object_or_404(AttendanceDevice, pk=pk)
    ok, msg, count = sync_device(device)
    if ok:
        process_attendance_for_date(timezone.localdate(), force=True)
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect('hr:attendance_devices')


@hr_write_required
def attendance_sync_all(request):
    if request.method != 'POST':
        return redirect('hr:attendance_dashboard')
    results = sync_and_process(timezone.localdate())
    if not results:
        messages.warning(request, 'No active devices configured.')
    else:
        for device, ok, msg, _count in results:
            if ok:
                messages.success(request, f'{device.name}: {msg}')
            else:
                messages.error(request, f'{device.name}: {msg}')
    return redirect('hr:attendance_dashboard')


@hr_write_required
def attendance_profiles(request):
    q = request.GET.get('q', '').strip()
    staff = User.objects.filter(is_active=True).exclude(role='Admin')
    if q:
        staff = staff.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(id_number__icontains=q)
            | Q(attendance_profile__device_user_id__icontains=q)
        )
    rows = []
    for member in staff.order_by('first_name', 'last_name'):
        profile, _ = StaffAttendanceProfile.objects.get_or_create(user=member)
        rows.append({'user': member, 'profile': profile})
    return render(request, 'hr/attendance_profiles.html', {
        'rows': rows,
        'q': q,
    })


@hr_write_required
def attendance_profile_edit(request, user_id):
    staff_user = get_object_or_404(User, pk=user_id, is_active=True)
    profile, _ = StaffAttendanceProfile.objects.get_or_create(user=staff_user)
    if request.method == 'POST':
        form = StaffAttendanceProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            if profile.device_user_id:
                AttendanceLog.objects.filter(
                    device_user_id=profile.device_user_id,
                    user__isnull=True,
                ).update(user=staff_user)
            messages.success(request, f'Device profile saved for {staff_user.get_full_name()}.')
            return redirect('hr:attendance_profiles')
    else:
        form = StaffAttendanceProfileForm(instance=profile)
    return render(request, 'hr/attendance_profile_form.html', {
        'form': form,
        'staff_user': staff_user,
    })


@hr_write_required
def attendance_manual(request):
    day = _parse_attendance_date(request)
    initial = {'date': day}
    user_id = request.GET.get('user', '')
    if user_id.isdigit():
        initial['user'] = int(user_id)
    if request.method == 'POST':
        form = ManualAttendanceForm(request.POST)
        if form.is_valid():
            record = form.save()
            messages.success(request, f'Attendance saved for {record.user.get_full_name()}.')
            return redirect(
                f"{reverse('hr:attendance_user_detail', args=[record.user_id])}"
                f"?year={record.date.year}&month={record.date.month}&date={record.date.isoformat()}"
            )
    else:
        form = ManualAttendanceForm(initial=initial)
    return render(request, 'hr/attendance_manual_form.html', {'form': form, 'day': day})


@hr_write_required
def attendance_reprocess(request, pk):
    if request.method != 'POST':
        return redirect('hr:attendance_dashboard')
    record = get_object_or_404(AttendanceDay, pk=pk)
    compute_attendance_day(record.user, record.date, force=True)
    messages.success(request, f'Recalculated attendance for {record.user.get_full_name()}.')
    if request.POST.get('next') == 'user':
        return redirect(
            f"{reverse('hr:attendance_user_detail', args=[record.user_id])}"
            f"?year={record.date.year}&month={record.date.month}&date={record.date.isoformat()}"
        )
    return redirect(f"{reverse('hr:attendance_dashboard')}?date={record.date.isoformat()}")


@hr_settings_required
def leave_type_list(request):
    return render(request, 'hr/leave_type_list.html', {
        'leave_types': LeaveType.objects.order_by('name'),
    })


@hr_settings_required
def leave_type_create(request):
    if request.method == 'POST':
        form = LeaveTypeForm(request.POST)
        if form.is_valid():
            leave_type = form.save()
            messages.success(request, f'Leave type "{leave_type.name}" created.')
            return redirect('hr:leave_type_list')
    else:
        form = LeaveTypeForm()
    return render(request, 'hr/leave_type_form.html', {'form': form})


@hr_settings_required
def leave_type_edit(request, pk):
    leave_type = get_object_or_404(LeaveType, pk=pk)
    if request.method == 'POST':
        form = LeaveTypeForm(request.POST, instance=leave_type)
        if form.is_valid():
            leave_type = form.save()
            messages.success(request, f'Leave type "{leave_type.name}" updated.')
            return redirect('hr:leave_type_list')
    else:
        form = LeaveTypeForm(instance=leave_type)
    return render(request, 'hr/leave_type_form.html', {
        'form': form,
        'leave_type': leave_type,
        'is_edit': True,
    })


@hr_settings_required
def staff_entitlement_edit(request, user_id):
    staff_user = get_object_or_404(User, pk=user_id, is_active=True)
    if request.method == 'POST':
        leave_type_id = request.POST.get('leave_type')
        days = request.POST.get('days_per_year', '').strip()
        notes = request.POST.get('notes', '').strip()
        action = request.POST.get('action', 'save')

        if action == 'delete' and leave_type_id:
            StaffLeaveEntitlement.objects.filter(
                user=staff_user,
                leave_type_id=leave_type_id,
            ).delete()
            messages.success(request, f'Custom entitlement removed for {staff_user.get_full_name()}.')
            return redirect('hr:staff_entitlement_edit', user_id=staff_user.pk)

        if not leave_type_id or days == '':
            messages.error(request, 'Leave type and days are required.')
        else:
            leave_type = get_object_or_404(LeaveType, pk=leave_type_id)
            entitlement, _ = StaffLeaveEntitlement.objects.update_or_create(
                user=staff_user,
                leave_type=leave_type,
                defaults={
                    'days_per_year': int(days),
                    'notes': notes,
                },
            )
            messages.success(
                request,
                f'{leave_type.name} set to {entitlement.days_per_year} days for {staff_user.get_full_name()}.',
            )
        return redirect('hr:staff_entitlement_edit', user_id=staff_user.pk)

    entitlement_map = {
        item.leave_type_id: item
        for item in StaffLeaveEntitlement.objects.filter(user=staff_user).select_related('leave_type')
    }
    rows = []
    for leave_type in LeaveType.objects.filter(is_active=True):
        override = entitlement_map.get(leave_type.pk)
        rows.append({
            'leave_type': leave_type,
            'override': override,
            'effective_days': get_leave_entitlement(staff_user, leave_type),
        })
    return render(request, 'hr/staff_entitlement_form.html', {
        'staff_user': staff_user,
        'rows': rows,
        'leave_types': LeaveType.objects.filter(is_active=True),
    })
