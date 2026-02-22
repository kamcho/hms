from django import forms
from .models import (
    PostnatalMotherVisit, PostnatalBabyVisit, MaternityDischarge, MaternityReferral,
    Vaccine, ImmunizationRecord, Pregnancy, AntenatalVisit, LaborDelivery, Newborn
)
from home.models import Patient
from inpatient.models import Ward, Bed


class PregnancyRegistrationForm(forms.ModelForm):
    class Meta:
        model = Pregnancy
        fields = ['patient', 'lmp', 'edd', 'gravida', 'para', 'abortion', 'living', 
                  'blood_group', 'allergies', 'previous_cs', 'chronic_conditions', 'risk_level']
        widgets = {
            'patient': forms.Select(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'}),
            'lmp': forms.DateInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all', 'type': 'date', 'id': 'id_lmp'}),
            'edd': forms.DateInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 bg-slate-50/50 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all', 'type': 'date', 'id': 'id_edd', 'readonly': 'readonly'}),
            'gravida': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all', 'min': '1'}),
            'para': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all', 'min': '0'}),
            'abortion': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all', 'min': '0'}),
            'living': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all', 'min': '0'}),
            'blood_group': forms.Select(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'}),
            'allergies': forms.Textarea(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all', 'rows': 2}),
            'previous_cs': forms.CheckboxInput(attrs={'class': 'w-5 h-5 border-slate-300 rounded text-blue-600 focus:ring-blue-500 transition-all cursor-pointer'}),
            'chronic_conditions': forms.Textarea(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all', 'rows': 2}),
            'risk_level': forms.Select(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make optional since it might not be known at registration
        self.fields['edd'].required = False
        self.fields['blood_group'].required = False


class AntenatalVisitForm(forms.ModelForm):
    class Meta:
        model = AntenatalVisit
        fields = ['visit', 'visit_date', 'visit_number', 'gestational_age', 'weight', 'bp_systolic', 'bp_diastolic', 
                  'temperature', 'fundal_height', 'fetal_heart_rate', 'fetal_presentation', 'fetal_movements',
                  'hemoglobin', 'blood_sugar', 'urine_protein', 'hiv_status',
                  'iron_supplements', 'folate_supplements', 'deworming', 'tetanus_toxoid',
                  'complaints', 'findings', 'plan', 'next_visit_date']
        widgets = {
            'visit': forms.HiddenInput(),
            'visit_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'visit_number': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'gestational_age': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'bp_systolic': forms.NumberInput(attrs={'class': 'form-control'}),
            'bp_diastolic': forms.NumberInput(attrs={'class': 'form-control'}),
            'temperature': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'fundal_height': forms.NumberInput(attrs={'class': 'form-control'}),
            'fetal_heart_rate': forms.NumberInput(attrs={'class': 'form-control'}),
            'fetal_presentation': forms.Select(attrs={'class': 'form-control'}),
            'fetal_movements': forms.Select(attrs={'class': 'form-control'}),
            'hemoglobin': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'blood_sugar': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'urine_protein': forms.TextInput(attrs={'class': 'form-control'}),
            'hiv_status': forms.Select(attrs={'class': 'form-control'}),
            'iron_supplements': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'folate_supplements': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'deworming': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'tetanus_toxoid': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'complaints': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'findings': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'plan': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'next_visit_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


class LaborDeliveryForm(forms.ModelForm):
    ward = forms.ModelChoiceField(
        queryset=Ward.objects.all(),
        required=False,
        help_text="Select ward for mother admission (optional)"
    )
    
    bed = forms.ModelChoiceField(
        queryset=Bed.objects.filter(is_occupied=False),
        required=False,
        empty_label="Select a Bed (optional)",
        help_text="Select bed for mother admission"
    )
    
    class Meta:
        model = LaborDelivery
        fields = ['admission_date', 'gestational_age_at_delivery', 'labor_onset', 'rupture_of_membranes',
                  'labor_duration', 'delivery_datetime', 'delivery_mode', 'maternal_complications',
                  'episiotomy', 'perineal_tear', 'estimated_blood_loss', 'blood_transfusion',
                  'placenta_delivery', 'mother_condition', 'delivery_notes', 'ward', 'bed']
        widgets = {
            'admission_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'gestational_age_at_delivery': forms.NumberInput(attrs={'class': 'form-control', 'min': '20', 'max': '45'}),
            'labor_onset': forms.Select(attrs={'class': 'form-control'}),
            'rupture_of_membranes': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'labor_duration': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 08:30:00 for 8 hours 30 minutes'}),
            'delivery_datetime': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'delivery_mode': forms.Select(attrs={'class': 'form-control'}),
            'maternal_complications': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'PPH, tears, retained placenta, etc.'}),
            'episiotomy': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'perineal_tear': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Degree of tear (if any)'}),
            'estimated_blood_loss': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'placeholder': 'mL'}),
            'blood_transfusion': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'placenta_delivery': forms.Select(attrs={'class': 'form-control'}),
            'mother_condition': forms.Select(attrs={'class': 'form-control'}),
            'delivery_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Labor progress, delivery summary, etc.'}),
        }
        labels = {
            'rupture_of_membranes': 'Rupture of Membranes (ROM)',
            'estimated_blood_loss': 'Estimated Blood Loss (EBL)',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bed'].queryset = Bed.objects.filter(is_occupied=False).select_related('ward')
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})


class NewbornForm(forms.ModelForm):
    first_name = forms.CharField(
        max_length=100, 
        required=False, 
        label="Baby's First Name",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter baby\'s first name'})
    )
    last_name = forms.CharField(
        max_length=100, 
        required=False, 
        label="Baby's Last Name",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter baby\'s last name'})
    )

    birth_datetime = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={'class': 'form-control', 'type': 'datetime-local'},
            format='%Y-%m-%dT%H:%M'
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        label="Birth Date & Time"
    )

    class Meta:
        model = Newborn
        fields = ['baby_number', 'gender', 'birth_datetime', 'birth_weight', 'birth_length', 
                  'head_circumference', 'apgar_1min', 'apgar_5min', 'apgar_10min',
                  'resuscitation_required', 'resuscitation_details', 'status', 
                  'congenital_abnormalities', 'breastfeeding_initiated', 'bcg_given', 
                  'opv_0_given', 'notes']
        widgets = {
            'baby_number': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'birth_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': 'kg'}),
            'birth_length': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'placeholder': 'cm'}),
            'head_circumference': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'placeholder': 'cm'}),
            'apgar_1min': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '10'}),
            'apgar_5min': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '10'}),
            'apgar_10min': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '10'}),
            'resuscitation_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'resuscitation_details': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'If resuscitation was required, describe the interventions performed'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'congenital_abnormalities': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Any congenital abnormalities noted'}),
            'breastfeeding_initiated': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'bcg_given': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'opv_0_given': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Clinical observations, care plan, etc.'}),
        }
        labels = {
            'baby_number': 'Baby Number (for multiple births)',
            'birth_datetime': 'Birth Date & Time',
            'birth_weight': 'Birth Weight (kg)',
            'birth_length': 'Birth Length (cm)',
            'head_circumference': 'Head Circumference (cm)',
            'apgar_1min': 'APGAR Score at 1 Minute',
            'apgar_5min': 'APGAR Score at 5 Minutes',
            'apgar_10min': 'APGAR Score at 10 Minutes (if applicable)',
            'bcg_given': 'BCG Vaccine Given',
            'opv_0_given': 'OPV 0 Given',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.patient_profile:
            self.fields['first_name'].initial = self.instance.patient_profile.first_name
            self.fields['last_name'].initial = self.instance.patient_profile.last_name

class PostnatalBabyVisitForm(forms.ModelForm):
    class Meta:
        model = PostnatalBabyVisit
        fields = [
            'visit', 'visit_date', 'visit_day', 'weight', 'length', 'head_circumference',
            'temperature', 'feeding_type', 'feeding_well', 'feeding_difficulties',
            'umbilical_cord', 'jaundice', 'jaundice_level', 'skin_condition',
            'eyes', 'vaccines_given', 'alertness', 'complaints', 'findings',
            'plan', 'next_visit_date'
        ]
        widgets = {
            'visit': forms.HiddenInput(),
            'visit_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'visit_day': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 3'}),
            'weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': 'kg'}),
            'length': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'placeholder': 'cm'}),
            'head_circumference': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'placeholder': 'cm'}),
            'temperature': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'placeholder': '°C'}),
            'feeding_type': forms.Select(attrs={'class': 'form-control'}),
            'feeding_well': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'feeding_difficulties': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'umbilical_cord': forms.Select(attrs={'class': 'form-control'}),
            'jaundice': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'jaundice_level': forms.TextInput(attrs={'class': 'form-control'}),
            'skin_condition': forms.TextInput(attrs={'class': 'form-control'}),
            'eyes': forms.TextInput(attrs={'class': 'form-control'}),
            'vaccines_given': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'alertness': forms.Select(attrs={'class': 'form-control'}),
            'complaints': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'findings': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'plan': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'next_visit_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }
        labels = {
            'visit_day': 'Day Post-Delivery',
            'weight': 'Weight (kg)',
            'length': 'Length (cm)',
            'head_circumference': 'Head Circumference (cm)',
        }

class PostnatalMotherVisitForm(forms.ModelForm):
    class Meta:
        model = PostnatalMotherVisit
        fields = [
            'visit', 'visit_date', 'visit_day', 'bp_systolic', 'bp_diastolic', 
            'temperature', 'pulse', 'uterus_involution', 'lochia', 
            'breastfeeding_status', 'perineum_wound', 'cs_wound',
            'family_planning_counseling', 'contraception_method',
            'mood_assessment', 'complaints', 'findings', 'plan', 'next_visit_date'
        ]
        widgets = {
            'visit': forms.HiddenInput(),
            'visit_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'visit_day': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 3'}),
            'bp_systolic': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'mmHg'}),
            'bp_diastolic': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'mmHg'}),
            'temperature': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'placeholder': '°C'}),
            'pulse': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'bpm'}),
            'uterus_involution': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Fundal height/status'}),
            'lochia': forms.Select(attrs={'class': 'form-control'}),
            'breastfeeding_status': forms.Select(attrs={'class': 'form-control'}),
            'perineum_wound': forms.Select(attrs={'class': 'form-control'}),
            'cs_wound': forms.Select(attrs={'class': 'form-control'}),
            'family_planning_counseling': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'contraception_method': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Method discussed/chosen'}),
            'mood_assessment': forms.Select(attrs={'class': 'form-control'}),
            'complaints': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'findings': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'plan': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'next_visit_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }
        labels = {
            'visit_day': 'Day Post-Delivery',
            'bp_systolic': 'Systolic BP',
            'bp_diastolic': 'Diastolic BP',
            'cs_wound': 'C-Section Wound (if applicable)',
        }

class MaternityDischargeForm(forms.ModelForm):
    class Meta:
        model = MaternityDischarge
        fields = [
            'discharge_date', 'mother_condition_at_discharge', 
            'baby_condition_at_discharge', 'final_diagnosis', 
            'discharge_summary', 'follow_up_plan', 'medications_prescribed'
        ]
        widgets = {
            'discharge_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'mother_condition_at_discharge': forms.Select(attrs={'class': 'form-control'}),
            'baby_condition_at_discharge': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Alive and healthy'}),
            'final_diagnosis': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'discharge_summary': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'follow_up_plan': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'medications_prescribed': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'List take-home medications'}),
        }


class MaternityReferralForm(forms.ModelForm):
    class Meta:
        model = MaternityReferral
        fields = [
            'referral_date', 'referred_to_facility', 'department', 
            'reason_for_referral', 'clinical_clinical_summary', 
            'urgent', 'transport_mode'
        ]
        widgets = {
            'referral_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'referred_to_facility': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Receiving Hospital Name'}),
            'department': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. ICU, NICU, Specialized OBGYN'}),
            'reason_for_referral': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'clinical_clinical_summary': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'urgent': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'transport_mode': forms.Select(attrs={'class': 'form-control'}),
        }

class ImmunizationRecordForm(forms.ModelForm):
    class Meta:
        model = ImmunizationRecord
        fields = [
            'vaccine', 'dose_number', 'date_administered', 'batch_number',
            'reaction_observed', 'next_dose_due', 'facility'
        ]
        widgets = {
            'vaccine': forms.Select(attrs={'class': 'form-control'}),
            'dose_number': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'date_administered': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'batch_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. B12345'}),
            'reaction_observed': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'next_dose_due': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'facility': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Facility name if given elsewhere'}),
        }


class ExternalDeliveryForm(forms.Form):
    """Consolidated form for registering a pregnancy and delivery that happened elsewhere"""
    
    # Patient
    patient = forms.ModelChoiceField(
        queryset=Patient.objects.all(),
        widget=forms.Select(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'})
    )
    
    # Pregnancy Info (Essential for history)
    gravida = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'}))
    para = forms.IntegerField(min_value=0, widget=forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'}))
    abortion = forms.IntegerField(min_value=0, initial=0, widget=forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'}))
    living = forms.IntegerField(min_value=0, initial=1, widget=forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'}))
    
    # Delivery Info
    delivery_datetime = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all', 'type': 'datetime-local'})
    )
    
    delivery_mode = forms.ChoiceField(
        choices=LaborDelivery.DELIVERY_MODE_CHOICES,
        widget=forms.Select(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'})
    )
    
    outcome = forms.ChoiceField(
        choices=[('Alive', 'Alive and Well'), ('Stillborn', 'Stillborn'), ('Neonatal Death', 'Neonatal Death')],
        widget=forms.Select(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'})
    )

    number_of_babies = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'})
    )

    child_patient = forms.ModelChoiceField(
        queryset=Patient.objects.all(),
        required=False,
        label="Linked Child Patient (Optional)",
        help_text="Link this delivery record to an existing child patient profile",
        widget=forms.Select(attrs={'class': 'w-full px-4 py-2.5 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-100 focus:border-blue-500 outline-none transition-all'})
    )

    def __init__(self, *args, **kwargs):
        patient_id = kwargs.pop('patient_id', None)
        child_patient_id = kwargs.pop('child_patient_id', None)
        super().__init__(*args, **kwargs)
        if patient_id:
            self.fields['patient'].initial = patient_id
        if child_patient_id:
            self.fields['child_patient'].initial = child_patient_id
