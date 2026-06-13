from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

HR_WRITE_ROLES = ('Admin', 'HR Manager')
HR_READ_ALL_ROLES = ('Admin', 'HR Manager', 'Accountant')


def _role(user):
    return getattr(user, 'role', None)


def is_hr_writer(user):
    return user.is_authenticated and (user.is_superuser or _role(user) in HR_WRITE_ROLES)


def is_hr_reader(user):
    return user.is_authenticated and (
        user.is_superuser or _role(user) in HR_READ_ALL_ROLES
    )


def is_staff_self_service(user):
    """Active staff using HR for their own records only."""
    return (
        user.is_authenticated
        and user.is_active
        and not user.is_superuser
        and _role(user) not in HR_READ_ALL_ROLES
    )


def can_access_hr(user):
    return is_hr_writer(user) or is_hr_reader(user) or is_staff_self_service(user)


def can_manage_hr_settings(user):
    return is_hr_writer(user)


def can_write_hr(user):
    return is_hr_writer(user)


def can_read_all_hr(user):
    return is_hr_reader(user)


def can_view_salaries(user):
    return is_hr_reader(user)


def can_edit_salaries(user):
    return is_hr_writer(user)


def can_approve_leave(user):
    return is_hr_writer(user)


def can_manage_attendance(user):
    return is_hr_writer(user)


def get_hr_context(user):
    return {
        'is_hr_writer': is_hr_writer(user),
        'is_hr_reader': is_hr_reader(user),
        'is_staff_self': is_staff_self_service(user),
        'can_manage_settings': can_manage_hr_settings(user),
        'can_view_salaries': can_view_salaries(user),
        'can_edit_salaries': can_edit_salaries(user),
        'can_approve_leave': can_approve_leave(user),
        'can_manage_attendance': can_manage_attendance(user),
    }


def _deny_unless(check, request):
    if not check(request.user):
        raise PermissionDenied


def hr_access_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        _deny_unless(can_access_hr, request)
        return view_func(request, *args, **kwargs)
    return wrapper


def hr_read_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not (can_read_all_hr(request.user) or is_staff_self_service(request.user)):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper


def hr_write_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        _deny_unless(can_write_hr, request)
        return view_func(request, *args, **kwargs)
    return wrapper


def hr_settings_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        _deny_unless(can_manage_hr_settings, request)
        return view_func(request, *args, **kwargs)
    return wrapper


def user_may_view_leave(user, leave):
    if can_read_all_hr(user):
        return True
    return is_staff_self_service(user) and leave.user_id == user.pk


def user_may_edit_leave(user, leave):
    if can_write_hr(user):
        return leave.status in ('Pending', 'Approved')
    return is_staff_self_service(user) and leave.user_id == user.pk and leave.status == 'Pending'


def user_may_cancel_leave(user, leave):
    if can_write_hr(user):
        return leave.status in ('Pending', 'Approved')
    return is_staff_self_service(user) and leave.user_id == user.pk and leave.status == 'Pending'


def user_may_view_off_day(user, off):
    if can_read_all_hr(user):
        return True
    return is_staff_self_service(user) and off.user_id == user.pk


def user_may_view_attendance_user(user, staff_user):
    if can_read_all_hr(user):
        return True
    return is_staff_self_service(user) and staff_user.pk == user.pk
