from django import forms

from .models import Moh705bMonthlyReport, Moh717MonthlyReport, NvipMonthlyReport


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
