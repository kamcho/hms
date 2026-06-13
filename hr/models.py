from decimal import Decimal, ROUND_HALF_UP
from datetime import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class StaffSalary(models.Model):
    """Monthly salary profile for an HMS user (staff member)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='salary_profile',
    )
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
    allowance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    effective_from = models.DateField()
    notes = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='salary_profiles_updated',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'staff salary'
        verbose_name_plural = 'staff salaries'
        ordering = ['user__first_name', 'user__last_name']

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.gross_monthly}'

    @property
    def gross_monthly(self):
        return self.basic_salary + self.allowance


class LeaveType(models.Model):
    name = models.CharField(max_length=80, unique=True)
    days_per_year = models.PositiveIntegerField(
        default=21,
        help_text='Annual entitlement per staff member (enforced on leave requests).',
    )
    is_paid = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class StaffLeaveEntitlement(models.Model):
    """Per-staff annual leave allowance override for a leave type."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='leave_entitlements',
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name='staff_entitlements',
    )
    days_per_year = models.PositiveIntegerField()
    notes = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['user', 'leave_type']]
        ordering = ['user__first_name', 'leave_type__name']

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.leave_type.name}: {self.days_per_year} days'


class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='leave_requests',
    )
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='requests')
    start_date = models.DateField()
    end_date = models.DateField()
    days_count = models.PositiveIntegerField(default=1)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    requested_at = models.DateTimeField(default=timezone.now)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leave_reviews',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-start_date', '-requested_at']

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.leave_type.name} ({self.start_date} to {self.end_date})'

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'End date must be on or after start date.'})

    def save(self, *args, **kwargs):
        if self.start_date and self.end_date:
            self.days_count = (self.end_date - self.start_date).days + 1
        super().save(*args, **kwargs)


class PublicHoliday(models.Model):
    """Facility-wide day off (everyone)."""

    date = models.DateField(unique=True)
    name = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='holidays_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f'{self.name} ({self.date})'


class StaffOffDay(models.Model):
    """Scheduled day off for one staff member (roster / planned off)."""

    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='off_days',
    )
    date = models.DateField()
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    requested_at = models.DateTimeField(default=timezone.now)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='off_days_reviewed',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='off_days_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-requested_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'date'],
                condition=models.Q(status__in=['Pending', 'Approved']),
                name='unique_staff_off_pending_approved',
            ),
        ]

    def __str__(self):
        return f'{self.user.get_full_name()} off {self.date}'


class StaffAttendanceProfile(models.Model):
    """Links HMS user to ZKTeco device PIN and shift settings."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attendance_profile',
    )
    device_user_id = models.CharField(
        max_length=32,
        blank=True,
        default='',
        help_text='Numeric user ID / PIN on the ZKTeco K40.',
    )
    shift_start = models.TimeField(default=time(8, 0))
    shift_end = models.TimeField(default=time(17, 0))
    late_grace_minutes = models.PositiveSmallIntegerField(default=15)

    class Meta:
        verbose_name = 'staff attendance profile'
        constraints = [
            models.UniqueConstraint(
                fields=['device_user_id'],
                condition=~models.Q(device_user_id=''),
                name='unique_staff_device_user_id',
            ),
        ]

    def __str__(self):
        pin = self.device_user_id or '—'
        return f'{self.user.get_full_name()} (PIN {pin})'


class AttendanceDevice(models.Model):
    """ZKTeco K40 or compatible attendance terminal."""

    name = models.CharField(max_length=100)
    ip_address = models.GenericIPAddressField()
    port = models.PositiveIntegerField(default=4370)
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.ip_address})'


class AttendanceLog(models.Model):
    PUNCH_TYPES = [
        ('In', 'In'),
        ('Out', 'Out'),
        ('Unknown', 'Unknown'),
    ]
    SOURCES = [
        ('device', 'Device'),
        ('manual', 'Manual'),
        ('import', 'Import'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attendance_logs',
    )
    device_user_id = models.CharField(max_length=32)
    punch_time = models.DateTimeField()
    punch_type = models.CharField(max_length=10, choices=PUNCH_TYPES, default='Unknown')
    device = models.ForeignKey(
        AttendanceDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='logs',
    )
    source = models.CharField(max_length=10, choices=SOURCES, default='device')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-punch_time']
        constraints = [
            models.UniqueConstraint(
                fields=['device', 'device_user_id', 'punch_time'],
                name='unique_attendance_punch',
            ),
        ]

    def __str__(self):
        return f'{self.device_user_id} @ {self.punch_time:%Y-%m-%d %H:%M}'


class AttendanceDay(models.Model):
    STATUS_CHOICES = [
        ('Present', 'Present'),
        ('Late', 'Late'),
        ('Absent', 'Absent'),
        ('Half Day', 'Half Day'),
        ('On Leave', 'On Leave'),
        ('Off', 'Off'),
        ('Holiday', 'Holiday'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attendance_days',
    )
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Absent')
    first_in = models.TimeField(null=True, blank=True)
    last_out = models.TimeField(null=True, blank=True)
    worked_minutes = models.PositiveIntegerField(default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    is_manual = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'user__first_name']
        unique_together = [['user', 'date']]

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.date} ({self.status})'


class PayrollRun(models.Model):
    """Monthly payroll period for the whole facility."""

    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Finalized', 'Finalized'),
        ('Paid', 'Paid'),
    ]

    period_year = models.PositiveIntegerField()
    period_month = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Draft')
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_runs_finalized',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-period_year', '-period_month']
        unique_together = [['period_year', 'period_month']]

    def __str__(self):
        return f'Payroll {self.period_month:02d}/{self.period_year}'

    @property
    def period_label(self):
        from datetime import date
        return date(self.period_year, self.period_month, 1).strftime('%B %Y')


class StaffPayroll(models.Model):
    """Monthly pay invoice for one staff member."""

    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Finalized', 'Finalized'),
        ('Partial', 'Partial'),
        ('Paid', 'Paid'),
    ]

    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='lines')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payroll_lines',
    )
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
    allowance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    gross_pay = models.DecimalField(max_digits=12, decimal_places=2)
    working_days = models.PositiveSmallIntegerField(default=0)
    days_present = models.PositiveSmallIntegerField(default=0)
    days_absent = models.PositiveSmallIntegerField(default=0)
    days_on_leave = models.PositiveSmallIntegerField(default=0)
    deductible_days = models.PositiveSmallIntegerField(default=0)
    deduction = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    adjustment = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        help_text='Manual bonus (+) or extra deduction (−).',
    )
    net_pay = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Draft')
    notes = models.TextField(blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payroll_run__period_year', '-payroll_run__period_month']
        unique_together = [['payroll_run', 'user']]

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.payroll_run.period_label}'

    @property
    def balance_due(self):
        return max(Decimal('0'), self.net_pay - self.paid_amount)

    def sync_paid_amount(self):
        """Recalculate paid_amount and status from payment records."""
        from django.db.models import Sum

        total = self.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        self.paid_amount = total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if self.paid_amount >= self.net_pay:
            self.status = 'Paid'
        elif self.paid_amount > 0:
            self.status = 'Partial'
        elif self.finalized_at:
            self.status = 'Finalized'
        self.save(update_fields=['paid_amount', 'status', 'updated_at'])

    def refresh_payment_status(self):
        """Update status from current paid_amount (call after paid_amount is saved)."""
        if self.paid_amount >= self.net_pay:
            self.status = 'Paid'
        elif self.paid_amount > 0:
            self.status = 'Partial'
        elif self.finalized_at:
            self.status = 'Finalized'
        self.save(update_fields=['paid_amount', 'status', 'updated_at'])


class StaffPayrollPayment(models.Model):
    PAYMENT_METHODS = [
        ('Cash', 'Cash'),
        ('M-Pesa', 'M-Pesa'),
        ('Bank', 'Bank transfer'),
    ]

    payroll = models.ForeignKey(StaffPayroll, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='Cash')
    reference = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_payments_recorded',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['paid_at', 'id']

    def __str__(self):
        return f'{self.amount} — {self.payroll}'
