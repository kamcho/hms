from django import forms
from .models import Patient, EmergencyContact, Prescription, PrescriptionItem
from accounts.models import Service, Payment


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
        fields = ['medication', 'dose_count', 'frequency_count', 'duration_days', 'quantity', 'instructions']
        widgets = {
            'medication': forms.Select(attrs={'class': 'medication-select'}),
            'dose_count': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Pills/Dose'}),
            'frequency_count': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Times/Day'}),
            'duration_days': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Days'}),
            'quantity': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Total quantity'}),
            'instructions': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Special instructions (optional)...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter to show only medications from inventory using the new item_type
        from inventory.models import InventoryItem
        self.fields['medication'].queryset = InventoryItem.objects.filter(
            item_type='Medicine'
        ).select_related('medication').order_by('name')
        
        # Customize labels to show strength and formulation if available
        self.fields['medication'].label_from_instance = lambda obj: (
            f"{obj.name} ({obj.medication.strength} - {obj.medication.formulation})" 
            if hasattr(obj, 'medication') else obj.name
        )
        
        self.fields['medication'].empty_label = "Select a medication"


class PatientForm(forms.ModelForm):
    """Form for creating and updating patient records with integrated billing"""
    
    consultation_type = forms.ModelChoiceField(
        queryset=Service.objects.filter(name__icontains='Consultation', is_active=True),
        required=True,
        label="Consultation Type",
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
        fields = ['first_name', 'last_name', 'date_of_birth', 'phone', 'location', 'gender']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
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
