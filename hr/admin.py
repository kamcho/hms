from django.contrib import admin

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


@admin.register(StaffSalary)
class StaffSalaryAdmin(admin.ModelAdmin):
    list_display = ('user', 'basic_salary', 'allowance', 'effective_from', 'updated_at')
    list_filter = ('effective_from',)
    search_fields = ('user__id_number', 'user__first_name', 'user__last_name')
    raw_id_fields = ('user', 'updated_by')


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'days_per_year', 'is_paid', 'is_active')
    list_filter = ('is_paid', 'is_active')


@admin.register(StaffLeaveEntitlement)
class StaffLeaveEntitlementAdmin(admin.ModelAdmin):
    list_display = ('user', 'leave_type', 'days_per_year', 'updated_at')
    list_filter = ('leave_type',)
    search_fields = ('user__first_name', 'user__last_name', 'user__id_number')
    raw_id_fields = ('user',)


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'leave_type', 'start_date', 'end_date', 'days_count', 'status', 'requested_at')
    list_filter = ('status', 'leave_type', 'start_date')
    search_fields = ('user__first_name', 'user__last_name', 'user__id_number')
    raw_id_fields = ('user', 'reviewed_by')


@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = ('date', 'name', 'created_at')
    ordering = ('date',)


@admin.register(StaffOffDay)
class StaffOffDayAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'status', 'reason', 'requested_at')
    list_filter = ('status', 'date')
    search_fields = ('user__first_name', 'user__last_name')
    raw_id_fields = ('user', 'reviewed_by', 'created_by')


@admin.register(StaffAttendanceProfile)
class StaffAttendanceProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'device_user_id', 'shift_start', 'shift_end', 'late_grace_minutes')
    search_fields = ('user__first_name', 'user__last_name', 'device_user_id')
    raw_id_fields = ('user',)


@admin.register(AttendanceDevice)
class AttendanceDeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'ip_address', 'port', 'is_active', 'last_sync_at')
    list_filter = ('is_active',)


@admin.register(AttendanceLog)
class AttendanceLogAdmin(admin.ModelAdmin):
    list_display = ('punch_time', 'device_user_id', 'user', 'punch_type', 'device', 'source')
    list_filter = ('punch_type', 'source')
    search_fields = ('device_user_id', 'user__first_name', 'user__last_name')
    raw_id_fields = ('user', 'device')


@admin.register(AttendanceDay)
class AttendanceDayAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'status', 'first_in', 'last_out', 'late_minutes', 'is_manual')
    list_filter = ('status', 'date', 'is_manual')
    search_fields = ('user__first_name', 'user__last_name')
    raw_id_fields = ('user',)


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ('period_year', 'period_month', 'status', 'finalized_at')
    list_filter = ('status', 'period_year')


@admin.register(StaffPayroll)
class StaffPayrollAdmin(admin.ModelAdmin):
    list_display = ('user', 'payroll_run', 'net_pay', 'paid_amount', 'status')
    list_filter = ('status', 'payroll_run__period_year')
    raw_id_fields = ('user', 'payroll_run')


@admin.register(StaffPayrollPayment)
class StaffPayrollPaymentAdmin(admin.ModelAdmin):
    list_display = ('payroll', 'amount', 'payment_method', 'paid_at', 'recorded_by')
    raw_id_fields = ('payroll', 'recorded_by')
