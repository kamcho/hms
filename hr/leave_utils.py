from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import LeaveRequest, LeaveType, StaffLeaveEntitlement, StaffOffDay


def get_leave_entitlement(user, leave_type):
    """Return annual days allowed for this staff member and leave type."""
    override = StaffLeaveEntitlement.objects.filter(user=user, leave_type=leave_type).first()
    if override:
        return override.days_per_year
    return leave_type.days_per_year


def inclusive_days(start_date, end_date):
    return (end_date - start_date).days + 1


def leave_requests_overlap(user, start_date, end_date, exclude_pk=None):
    """True if user has Pending/Approved leave overlapping the range."""
    qs = LeaveRequest.objects.filter(
        user=user,
        status__in=['Pending', 'Approved'],
        start_date__lte=end_date,
        end_date__gte=start_date,
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def staff_off_day_exists(user, date, exclude_pk=None):
    """True if user already has a pending or approved off day on that date."""
    qs = StaffOffDay.objects.filter(
        user=user,
        date=date,
        status__in=['Pending', 'Approved'],
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def dates_in_range(start_date, end_date):
    day = start_date
    while day <= end_date:
        yield day
        day += timedelta(days=1)


def leave_days_by_year(start_date, end_date):
    """Count leave days allocated to each calendar year in the range."""
    counts = {}
    for day in dates_in_range(start_date, end_date):
        counts[day.year] = counts.get(day.year, 0) + 1
    return counts


def leave_days_in_year(user, leave_type, year, *, statuses, exclude_pk=None):
    """Sum days from matching requests that fall in the given calendar year."""
    qs = LeaveRequest.objects.filter(
        user=user,
        leave_type=leave_type,
        status__in=statuses,
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    total = 0
    for leave in qs.only('start_date', 'end_date'):
        for day in dates_in_range(leave.start_date, leave.end_date):
            if day.year == year:
                total += 1
    return total


def leave_balance_snapshot(user, leave_type, year, *, exclude_pk=None):
    """Remaining entitlement for one staff member, leave type, and year."""
    entitlement = get_leave_entitlement(user, leave_type)
    used = leave_days_in_year(user, leave_type, year, statuses=['Approved'], exclude_pk=exclude_pk)
    pending = leave_days_in_year(user, leave_type, year, statuses=['Pending'], exclude_pk=exclude_pk)
    remaining = max(0, entitlement - used - pending)
    return {
        'year': year,
        'leave_type_id': leave_type.pk,
        'leave_type_name': leave_type.name,
        'entitlement': entitlement,
        'used': used,
        'pending': pending,
        'remaining': remaining,
    }


def leave_balance_for_user(user, year=None):
    """Balances for every active leave type in one calendar year."""
    if year is None:
        year = timezone.localdate().year
    return [
        leave_balance_snapshot(user, leave_type, year)
        for leave_type in LeaveType.objects.filter(is_active=True)
    ]


def validate_leave_balance(user, leave_type, start_date, end_date, *, exclude_pk=None):
    """Return validation error messages; empty list means the request fits."""
    errors = []
    for year, requested_days in leave_days_by_year(start_date, end_date).items():
        snapshot = leave_balance_snapshot(user, leave_type, year, exclude_pk=exclude_pk)
        if requested_days > snapshot['remaining']:
            errors.append(
                f'{leave_type.name} for {year}: requesting {requested_days} day(s) but only '
                f'{snapshot["remaining"]} remain '
                f'({snapshot["used"]} used, {snapshot["pending"]} pending, '
                f'{snapshot["entitlement"]} allowed per year).'
            )
    return errors
