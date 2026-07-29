from django import forms
from django.db.models import Q
from .models import (
    Patient,
    EmergencyContact,
    Prescription,
    PrescriptionItem,
    Problem,
    PatientMedication,
    PatientAllergy,
    FamilyHistory,
)
from accounts.models import Service, Payment

# ... (skip to PatientForm)


class EmergencyContactForm(forms.ModelForm):
    """Form for next of kin / emergency contact (KPS.A contactPerson)."""

    class Meta:
        model = EmergencyContact
        fields = [
            'given_name', 'family_name', 'name', 'role', 'relationship',
            'phone', 'email', 'address', 'is_primary',
        ]
        widgets = {
            'given_name': forms.TextInput(attrs={'class': 'form-control'}),
            'family_name': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
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

        self.fields['given_name'].help_text = "First name (KPS.A contactPerson.name.given)"
        self.fields['family_name'].help_text = "Surname (KPS.A contactPerson.name.family)"
        self.fields['name'].help_text = "Full name (auto-filled from given + family if left blank)"
        self.fields['name'].required = False
        self.fields['role'].help_text = "KNHTS role: Next-of-Kin, Emergency Contact, etc."
        self.fields['relationship'].help_text = "Kinship to the patient (e.g. father, spouse)"
        self.fields['phone'].help_text = "Primary phone number"
        self.fields['email'].help_text = "Email address for non-urgent communication"
        self.fields['address'].help_text = "Physical address of the contact"
        self.fields['is_primary'].help_text = "Primary next of kin / emergency contact"

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            phone = ''.join(filter(str.isdigit, phone))
            if len(phone) < 10:
                raise forms.ValidationError("Phone number must be at least 10 digits")
        return phone

    def clean(self):
        cleaned_data = super().clean()
        given = (cleaned_data.get('given_name') or '').strip()
        family = (cleaned_data.get('family_name') or '').strip()
        name = (cleaned_data.get('name') or '').strip()
        if not name and (given or family):
            cleaned_data['name'] = f"{given} {family}".strip()
        elif not name:
            raise forms.ValidationError("Provide a full name or given + family name.")

        is_primary = cleaned_data.get('is_primary')
        patient = getattr(self.instance, 'patient', None)

        if is_primary and patient:
            existing_primary = EmergencyContact.objects.filter(
                patient=patient,
                is_primary=True
            ).exclude(pk=self.instance.pk).first()

            if existing_primary:
                raise forms.ValidationError(
                    "There is already a primary contact for this patient. "
                    "Please uncheck the primary flag on the existing contact first."
                )

        return cleaned_data


class PrescriptionForm(forms.ModelForm):
    """Form for creating prescriptions"""

    class Meta:
        model = Prescription
        fields = ['diagnosis', 'notes']
        widgets = {
            'diagnosis': forms.Textarea(attrs={
                'rows': 2,
                'class': 'icd-diagnosis-value hidden',
                'placeholder': 'ICD-11 diagnosis will be set from search…',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Additional instructions or notes (optional)...'
            }),
        }

    def clean_diagnosis(self):
        from .icd11_diagnosis import validate_and_resolve_diagnosis

        value = self.cleaned_data.get('diagnosis')
        _code, display, entry = validate_and_resolve_diagnosis(value, required=True)
        self._icd11_diagnosis_entry = entry
        return display

    def save(self, commit=True):
        prescription = super().save(commit=False)
        entry = getattr(self, '_icd11_diagnosis_entry', None)
        if entry:
            prescription.icd11_code = entry.code
            prescription.icd11_entry = entry
        if commit:
            prescription.save()
        return prescription


class PrescriptionItemForm(forms.ModelForm):
    """Form for individual prescription items (medications)"""
    
    class Meta:
        model = PrescriptionItem
        fields = [
            'medication',
            'generic_concept_code',
            'generic_concept_display',
            'dose_count',
            'dose_unit',
            'frequency',
            'number_of_days',
            'quantity',
            'instructions',
        ]
        widgets = {
            'medication': forms.Select(attrs={'class': 'medication-select'}),
            'generic_concept_code': forms.HiddenInput(attrs={'class': 'dha-generic-code'}),
            'generic_concept_display': forms.HiddenInput(attrs={'class': 'dha-generic-display'}),
            'dose_count': forms.NumberInput(attrs={'min': 0, 'placeholder': 'Units', 'step': '0.01'}),
            'dose_unit': forms.TextInput(attrs={'placeholder': 'e.g. ml, g, mg'}),
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
        
        # Add Tailwind styling to visible fields only
        for field_name, field in self.fields.items():
            if field_name in ('generic_concept_code', 'generic_concept_display'):
                continue
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
        from inventory.consumable_utils import exclude_pharmaceutical_items

        consumable_category = InventoryCategory.objects.filter(name__icontains='Consumable').first()

        queryset = exclude_pharmaceutical_items(InventoryItem.objects.all())
        if consumable_category:
            queryset = queryset.filter(category=consumable_category)
            
        self.fields['item'].queryset = queryset.order_by('name')
        self.fields['item'].empty_label = "Select an item"
        
        # Add Tailwind styling
        for field_name, field in self.fields.items():
            current_classes = field.widget.attrs.get('class', '')
            field.widget.attrs.update({
                'class': f'{current_classes} w-full rounded-xl border-slate-200 focus:border-emerald-500 focus:ring-emerald-500 text-slate-700 text-sm font-bold placeholder-slate-400 shadow-sm transition-all bg-slate-50 focus:bg-white'
            })


class PatientForm(forms.ModelForm):
    """Form for creating and updating patient records with integrated billing (KNHTS / KPS.A)."""

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

    patient_payment_method = forms.ChoiceField(
        choices=[('Cash', 'Cash'), ('M-Pesa', 'M-Pesa')],
        required=False,
        label="Patient Portion Method",
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text="How the patient pays the remaining balance (e.g. for OPD Book/Co-pay)"
    )

    bill_opd_book = forms.BooleanField(
        required=False,
        initial=True,
        label="OPD Book",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    bill_opd_consultation = forms.BooleanField(
        required=False,
        initial=True,
        label="OPD Consultation",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    class Meta:
        model = Patient
        fields = [
            'first_name', 'last_name',
            'id_type', 'id_number', 'national_id', 'passport_number', 'birth_certificate_number',
            'cr_id', 'date_of_birth', 'gender',
            'phone', 'email',
            'country', 'county', 'sub_county', 'ward', 'village', 'postal_address', 'location',
            'insurance_number',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'id_type': forms.Select(attrs={'class': 'form-control'}),
            'id_number': forms.TextInput(attrs={'class': 'form-control'}),
            'national_id': forms.TextInput(attrs={'class': 'form-control'}),
            'passport_number': forms.TextInput(attrs={'class': 'form-control'}),
            'birth_certificate_number': forms.TextInput(attrs={'class': 'form-control'}),
            'cr_id': forms.TextInput(attrs={
                'class': 'form-control',
                'readonly': 'readonly',
                'placeholder': 'Filled from SHA Check',
            }),
            'date_of_birth': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'country': forms.TextInput(attrs={'class': 'form-control'}),
            'county': forms.Select(attrs={'class': 'form-control'}),
            'sub_county': forms.TextInput(attrs={'class': 'form-control'}),
            'ward': forms.TextInput(attrs={'class': 'form-control'}),
            'village': forms.TextInput(attrs={'class': 'form-control'}),
            'postal_address': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'insurance_number': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        from .knhts_demographics import COUNTY_CHOICES

        super().__init__(*args, **kwargs)
        self.fields['county'].widget = forms.Select(
            choices=COUNTY_CHOICES,
            attrs={'class': 'form-control'},
        )
        self.fields['county'].required = False
        self.fields['location'].required = False
        self.fields['location'].help_text = (
            "Auto-filled from county / sub-county / ward / village if left blank"
        )
        self.fields['id_type'].help_text = "Primary ID used for SHA / Client Registry lookup"
        self.fields['national_id'].help_text = "National ID (adults)"
        self.fields['passport_number'].help_text = "Passport number"
        self.fields['birth_certificate_number'].help_text = "Birth certificate (under 18)"
        self.fields['gender'].label = "Sex / Gender (KNHTS)"
        self.fields['insurance_number'].help_text = "SHA/SHIF or other insurance member number"

        if self.instance.pk:
            self.fields['consultation_type'].required = False
            self.fields['payment_method'].required = False

    def clean(self):
        cleaned = super().clean()
        id_type = cleaned.get('id_type') or 'NATIONAL_ID'
        id_number = (cleaned.get('id_number') or '').strip()
        national_id = (cleaned.get('national_id') or '').strip()
        passport = (cleaned.get('passport_number') or '').strip()
        birth_cert = (cleaned.get('birth_certificate_number') or '').strip()

        # Prefer explicit typed document fields; sync into primary id_number
        if id_type == 'NATIONAL_ID' and national_id and not id_number:
            cleaned['id_number'] = national_id
        elif id_type == 'PASSPORT' and passport and not id_number:
            cleaned['id_number'] = passport
        elif id_type == 'BIRTH_CERTIFICATE' and birth_cert and not id_number:
            cleaned['id_number'] = birth_cert

        # If primary number entered, mirror into the matching document field
        primary = (cleaned.get('id_number') or '').strip()
        if primary:
            if id_type == 'NATIONAL_ID' and not national_id:
                cleaned['national_id'] = primary
            elif id_type == 'PASSPORT' and not passport:
                cleaned['passport_number'] = primary
            elif id_type == 'BIRTH_CERTIFICATE' and not birth_cert:
                cleaned['birth_certificate_number'] = primary

        from .knhts_demographics import format_residence_location
        location = (cleaned.get('location') or '').strip()
        structured = format_residence_location(
            village=cleaned.get('village') or '',
            ward=cleaned.get('ward') or '',
            sub_county=cleaned.get('sub_county') or '',
            county=cleaned.get('county') or '',
            postal_address=cleaned.get('postal_address') or '',
        )
        if not location and structured:
            cleaned['location'] = structured[:200]
        elif not location:
            cleaned['location'] = 'Not specified'

        return cleaned

from .models import Symptoms, Impression, Diagnosis, Referral, TBScreening
 
class TBScreeningForm(forms.ModelForm):
    """Form for compulsory TB screening — each symptom uses explicit Yes/No."""

    YES_NO = [(True, 'Yes'), (False, 'No')]

    class Meta:
        model = TBScreening
        fields = [
            'has_cough', 'has_chest_pain', 'has_night_sweats',
            'has_unexplained_fever', 'has_weight_loss', 'failure_to_thrive',
        ]

    def __init__(self, *args, **kwargs):
        self.show_failure_to_thrive = kwargs.pop('show_failure_to_thrive', True)
        super().__init__(*args, **kwargs)
        for field_name in self.Meta.fields:
            if field_name == 'failure_to_thrive' and not self.show_failure_to_thrive:
                del self.fields[field_name]
                continue
            label = self.fields[field_name].label
            initial = None
            if self.instance and self.instance.pk:
                initial = getattr(self.instance, field_name)
            self.fields[field_name] = forms.TypedChoiceField(
                choices=self.YES_NO,
                coerce=self._coerce_bool,
                empty_value=None,
                widget=forms.RadioSelect,
                required=True,
                label=label,
                initial=initial,
            )

    @staticmethod
    def _coerce_bool(value):
        if isinstance(value, bool):
            return value
        return str(value).lower() == 'true'


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
            'data': forms.Textarea(attrs={
                'class': 'icd-diagnosis-value hidden',
                'rows': 2,
                'placeholder': 'ICD-11 diagnosis will be set from search…',
            }),
        }

    def clean_data(self):
        from .icd11_diagnosis import validate_and_resolve_diagnosis

        value = self.cleaned_data.get('data')
        _code, display, entry = validate_and_resolve_diagnosis(value, required=True)
        self._icd11_entry = entry
        return display

    def save(self, commit=True):
        diagnosis = super().save(commit=False)
        entry = getattr(self, '_icd11_entry', None)
        if entry:
            diagnosis.icd11_code = entry.code
            diagnosis.icd11_entry = entry
        if commit:
            diagnosis.save()
        return diagnosis

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


class ProblemForm(forms.ModelForm):
    """KNHTS / KPS Condition problem-list item form (ICD-11 coded)."""

    class Meta:
        model = Problem
        fields = [
            'display', 'clinical_status', 'verification_status', 'category',
            'severity', 'onset_date', 'abatement_date', 'notes',
        ]
        widgets = {
            'display': forms.Textarea(attrs={
                'class': 'icd-diagnosis-value hidden',
                'rows': 2,
                'placeholder': 'ICD-11 diagnosis will be set from search…',
            }),
            'clinical_status': forms.Select(attrs={'class': 'form-control'}),
            'verification_status': forms.Select(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'severity': forms.Select(attrs={'class': 'form-control'}),
            'onset_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'abatement_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['display'].label = 'Problem / Diagnosis (ICD-11)'
        self.fields['clinical_status'].help_text = 'KPS clinicalStatus (required)'
        self.fields['verification_status'].help_text = 'KPS verificationStatus'
        for name in (
            'clinical_status', 'verification_status', 'category',
            'severity', 'onset_date', 'abatement_date', 'notes',
        ):
            self.fields[name].widget.attrs.setdefault('class', 'form-control')

    def clean_display(self):
        from .icd11_diagnosis import validate_and_resolve_diagnosis

        value = self.cleaned_data.get('display')
        _code, display, entry = validate_and_resolve_diagnosis(value, required=True)
        self._icd11_entry = entry
        self._icd11_code = _code
        return display

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get('clinical_status')
        abatement = cleaned.get('abatement_date')
        if status in ('resolved', 'remission', 'inactive') and not abatement:
            # Soft guidance — allow blank but preferred
            pass
        if status in ('active', 'recurrence', 'relapse') and abatement:
            cleaned['abatement_date'] = None
        return cleaned

    def save(self, commit=True):
        problem = super().save(commit=False)
        entry = getattr(self, '_icd11_entry', None)
        code = getattr(self, '_icd11_code', '') or ''
        if entry:
            problem.icd11_code = entry.code
            problem.icd11_entry = entry
        elif code:
            problem.icd11_code = code
        if commit:
            problem.save()
        return problem


class PatientMedicationForm(forms.ModelForm):
    """Longitudinal active / historical medication (HPT GE* preferred)."""

    class Meta:
        model = PatientMedication
        fields = [
            'display_name',
            'generic_concept_code',
            'generic_concept_display',
            'actual_product_code',
            'dose_text',
            'frequency',
            'route',
            'instructions',
            'status',
            'start_date',
            'end_date',
            'notes',
        ]
        widgets = {
            'display_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Drug name'}),
            'generic_concept_code': forms.HiddenInput(),
            'generic_concept_display': forms.HiddenInput(),
            'actual_product_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional PH* pack code',
            }),
            'dose_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 500 mg'}),
            'frequency': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. BD'}),
            'route': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Oral'}),
            'instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_display_name(self):
        name = (self.cleaned_data.get('display_name') or '').strip()
        if not name:
            raise forms.ValidationError('Medication name is required.')
        return name

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get('status')
        end = cleaned.get('end_date')
        if status == 'active' and end:
            cleaned['end_date'] = None
        return cleaned


class PatientAllergyForm(forms.ModelForm):
    """Allergy / intolerance list with optional HPT allergen coding."""

    class Meta:
        model = PatientAllergy
        fields = [
            'allergen_name',
            'hpt_code',
            'hpt_display',
            'hpt_kind',
            'icd11_code',
            'icd11_display',
            'allergy_type',
            'category',
            'clinical_status',
            'criticality',
            'severity',
            'reaction',
            'onset_date',
            'notes',
        ]
        widgets = {
            'allergen_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Allergen name (search HPT or type free text)',
            }),
            'hpt_code': forms.HiddenInput(),
            'hpt_display': forms.HiddenInput(),
            'hpt_kind': forms.HiddenInput(),
            'icd11_code': forms.HiddenInput(),
            'icd11_display': forms.HiddenInput(),
            'allergy_type': forms.Select(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'clinical_status': forms.Select(attrs={'class': 'form-control'}),
            'criticality': forms.Select(attrs={'class': 'form-control'}),
            'severity': forms.Select(attrs={'class': 'form-control'}),
            'reaction': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. rash, anaphylaxis, angioedema',
            }),
            'onset_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_allergen_name(self):
        name = (self.cleaned_data.get('allergen_name') or '').strip()
        if not name:
            raise forms.ValidationError('Allergen name is required.')
        return name


class FamilyHistoryForm(forms.ModelForm):
    """Structured family history (CPOE)."""

    class Meta:
        model = FamilyHistory
        fields = [
            'relationship', 'relative_name', 'condition',
            'icd11_code', 'icd11_display',
            'onset_age', 'is_deceased', 'contributed_to_death', 'notes', 'status',
        ]
        widgets = {
            'relationship': forms.Select(attrs={'class': 'form-control'}),
            'relative_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional name'}),
            'condition': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Diabetes mellitus, Hypertension, Breast cancer',
            }),
            'icd11_code': forms.HiddenInput(attrs={'class': 'icd-family-code'}),
            'icd11_display': forms.HiddenInput(attrs={'class': 'icd-family-display'}),
            'onset_age': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 120}),
            'is_deceased': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'contributed_to_death': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean_condition(self):
        value = (self.cleaned_data.get('condition') or '').strip()
        if not value:
            raise forms.ValidationError('Condition is required.')
        return value
