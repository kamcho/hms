from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from users.models import User

from .attendance_service import compute_manual_day_metrics
from .leave_utils import leave_requests_overlap, staff_off_day_exists, validate_leave_balance
from .models import (
    AttendanceDay,
    AttendanceDevice,
    LeaveRequest,
    LeaveType,
    PublicHoliday,
    StaffAttendanceProfile,
    StaffLeaveEntitlement,
    StaffOffDay,
    StaffPayrollPayment,
    StaffSalary,
)


class StaffSalaryForm(forms.ModelForm):
    class Meta:
        model = StaffSalary
        fields = ['basic_salary', 'allowance', 'effective_from', 'notes']
        widgets = {
            'basic_salary': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0'}),
            'allowance': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0'}),
            'effective_from': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Optional notes…'}),
        }


def _staff_queryset():
    return User.objects.filter(is_active=True).exclude(role='Admin').order_by('first_name', 'last_name')


class StaffUserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        name = obj.get_full_name()
        if name and name != obj.id_number:
            return f'{name} — {obj.role}'
        return f'{obj.id_number} — {obj.role}'


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ['user', 'leave_type', 'start_date', 'end_date', 'reason']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-input'}),
            'leave_type': forms.Select(attrs={'class': 'form-input'}),
            'start_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'reason': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Reason for leave…'}),
        }

    def __init__(self, *args, restrict_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if restrict_user is not None:
            self.fields['user'] = forms.ModelChoiceField(
                queryset=User.objects.filter(pk=restrict_user.pk),
                initial=restrict_user,
                widget=forms.HiddenInput(),
                label='Staff member',
            )
        else:
            self.fields['user'] = StaffUserChoiceField(
                queryset=_staff_queryset(),
                widget=forms.Select(attrs={'class': 'form-input'}),
                empty_label='Select staff member…',
                label='Staff member',
            )
        self.fields['leave_type'].queryset = LeaveType.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        user = cleaned.get('user')
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if user and start and end:
            if end < start:
                raise ValidationError('End date must be on or after start date.')
            exclude_pk = self.instance.pk if self.instance.pk else None
            if leave_requests_overlap(user, start, end, exclude_pk=exclude_pk):
                raise ValidationError('This staff member already has leave (pending or approved) in that period.')
            leave_type = cleaned.get('leave_type')
            if leave_type:
                balance_errors = validate_leave_balance(
                    user,
                    leave_type,
                    start,
                    end,
                    exclude_pk=exclude_pk,
                )
                if balance_errors:
                    raise ValidationError(balance_errors)
        return cleaned


class LeaveTypeForm(forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = ['name', 'days_per_year', 'is_paid', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Annual Leave'}),
            'days_per_year': forms.NumberInput(attrs={'class': 'form-input', 'min': '0'}),
            'is_paid': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class StaffLeaveEntitlementForm(forms.ModelForm):
    class Meta:
        model = StaffLeaveEntitlement
        fields = ['leave_type', 'days_per_year', 'notes']
        widgets = {
            'leave_type': forms.Select(attrs={'class': 'form-input'}),
            'days_per_year': forms.NumberInput(attrs={'class': 'form-input', 'min': '0'}),
            'notes': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Optional override note…'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['leave_type'].queryset = LeaveType.objects.filter(is_active=True)


class PublicHolidayForm(forms.ModelForm):
    class Meta:
        model = PublicHoliday
        fields = ['date', 'name', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Madaraka Day'}),
            'notes': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Optional'}),
        }


class StaffOffDayForm(forms.ModelForm):
    class Meta:
        model = StaffOffDay
        fields = ['user', 'date', 'reason']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-input'}),
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'reason': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Scheduled roster off'}),
        }

    def __init__(self, *args, restrict_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if restrict_user is not None:
            self.fields['user'] = forms.ModelChoiceField(
                queryset=User.objects.filter(pk=restrict_user.pk),
                initial=restrict_user,
                widget=forms.HiddenInput(),
                label='Staff member',
            )
        else:
            self.fields['user'] = StaffUserChoiceField(
                queryset=_staff_queryset(),
                widget=forms.Select(attrs={'class': 'form-input'}),
                empty_label='Select staff member…',
                label='Staff member',
            )

    def clean(self):
        cleaned = super().clean()
        user = cleaned.get('user')
        date = cleaned.get('date')
        if user and date:
            exclude_pk = self.instance.pk if self.instance.pk else None
            if staff_off_day_exists(user, date, exclude_pk=exclude_pk):
                raise ValidationError('This staff member already has a pending or approved off day on that date.')
        return cleaned


class StaffPayrollPaymentForm(forms.Form):
    amount = forms.DecimalField(
        min_value=Decimal('0.01'),
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0.01'}),
    )
    payment_method = forms.ChoiceField(
        choices=StaffPayrollPayment.PAYMENT_METHODS,
        widget=forms.Select(attrs={'class': 'form-input'}),
    )
    reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'M-Pesa code or bank ref…'}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Optional note…'}),
    )


class StaffAttendanceProfileForm(forms.ModelForm):
    class Meta:
        model = StaffAttendanceProfile
        fields = ['device_user_id', 'shift_start', 'shift_end', 'late_grace_minutes']
        widgets = {
            'device_user_id': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. 101'}),
            'shift_start': forms.TimeInput(attrs={'class': 'form-input', 'type': 'time'}),
            'shift_end': forms.TimeInput(attrs={'class': 'form-input', 'type': 'time'}),
            'late_grace_minutes': forms.NumberInput(attrs={'class': 'form-input', 'min': '0', 'max': '120'}),
        }


class AttendanceDeviceForm(forms.ModelForm):
    class Meta:
        model = AttendanceDevice
        fields = ['name', 'ip_address', 'port', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Main entrance K40'}),
            'ip_address': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '192.168.1.201'}),
            'port': forms.NumberInput(attrs={'class': 'form-input', 'min': '1', 'max': '65535'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class ManualAttendanceForm(forms.ModelForm):
    class Meta:
        model = AttendanceDay
        fields = ['user', 'date', 'status', 'first_in', 'last_out', 'notes']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-input'}),
            'date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-input'}),
            'first_in': forms.TimeInput(attrs={'class': 'form-input', 'type': 'time'}),
            'last_out': forms.TimeInput(attrs={'class': 'form-input', 'type': 'time'}),
            'notes': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Optional note…'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'] = StaffUserChoiceField(
            queryset=_staff_queryset(),
            widget=forms.Select(attrs={'class': 'form-input'}),
            empty_label='Select staff member…',
            label='Staff member',
        )

    def clean(self):
        cleaned = super().clean()
        user = cleaned.get('user')
        date = cleaned.get('date')
        if user and date:
            existing = AttendanceDay.objects.filter(user=user, date=date).first()
            if existing and not self.instance.pk:
                self.instance.pk = existing.pk
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.is_manual = True
        metrics = compute_manual_day_metrics(
            instance.user,
            instance.date,
            instance.first_in,
            instance.last_out,
            status=instance.status,
        )
        instance.status = metrics['status']
        instance.worked_minutes = metrics['worked_minutes']
        instance.late_minutes = metrics['late_minutes']
        if commit:
            instance.save()
        return instance
