"""Pull attendance logs from ZKTeco K40 devices via pyzk."""

from django.utils import timezone

from .attendance_service import (
    process_attendance_for_dates,
    remap_unmapped_attendance_logs,
    user_for_device_id,
)
from .models import AttendanceDevice, AttendanceLog


def _punch_date(punch_time):
    if timezone.is_naive(punch_time):
        punch_time = timezone.make_aware(punch_time, timezone.get_current_timezone())
    return timezone.localtime(punch_time).date()


def sync_device(device):
    """
    Connect to a K40 and import new attendance records.
    Returns (success: bool, message: str, imported_count: int, affected_dates: set[date]).
    """
    try:
        from zk import ZK
    except ImportError:
        return False, 'pyzk is not installed. Run: pip install pyzk', 0, set()

    zk = ZK(device.ip_address, port=device.port, timeout=10)
    conn = None
    imported = 0
    affected_dates = set()
    try:
        conn = zk.connect()
        conn.disable_device()
        since = device.last_sync_at
        records = conn.get_attendance()
        for record in records:
            punch_time = record.timestamp
            if timezone.is_naive(punch_time):
                punch_time = timezone.make_aware(punch_time, timezone.get_current_timezone())
            if since and punch_time <= since:
                continue

            device_user_id = str(record.user_id)
            user = user_for_device_id(device_user_id)
            punch_type = 'Unknown'
            status = getattr(record, 'status', None)
            if status is not None:
                punch_type = 'In' if int(status) == 0 else 'Out' if int(status) == 1 else 'Unknown'

            log, created = AttendanceLog.objects.get_or_create(
                device=device,
                device_user_id=device_user_id,
                punch_time=punch_time,
                defaults={
                    'user': user,
                    'punch_type': punch_type,
                    'source': 'device',
                },
            )
            punch_day = _punch_date(punch_time)
            if not created and user and log.user_id is None:
                log.user = user
                log.save(update_fields=['user'])
                affected_dates.add(punch_day)
            if created:
                imported += 1
                affected_dates.add(punch_day)

        remapped, remap_dates = remap_unmapped_attendance_logs(device=device)
        affected_dates.update(remap_dates)
        device.last_sync_at = timezone.now()
        unmapped = AttendanceLog.objects.filter(user__isnull=True, device=device).count()
        msg = f'Imported {imported} punch(es).'
        if remapped:
            msg += f' Mapped {remapped} existing log(s) to staff.'
        if unmapped:
            msg += f' {unmapped} log(s) still unmapped — check device PIN matches HMS user id or set PIN on staff profiles.'
        device.last_sync_message = msg
        device.save(update_fields=['last_sync_at', 'last_sync_message'])
        return True, msg, imported, affected_dates
    except Exception as exc:
        device.last_sync_message = str(exc)
        device.save(update_fields=['last_sync_message'])
        return False, str(exc), imported, affected_dates
    finally:
        if conn:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass


def sync_all_devices():
    results = []
    for device in AttendanceDevice.objects.filter(is_active=True):
        ok, msg, count, affected_dates = sync_device(device)
        results.append((device, ok, msg, count, affected_dates))
    return results


def sync_and_process(day=None):
    """Sync all devices then rebuild daily attendance for every affected date."""
    from django.utils import timezone as tz

    day = day or tz.localdate()
    sync_results = sync_all_devices()
    affected_dates = {day}
    for _device, ok, _msg, _count, device_dates in sync_results:
        if ok:
            affected_dates.update(device_dates)

    process_attendance_for_dates(affected_dates, force=True)
    return sync_results
