from django import forms
from django.contrib.auth import get_user_model
from .models import LabResult, LabReport, ServiceParameters
from accounts.models import Invoice

User = get_user_model()

class LabResultForm(forms.ModelForm):
    class Meta:
        model = LabResult
        fields = ['patient', 'service', 'invoice', 'priority', 'scheduled_for', 'clinical_notes']
        widgets = {
            'patient': forms.Select(attrs={'class': 'form-control'}),
            'service': forms.Select(attrs={'class': 'form-control'}),
            'invoice': forms.Select(attrs={'class': 'form-control'}),
            'priority': forms.Select(attrs={'class': 'form-control'}),
            'scheduled_for': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'clinical_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class LabReportForm(forms.ModelForm):
    class Meta:
        model = LabReport
        fields = ['report_file', 'report_text', 'is_final']
        widgets = {
            'report_file': forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png,.doc,.docx'}),
            'report_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 8}),
            'is_final': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class LabResultUpdateForm(forms.ModelForm):
    performed_by = forms.ModelChoiceField(
        queryset=User.objects.filter(role__in=['Doctor', 'Lab Technician', 'Radiographer']),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = LabResult
        fields = ['status', 'performed_by', 'results', 'interpretation']
        widgets = {
            'interpretation': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

class ServiceParameterForm(forms.ModelForm):
    class Meta:
        model = ServiceParameters
        fields = ['name', 'value', 'unit', 'ranges']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Parameter Name (e.g. Hemoglobin)'}),
            'value': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Result Value'}),
            'unit': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Unit (e.g. g/dL)'}),
            'ranges': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Reference Range (e.g. 12-16)'}),
        }
