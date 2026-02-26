from django import forms
from django.db.models import Q
from .models import Patient, EmergencyContact, Prescription, PrescriptionItem
from accounts.models import Service, Payment

# ... (skip to PatientForm)


class EmergencyContactForm(forms.ModelForm):
    """Form for creating and updating emergency contact records"""
    
    class Meta:
        model = EmergencyContact
        fields = ['name', 'relationship', 'phone', 'email', 'address', 'is_primary']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'relationship': forms.Select(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'is_primary': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name != 'is_primary':
                field.widget.attrs['class'] = 'form-control'
        
        # Add help text
        self.fields['name'].help_text = "Full name of the emergency contact person"
        self.fields['relationship'].help_text = "Relationship to the patient"
        self.fields['phone'].help_text = "Primary phone number for emergencies"
        self.fields['email'].help_text = "Email address for non-urgent communication"
        self.fields['address'].help_text = "Physical address of the emergency contact"
        self.fields['is_primary'].help_text = "Check if this is the primary emergency contact"
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            # Basic phone validation - can be enhanced
            phone = ''.join(filter(str.isdigit, phone))
            if len(phone) < 10:
                raise forms.ValidationError("Phone number must be at least 10 digits")
        return phone
    
    def clean(self):
        cleaned_data = super().clean()
        is_primary = cleaned_data.get('is_primary')
        patient = getattr(self.instance, 'patient', None)
        
        # If this is being set as primary, check if there's already a primary contact
        if is_primary and patient:
            existing_primary = EmergencyContact.objects.filter(
                patient=patient,
                is_primary=True
            ).exclude(pk=self.instance.pk).first()
            
            if existing_primary:
                raise forms.ValidationError(
                    "There is already a primary emergency contact for this patient. "
                    "Please uncheck the primary contact for the existing contact first."
                )
        
        return cleaned_data


class PrescriptionForm(forms.ModelForm):
    """Form for creating prescriptions"""
    
    class Meta:
        model = Prescription
        fields = ['diagnosis', 'notes']
        widgets = {
            'diagnosis': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Enter diagnosis or reason for prescription...'
            }),
            'notes': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Additional instructions or notes (optional)...'
            }),
        }


class PrescriptionItemForm(forms.ModelForm):
    """Form for individual prescription items (medications)"""
    
    class Meta:
        model = PrescriptionItem
        fields = ['medication', 'dose_count', 'frequency', 'number_of_days', 'quantity', 'instructions']
        widgets = {
            'medication': forms.Select(attrs={'class': 'medication-select'}),
            'dose_count': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Pills/Dose'}),
            'frequency': forms.Select(attrs={'class': 'frequency-select'}),
            'number_of_days': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Days'}),
            'quantity': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Total quantity'}),
            'instructions': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Special instructions (optional)...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter to show medications from inventory (Pharmaceuticals category)
        from inventory.models import InventoryItem, InventoryCategory
        
        # Try to get Pharmaceuticals category, fallback to all items if not found
        pharma_category = InventoryCategory.objects.filter(name__icontains='Pharmaceutical').first()
        
        if pharma_category:
            queryset = InventoryItem.objects.filter(category=pharma_category)
        else:
            # Fallback: show items with medication object OR all items
            queryset = InventoryItem.objects.all()

        self.fields['medication'].queryset = queryset.order_by('name')
        
        # Add Tailwind styling to all fields
        for field_name, field in self.fields.items():
            current_classes = field.widget.attrs.get('class', '')
            field.widget.attrs.update({
                'class': f'{current_classes} w-full rounded-xl border-slate-200 focus:border-purple-500 focus:ring-purple-500 text-slate-700 text-sm font-bold placeholder-slate-400 shadow-sm transition-all bg-slate-50 focus:bg-white'
            })
        
        self.fields['medication'].queryset = queryset.select_related('category').order_by('name')
        
        # Customize labels to show category and formulation if available
        self.fields['medication'].label_from_instance = lambda obj: (
            f"{obj.name} ({obj.medication.generic_name} - {obj.medication.formulation})" 
            if hasattr(obj, 'medication') and obj.medication else obj.name
        )
        
        self.fields['medication'].empty_label = "Select a medication"


class DispenseInventoryForm(forms.ModelForm):
    """Form for dispensing general inventory items (consumables, etc.)"""
    
    class Meta:
        from inventory.models import DispensedItem
        model = DispensedItem
        fields = ['item', 'quantity']
        widgets = {
            'item': forms.Select(attrs={'class': 'item-select'}),
            'quantity': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Quantity'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from inventory.models import InventoryItem, InventoryCategory
        
        # Filter for Consumables or non-pharmaceuticals
        consumable_category = InventoryCategory.objects.filter(name__icontains='Consumable').first()
        pharma_category = InventoryCategory.objects.filter(name__icontains='Pharmaceutical').first()
        
        if consumable_category:
            queryset = InventoryItem.objects.filter(category=consumable_category)
        elif pharma_category:
            queryset = InventoryItem.objects.exclude(category=pharma_category)
        else:
            queryset = InventoryItem.objects.all()
            
        self.fields['item'].queryset = queryset.order_by('name')
        self.fields['item'].empty_label = "Select an item"
        
        # Add Tailwind styling
        for field_name, field in self.fields.items():
            current_classes = field.widget.attrs.get('class', '')
            field.widget.attrs.update({
                'class': f'{current_classes} w-full rounded-xl border-slate-200 focus:border-emerald-500 focus:ring-emerald-500 text-slate-700 text-sm font-bold placeholder-slate-400 shadow-sm transition-all bg-slate-50 focus:bg-white'
            })


class PatientForm(forms.ModelForm):
    """Form for creating and updating patient records with integrated billing"""
    
    consultation_type = forms.ModelChoiceField(
        queryset=Service.objects.filter(
            is_active=True
        ).order_by('department__name', 'name'),
        required=True,
        label="Service",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    payment_method = forms.ChoiceField(
        choices=Payment.PAYMENT_METHOD_CHOICES,
        required=True,
        label="Payment Method",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Patient
        fields = ['first_name', 'last_name', 'id_number', 'date_of_birth', 'phone', 'location', 'gender']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'id_number': forms.TextInput(attrs={'class': 'form-control'}),
            'date_of_birth': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If we are editing, consultation_type and payment_method might not be needed
        if self.instance.pk:
            self.fields['consultation_type'].required = False
            self.fields['payment_method'].required = False
            # Hide them in the template or just leave them as optional

from .models import Symptoms, Impression, Diagnosis, Referral

class SymptomsForm(forms.ModelForm):
    class Meta:
        model = Symptoms
        fields = ['data', 'days']
        widgets = {
            'data': forms.Textarea(attrs={'class': 'clinical-input', 'rows': 3, 'placeholder': 'Describe symptoms...'}),
            'days': forms.NumberInput(attrs={'class': 'clinical-input', 'placeholder': 'Duration in days'}),
        }

class ImpressionForm(forms.ModelForm):
    class Meta:
        model = Impression
        fields = ['data']
        widgets = {
            'data': forms.Textarea(attrs={'class': 'clinical-input', 'rows': 3, 'placeholder': 'Clinical impression...'}),
        }

class DiagnosisForm(forms.ModelForm):
    class Meta:
        model = Diagnosis
        fields = ['data']
        widgets = {
            'data': forms.Textarea(attrs={'class': 'clinical-input', 'rows': 3, 'placeholder': 'Final diagnosis...'}),
        }

class ReferralForm(forms.ModelForm):
    class Meta:
        model = Referral
        fields = ['destination', 'reason', 'clinical_summary', 'notes']
        widgets = {
            'destination': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Kenyatta National Hospital'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Reason for referral...'}),
            'clinical_summary': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Summary of findings, treatment given...'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Additional notes...'}),
        }

from inpatient.models import Ward, Bed
from .models import Appointments
class WardForm(forms.ModelForm):
    class Meta:
        model = Ward
        fields = ['name', 'ward_type', 'base_charge_per_day']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ward Name (e.g., Male Surgical Wing)'}),
            'ward_type': forms.Select(attrs={'class': 'form-control'}),
            'base_charge_per_day': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Daily Charge'}),
        }

class BedForm(forms.ModelForm):
    class Meta:
        model = Bed
        fields = ['ward', 'bed_number', 'bed_type']
        widgets = {
            'ward': forms.Select(attrs={'class': 'form-control'}),
            'bed_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., B-101'}),
            'bed_type': forms.Select(attrs={'class': 'form-control'}),
        }

class AppointmentForm(forms.ModelForm):
    """Form for booking patient appointments"""
    
    class Meta:
        model = Appointments
        fields = ['appointment_date', 'appointment_type']
        widgets = {
            'appointment_date': forms.DateTimeInput(attrs={
                'class': 'clinical-input',
                'type': 'datetime-local',
                'placeholder': 'Select date and time'
            }),
            'appointment_type': forms.Select(choices=[
                ('Follow-up', 'Follow-up'),
                ('Consultation', 'New Consultation'),
                ('Check-up', 'Routine Check-up'),
                ('Surgery', 'Surgery Scheduling'),
                ('Lab Review', 'Lab Results Review'),
                ('Other', 'Other')
            ], attrs={'class': 'clinical-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({
                'class': 'w-full rounded-xl border-slate-200 focus:border-indigo-500 focus:ring-indigo-500 text-slate-700 text-sm font-bold placeholder-slate-400 shadow-sm transition-all bg-slate-50 focus:bg-white px-4 py-3'
            })
