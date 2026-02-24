from django import forms
from django.utils import timezone
from .models import Deceased, NextOfKin, MorgueAdmission, PerformedMortuaryService, MortuaryDischarge
from accounts.models import Service


class DeceasedAdmissionForm(forms.ModelForm):
    """Combined form for creating deceased and admission records"""
    
    admission_datetime = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        help_text="Date and time when deceased was admitted to morgue"
    )
    
    class Meta:
        model = Deceased
        fields = [
            'deceased_type', 'surname', 'other_names', 'sex', 'scheme', 'id_type', 'id_number',
            'physical_address', 'residence', 'town', 'nationality',
            'date_of_death', 'time_of_death', 'place_of_death', 'cause_of_death',
            'storage_area', 'storage_chamber', 'expected_removal_date', 'tag'
        ]
        widgets = {
            'date_of_death': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'time_of_death': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'expected_removal_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'cause_of_death': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'physical_address': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'surname': forms.TextInput(attrs={'class': 'form-control'}),
            'other_names': forms.TextInput(attrs={'class': 'form-control'}),
            'id_number': forms.TextInput(attrs={'class': 'form-control'}),
            'residence': forms.TextInput(attrs={'class': 'form-control'}),
            'town': forms.TextInput(attrs={'class': 'form-control'}),
            'nationality': forms.TextInput(attrs={'class': 'form-control'}),
            'place_of_death': forms.TextInput(attrs={'class': 'form-control'}),
            'tag': forms.TextInput(attrs={'class': 'form-control'}),
            'storage_area': forms.Select(attrs={'class': 'form-control'}),
            'storage_chamber': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name not in ['cause_of_death', 'physical_address', 'admission_datetime']:
                field.widget.attrs['class'] = 'form-control'
        
        # Set admission_datetime to current time if not provided
        if not self.instance.pk and not self.initial.get('admission_datetime'):
            self.initial['admission_datetime'] = timezone.now()
    
    def save(self, commit=True):
        deceased = super().save(commit=False)
        
        # Create admission record if this is a new deceased
        if not deceased.pk:
            deceased.save()  # Save first to get the ID
            
            # Create MorgueAdmission record
            from .models import MorgueAdmission
            import uuid
            
            admission_datetime = self.cleaned_data.get('admission_datetime', timezone.now())
            admission_number = f"ADM-{timezone.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
            
            MorgueAdmission.objects.create(
                deceased=deceased,
                admission_number=admission_number,
                admission_datetime=admission_datetime,
                created_by=self.instance.created_by if hasattr(self.instance, 'created_by') else None
            )
        
        if commit:
            deceased.save()
        return deceased
    
    def clean_tag(self):
        tag = self.cleaned_data.get('tag')
        if not tag:
            # Generate auto tag if not provided
            surname = self.cleaned_data.get('surname', '')[:3].upper()
            date_str = timezone.now().strftime("%m%d")
            count = Deceased.objects.filter(tag__startswith=f"{surname}{date_str}").count()
            tag = f"{surname}{date_str}{count+1:02d}"
        return tag
    
    def clean(self):
        cleaned_data = super().clean()
        date_of_death = cleaned_data.get('date_of_death')
        time_of_death = cleaned_data.get('time_of_death')
        expected_removal_date = cleaned_data.get('expected_removal_date')
        admission_datetime = cleaned_data.get('admission_datetime')
        
        if expected_removal_date and date_of_death:
            if expected_removal_date < date_of_death:
                raise forms.ValidationError("Expected removal date cannot be before date of death.")
        
        # Validate that time of death is not in the future
        if date_of_death and time_of_death:
            import datetime
            datetime_of_death = datetime.datetime.combine(date_of_death, time_of_death)
            if datetime_of_death > timezone.now():
                raise forms.ValidationError("Date and time of death cannot be in the future.")
        
        # Validate admission datetime is not before death
        if admission_datetime and date_of_death and time_of_death:
            datetime_of_death = datetime.datetime.combine(date_of_death, time_of_death)
            if admission_datetime < datetime_of_death:
                raise forms.ValidationError("Admission datetime cannot be before date and time of death.")
        
        return cleaned_data


class DeceasedForm(forms.ModelForm):
    """Form for creating and updating deceased records"""
    
    class Meta:
        model = Deceased
        fields = [
            'deceased_type', 'surname', 'other_names', 'sex', 'scheme', 'id_type', 'id_number',
            'physical_address', 'residence', 'town', 'nationality',
            'date_of_death', 'time_of_death', 'place_of_death', 'cause_of_death',
            'storage_area', 'storage_chamber', 'expected_removal_date', 'tag'
        ]
        widgets = {
            'date_of_death': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'time_of_death': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'expected_removal_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'cause_of_death': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'physical_address': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'surname': forms.TextInput(attrs={'class': 'form-control'}),
            'other_names': forms.TextInput(attrs={'class': 'form-control'}),
            'id_number': forms.TextInput(attrs={'class': 'form-control'}),
            'residence': forms.TextInput(attrs={'class': 'form-control'}),
            'town': forms.TextInput(attrs={'class': 'form-control'}),
            'nationality': forms.TextInput(attrs={'class': 'form-control'}),
            'place_of_death': forms.TextInput(attrs={'class': 'form-control'}),
            'tag': forms.TextInput(attrs={'class': 'form-control'}),
            'storage_area': forms.Select(attrs={'class': 'form-control'}),
            'storage_chamber': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name not in ['cause_of_death', 'physical_address']:
                field.widget.attrs['class'] = 'form-control'
    
    def clean_tag(self):
        tag = self.cleaned_data.get('tag')
        if not tag:
            # Generate auto tag if not provided
            surname = self.cleaned_data.get('surname', '')[:3].upper()
            date_str = timezone.now().strftime("%m%d")
            count = Deceased.objects.filter(tag__startswith=f"{surname}{date_str}").count()
            tag = f"{surname}{date_str}{count+1:02d}"
        return tag
    
    def clean(self):
        cleaned_data = super().clean()
        date_of_death = cleaned_data.get('date_of_death')
        time_of_death = cleaned_data.get('time_of_death')
        expected_removal_date = cleaned_data.get('expected_removal_date')
        
        if expected_removal_date and date_of_death:
            if expected_removal_date < date_of_death:
                raise forms.ValidationError("Expected removal date cannot be before date of death.")
        
        # Validate that time of death is not in the future
        if date_of_death and time_of_death:
            import datetime
            datetime_of_death = datetime.datetime.combine(date_of_death, time_of_death)
            if datetime_of_death > timezone.now():
                raise forms.ValidationError("Date and time of death cannot be in the future.")
        
        return cleaned_data


class NextOfKinForm(forms.ModelForm):
    """Form for creating next of kin records"""
    
    class Meta:
        model = NextOfKin
        fields = ['name', 'id_type', 'id_number', 'relationship', 'phone', 'email', 'address', 'is_primary']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'id_number': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'is_primary': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name != 'is_primary':
                field.widget.attrs['class'] = 'form-control'


class MorgueAdmissionForm(forms.ModelForm):
    """Form for morgue admission records"""
    
    class Meta:
        model = MorgueAdmission
        fields = ['status', 'release_date', 'released_to', 'release_notes']
        widgets = {
            'release_date': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'released_to': forms.TextInput(attrs={'class': 'form-control'}),
            'release_notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'


class ReleaseForm(forms.Form):
    """Form for releasing deceased from morgue"""
    
    released_to = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Person/organization released to'}),
        required=True
    )
    release_notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Release notes (optional)'}),
        required=False
    )


class PerformedMortuaryServiceForm(forms.ModelForm):
    """Form for recording mortuary services performed"""
    
    class Meta:
        model = PerformedMortuaryService
        fields = ['service', 'quantity']
        widgets = {
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from accounts.models import Service
        # Filter services to only show Mortuary category services
        self.fields['service'].queryset = Service.objects.filter(
            department__name='Morgue'
        ).order_by('name')
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'

class MortuaryDischargeForm(forms.ModelForm):
    """Form for formal mortuary discharge"""
    
    class Meta:
        model = MortuaryDischarge
        fields = ['released_to', 'relationship', 'receiver_id_number', 'receiver_phone', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional discharge notes...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})
            field.required = True
        
        self.fields['notes'].required = False

from .models import Morgue, Chamber

class MorgueForm(forms.ModelForm):
    class Meta:
        model = Morgue
        fields = ['name', 'description', 'base_charge_per_day']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Morgue Name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional details'}),
            'base_charge_per_day': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

class ChamberForm(forms.ModelForm):
    class Meta:
        model = Chamber
        fields = ['morgue', 'chamber_number']
        widgets = {
            'morgue': forms.Select(attrs={'class': 'form-control'}),
            'chamber_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. C-01'}),
        }
