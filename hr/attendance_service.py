import calendar
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from users.models import User

from .models import (
    AttendanceDay,
    AttendanceLog,
    LeaveRequest,
    PublicHoliday,
    StaffAttendanceProfile,
    StaffOffDay,
)

DEFAULT_SHIFT_START = datetime.strptime('08:00', '%H:%M').time()
DEFAULT_SHIFT_END = datetime.strptime('17:00', '%H:%M').time()
DEFAULT_LATE_GRACE = 15


def _staff_queryset():
    return User.objects.filter(is_active=True).exclude(role='Admin')


def get_profile(user):
    profile, _ = StaffAttendanceProfile.objects.get_or_create(
        user=user,
        defaults={
            'shift_start': DEFAULT_SHIFT_START,
            'shift_end': DEFAULT_SHIFT_END,
            'late_grace_minutes': DEFAULT_LATE_GRACE,
        },
    )
    return profile


def user_for_device_id(device_user_id):
    """
    Resolve HMS user from a ZKTeco device user id / PIN.

    Lookup order:
    1. StaffAttendanceProfile.device_user_id (manual PIN mapping)
    2. User.pk when the device was enrolled with Django user.id
    """
    if not device_user_id:
        return None
    device_user_id = str(device_user_id).strip()
    if not device_user_id:
        return None

    try:
        return StaffAttendanceProfile.objects.select_related('user').get(
            device_user_id=device_user_id,
        ).user
    except StaffAttendanceProfile.DoesNotExist:
        pass

    if device_user_id.isdigit():
        user = User.objects.filter(pk=int(device_user_id), is_active=True).first()
        if user:
            profile = get_profile(user)
            pin_taken = StaffAttendanceProfile.objects.filter(
                device_user_id=device_user_id,
            ).exclude(user=user).exists()
            if not pin_taken and profile.device_user_id != device_user_id:
                profile.device_user_id = device_user_id
                profile.save(update_fields=['device_user_id'])
            return user

    return None


def remap_unmapped_attendance_logs(*, device=None):
    """Attach HMS users to punch logs that were imported before mapping existed."""
    qs = AttendanceLog.objects.filter(user__isnull=True)
    if device is not None:
        qs = qs.filter(device=device)
    updated = 0
    affected_dates = set()
    for log in qs.iterator():
        user = user_for_device_id(log.device_user_id)
        if user:
            AttendanceLog.objects.filter(pk=log.pk, user__isnull=True).update(user=user)
            updated += 1
            affected_dates.add(timezone.localtime(log.punch_time).date())
    return updated, affected_dates


def _is_on_leave(user, day):
    return LeaveRequest.objects.filter(
        user=user,
        status='Approved',
        start_date__lte=day,
        end_date__gte=day,
    ).exists()


def _is_staff_off(user, day):
    return StaffOffDay.objects.filter(
        user=user,
        status='Approved',
        date=day,
    ).exists()


def _is_holiday(day):
    return PublicHoliday.objects.filter(date=day).exists()


def _minutes_between(start_t, end_t):
    start = datetime.combine(datetime.min.date(), start_t)
    end = datetime.combine(datetime.min.date(), end_t)
    if end < start:
        end += timedelta(days=1)
    return max(0, int((end - start).total_seconds() // 60))


def _compute_from_punches(user, day, profile):
    start_dt = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    end_dt = start_dt + timedelta(days=1)
    logs = AttendanceLog.objects.filter(
        user=user,
        punch_time__gte=start_dt,
        punch_time__lt=end_dt,
    ).order_by('punch_time')
    if not logs.exists():
        return None

    first_punch = logs.first().punch_time
    last_punch = logs.last().punch_time
    first_in = timezone.localtime(first_punch).time()
    last_out = timezone.localtime(last_punch).time() if logs.count() > 1 else None

    shift_start = profile.shift_start
    grace = timedelta(minutes=profile.late_grace_minutes)
    shift_start_dt = datetime.combine(day, shift_start)
    first_in_dt = datetime.combine(day, first_in)
    late_minutes = 0
    status = 'Present'
    if first_in_dt > shift_start_dt + grace:
        late_minutes = int((first_in_dt - shift_start_dt).total_seconds() // 60)
        status = 'Late'

    worked_minutes = 0
    if last_out and first_in:
        worked_minutes = _minutes_between(first_in, last_out)
        shift_len = _minutes_between(profile.shift_start, profile.shift_end)
        if shift_len and worked_minutes < shift_len // 2:
            status = 'Half Day'

    return {
        'status': status,
        'first_in': first_in,
        'last_out': last_out,
        'worked_minutes': worked_minutes,
        'late_minutes': late_minutes,
    }


def compute_attendance_day(user, day, *, force=False):
    """Build attendance summary for one staff member on one date."""
    existing = AttendanceDay.objects.filter(user=user, date=day).first()
    if existing and existing.is_manual and not force:
        return existing

    profile = get_profile(user)

    if _is_holiday(day):
        data = {
            'status': 'Holiday',
            'first_in': None,
            'last_out': None,
            'worked_minutes': 0,
            'late_minutes': 0,
        }
    elif _is_on_leave(user, day):
        data = {
            'status': 'On Leave',
            'first_in': None,
            'last_out': None,
            'worked_minutes': 0,
            'late_minutes': 0,
        }
    elif _is_staff_off(user, day):
        data = {
            'status': 'Off',
            'first_in': None,
            'last_out': None,
            'worked_minutes': 0,
            'late_minutes': 0,
        }
    else:
        punch_data = _compute_from_punches(user, day, profile)
        if punch_data:
            data = punch_data
        else:
            data = {
                'status': 'Absent',
                'first_in': None,
                'last_out': None,
                'worked_minutes': 0,
                'late_minutes': 0,
            }

    day_record, _ = AttendanceDay.objects.update_or_create(
        user=user,
        date=day,
        defaults={
            **data,
            'is_manual': False,
        },
    )
    return day_record


def compute_manual_day_metrics(user, day, first_in, last_out, *, status='Present'):
    """Derive worked_minutes, late_minutes, and status from manual clock times."""
    profile = get_profile(user)
    worked_minutes = 0
    late_minutes = 0
    computed_status = status

    non_punch_statuses = {'On Leave', 'Off', 'Holiday', 'Absent'}
    if computed_status in non_punch_statuses:
        return {
            'status': computed_status,
            'worked_minutes': 0,
            'late_minutes': 0,
        }

    if first_in:
        shift_start_dt = datetime.combine(day, profile.shift_start)
        first_in_dt = datetime.combine(day, first_in)
        grace = timedelta(minutes=profile.late_grace_minutes)
        if first_in_dt > shift_start_dt + grace:
            late_minutes = int((first_in_dt - shift_start_dt).total_seconds() // 60)
            if computed_status == 'Present':
                computed_status = 'Late'

        if last_out:
            worked_minutes = _minutes_between(first_in, last_out)
            shift_len = _minutes_between(profile.shift_start, profile.shift_end)
            if shift_len and worked_minutes < shift_len // 2:
                computed_status = 'Half Day'
    elif computed_status in ('Present', 'Late'):
        computed_status = 'Absent'

    return {
        'status': computed_status,
        'worked_minutes': worked_minutes,
        'late_minutes': late_minutes,
    }


def process_attendance_for_date(day, *, force=False):
    records = []
    for user in _staff_queryset():
        records.append(compute_attendance_day(user, day, force=force))
    return records


def punch_dates_from_logs(logs):
    """Return local calendar dates covered by attendance punch logs."""
    return {
        timezone.localtime(log.punch_time).date()
        for log in logs.only('punch_time')
    }


def process_attendance_for_dates(dates, *, force=False):
    """Rebuild daily attendance for each date in the set."""
    records = []
    for day in sorted(set(dates)):
        records.extend(process_attendance_for_date(day, force=force))
    return records


def attendance_metrics_for_date(day):
    records = AttendanceDay.objects.filter(date=day)
    if not records.exists():
        process_attendance_for_date(day)
        records = AttendanceDay.objects.filter(date=day)

    metrics = {
        'present': records.filter(status='Present').count(),
        'late': records.filter(status='Late').count(),
        'absent': records.filter(status='Absent').count(),
        'on_leave': records.filter(status='On Leave').count(),
        'off': records.filter(status__in=['Off', 'Holiday']).count(),
        'half_day': records.filter(status='Half Day').count(),
        'total': records.count(),
    }
    return metrics, records.select_related('user').order_by('user__first_name', 'user__last_name')


def build_user_attendance_calendar(user, year, month):
    """Return week rows and month summary for one staff member."""
    month_records = AttendanceDay.objects.filter(
        user=user,
        date__year=year,
        date__month=month,
    )
    by_date = {record.date: record for record in month_records}

    summary = {
        'present': 0,
        'late': 0,
        'absent': 0,
        'on_leave': 0,
        'off': 0,
        'holiday': 0,
        'half_day': 0,
        'tracked': month_records.count(),
    }
    for record in month_records:
        if record.status == 'Present':
            summary['present'] += 1
        elif record.status == 'Late':
            summary['late'] += 1
        elif record.status == 'Absent':
            summary['absent'] += 1
        elif record.status == 'On Leave':
            summary['on_leave'] += 1
        elif record.status == 'Off':
            summary['off'] += 1
        elif record.status == 'Holiday':
            summary['holiday'] += 1
        elif record.status == 'Half Day':
            summary['half_day'] += 1

    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        days = []
        for day in week:
            record = by_date.get(day) if day.month == month else None
            days.append({
                'date': day,
                'in_month': day.month == month,
                'record': record,
            })
        weeks.append(days)

    return weeks, summary


def attendance_logs_for_user_day(user, day):
    start_dt = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    end_dt = start_dt + timedelta(days=1)
    return AttendanceLog.objects.filter(
        user=user,
        punch_time__gte=start_dt,
        punch_time__lt=end_dt,
    ).select_related('device').order_by('punch_time')
