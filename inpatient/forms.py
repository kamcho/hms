from django import forms
from .models import (
    Admission, Bed, Ward, MedicationChart, ServiceAdmissionLink, 
    InpatientDischarge, PatientVitals, ClinicalNote, 
    FluidBalance, WardTransfer, DoctorInstruction, NutritionOrder
)
from home.models import Visit
from inventory.models import InventoryItem
from accounts.models import Service

class AdmissionForm(forms.ModelForm):
    ward = forms.ModelChoiceField(
        queryset=Ward.objects.all(),
        required=True,
        help_text="Select the ward first to see available beds"
    )

    class Meta:
        model = Admission
        fields = ['ward', 'bed', 'provisional_diagnosis']
        widgets = {
            'provisional_diagnosis': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Enter the reason for admission...'}),
        }

    def __init__(self, *args, **kwargs):
        patient = kwargs.pop('patient', None)
        super().__init__(*args, **kwargs)
        self.fields['bed'].queryset = Bed.objects.filter(is_occupied=False).select_related('ward')
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})

class MedicationChartForm(forms.ModelForm):
    class Meta:
        model = MedicationChart
        fields = ['item', 'dose_count', 'frequency_count', 'duration_days', 'quantity']
        widgets = {
            'item': forms.Select(attrs={'class': 'medication-select'}),
            'dose_count': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Pills/Dose', 'class': 'form-control'}),
            'frequency_count': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Times/Day', 'class': 'form-control'}),
            'duration_days': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Days', 'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'min': 1, 'class': 'form-control', 'placeholder': 'Total Units'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['item'].queryset = InventoryItem.objects.filter(item_type='Medicine').order_by('name')

class ServiceAdmissionLinkForm(forms.ModelForm):
    class Meta:
        model = ServiceAdmissionLink
        fields = ['service', 'quantity']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service'].queryset = Service.objects.all().order_by('category', 'name')
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})

class InpatientDischargeForm(forms.ModelForm):
    class Meta:
        model = InpatientDischarge
        fields = ['final_diagnosis', 'discharge_summary']
        widgets = {
            'final_diagnosis': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Enter final clinical diagnosis...'}),
            'discharge_summary': forms.Textarea(attrs={'rows': 5, 'placeholder': 'Provide a summary of treatment and care...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})

class PatientVitalsForm(forms.ModelForm):
    class Meta:
        model = PatientVitals
        fields = [
            'temperature', 'pulse_rate', 'respiratory_rate', 
            'systolic_bp', 'diastolic_bp', 'spo2', 'weight', 'blood_sugar'
        ]
        widgets = {
            'temperature': forms.NumberInput(attrs={'step': '0.1', 'placeholder': '36.5'}),
            'pulse_rate': forms.NumberInput(attrs={'placeholder': '72'}),
            'respiratory_rate': forms.NumberInput(attrs={'placeholder': '18'}),
            'systolic_bp': forms.NumberInput(attrs={'placeholder': '120'}),
            'diastolic_bp': forms.NumberInput(attrs={'placeholder': '80'}),
            'spo2': forms.NumberInput(attrs={'placeholder': '98'}),
            'weight': forms.NumberInput(attrs={'step': '0.1', 'placeholder': '70'}),
            'blood_sugar': forms.NumberInput(attrs={'step': '0.1', 'placeholder': '5.5'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})

class ClinicalNoteForm(forms.ModelForm):
    class Meta:
        model = ClinicalNote
        fields = ['note_type', 'content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 6, 'placeholder': 'Enter clinical findings, plan of care...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})

class FluidBalanceForm(forms.ModelForm):
    class Meta:
        model = FluidBalance
        fields = ['fluid_type', 'item', 'amount_ml']
        widgets = {
            'item': forms.TextInput(attrs={'placeholder': 'e.g., Oral Fluids, Urine'}),
            'amount_ml': forms.NumberInput(attrs={'placeholder': '500'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})

class WardTransferForm(forms.ModelForm):
    ward = forms.ModelChoiceField(
        queryset=Ward.objects.all(),
        required=True,
        help_text="Select target ward"
    )

    class Meta:
        model = WardTransfer
        fields = ['ward', 'to_bed', 'reason']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Reason for transfer...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['to_bed'].queryset = Bed.objects.filter(is_occupied=False)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})

class DoctorInstructionForm(forms.ModelForm):
    class Meta:
        model = DoctorInstruction
        fields = ['instruction_type', 'instruction']
        widgets = {
            'instruction': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Enter medical instruction or order...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})

class NutritionOrderForm(forms.ModelForm):
    class Meta:
        model = NutritionOrder
        fields = ['diet_type', 'specific_instructions']
        widgets = {
            'specific_instructions': forms.Textarea(attrs={'rows': 2, 'placeholder': 'e.g. No caffeine, fluid restriction...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})
