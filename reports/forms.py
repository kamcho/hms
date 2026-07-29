from django import forms

from .models import (
    Moh645DailyReport,
    Moh705bMonthlyReport,
    Moh717MonthlyReport,
    Moh743MonthlyReport,
    NvipMonthlyReport,
)


class NvipReportHeaderForm(forms.ModelForm):
    class Meta:
        model = NvipMonthlyReport
        fields = [
            'facility_name',
            'kmhfl_code',
            'month',
            'year',
            'ward',
            'sub_county',
            'county',
            'notes',
        ]
        widgets = {
            'facility_name': forms.TextInput(attrs={'class': 'form-control'}),
            'kmhfl_code': forms.TextInput(attrs={'class': 'form-control'}),
            'month': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2020, 'max': 2100}),
            'ward': forms.TextInput(attrs={'class': 'form-control'}),
            'sub_county': forms.TextInput(attrs={'class': 'form-control'}),
            'county': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class Moh705bReportHeaderForm(forms.ModelForm):
    class Meta:
        model = Moh705bMonthlyReport
        fields = [
            'facility_name',
            'kmhfl_code',
            'month',
            'year',
            'ward',
            'sub_county',
            'county',
            'compiled_by',
            'compiled_designation',
            'compiled_date',
            'notes',
        ]
        widgets = {
            'facility_name': forms.TextInput(attrs={'class': 'form-control'}),
            'kmhfl_code': forms.TextInput(attrs={'class': 'form-control'}),
            'month': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2020, 'max': 2100}),
            'ward': forms.TextInput(attrs={'class': 'form-control'}),
            'sub_county': forms.TextInput(attrs={'class': 'form-control'}),
            'county': forms.TextInput(attrs={'class': 'form-control'}),
            'compiled_by': forms.TextInput(attrs={'class': 'form-control'}),
            'compiled_designation': forms.TextInput(attrs={'class': 'form-control'}),
            'compiled_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class Moh645DailyReportForm(forms.ModelForm):
    class Meta:
        model = Moh645DailyReport
        fields = [
            'facility_name',
            'report_date',
            'page_number',
            'receipt_date',
            'receipt_reference',
            'balance_previous',
            'qty_received',
            'losses',
            'remarks',
        ]
        widgets = {
            'facility_name': forms.TextInput(attrs={'class': 'form-control'}),
            'report_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'page_number': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'receipt_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'receipt_reference': forms.TextInput(attrs={'class': 'form-control'}),
            'balance_previous': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'qty_received': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'losses': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class Moh743MonthlyReportForm(forms.ModelForm):
    class Meta:
        model = Moh743MonthlyReport
        fields = [
            'facility_name',
            'kmhfl_code',
            'county',
            'sub_county',
            'facility_level',
            'month',
            'year',
            'period_begin',
            'period_end',
        ]
        widgets = {
            'facility_name': forms.TextInput(attrs={'class': 'form-control'}),
            'kmhfl_code': forms.TextInput(attrs={'class': 'form-control'}),
            'county': forms.TextInput(attrs={'class': 'form-control'}),
            'sub_county': forms.TextInput(attrs={'class': 'form-control'}),
            'facility_level': forms.Select(attrs={'class': 'form-control'}),
            'month': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2020, 'max': 2100}),
            'period_begin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'period_end': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


class Moh717ReportHeaderForm(forms.ModelForm):
    class Meta:
        model = Moh717MonthlyReport
        fields = [
            'facility_name',
            'kmhfl_code',
            'month',
            'year',
            'sub_county',
            'county',
            'compiled_by',
            'compiled_designation',
            'compiled_date',
            'notes',
        ]
        widgets = {
            'facility_name': forms.TextInput(attrs={'class': 'form-control'}),
            'kmhfl_code': forms.TextInput(attrs={'class': 'form-control'}),
            'month': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2020, 'max': 2100}),
            'sub_county': forms.TextInput(attrs={'class': 'form-control'}),
            'county': forms.TextInput(attrs={'class': 'form-control'}),
            'compiled_by': forms.TextInput(attrs={'class': 'form-control'}),
            'compiled_designation': forms.TextInput(attrs={'class': 'form-control'}),
            'compiled_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
