from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone

from .knhts_demographics import (
    CONTACT_ROLE_CHOICES,
    GENDER_CHOICES as KNHTS_GENDER_CHOICES,
    ID_TYPE_CHOICES as KNHTS_ID_TYPE_CHOICES,
)
from .knhts_conditions import (
    CATEGORY_CHOICES as KNHTS_CATEGORY_CHOICES,
    CLINICAL_STATUS_CHOICES as KNHTS_CLINICAL_STATUS_CHOICES,
    HISTORY_ACTION_CHOICES as KNHTS_HISTORY_ACTION_CHOICES,
    SEVERITY_CHOICES as KNHTS_SEVERITY_CHOICES,
    VERIFICATION_STATUS_CHOICES as KNHTS_VERIFICATION_STATUS_CHOICES,
)


class Departments(models.Model):
    name = models.CharField(max_length=100, unique=True)
    hod = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='departments_hod')
    abbreviation = models.CharField(max_length=10, null=True, blank=True, unique=True)

    def __str__(self):
        return self.name


class Patient(models.Model):
    """
    Patient demographics aligned to KPS.A Client Registration / KNHTS.
    Sex uses HL7 Administrative Gender codes (KNHTS required binding).
    """
    GENDER_CHOICES = KNHTS_GENDER_CHOICES
    ID_TYPE_CHOICES = KNHTS_ID_TYPE_CHOICES

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    # Primary government-issued identifier (KPS.A identifier 1..1)
    id_type = models.CharField(
        max_length=20,
        choices=ID_TYPE_CHOICES,
        default='NATIONAL_ID',
        blank=True,
        help_text='Government ID type (National ID, Passport, Birth Certificate, Alien ID)',
    )
    id_number = models.CharField(max_length=50, null=True, blank=True)
    national_id = models.CharField(
        max_length=50, null=True, blank=True,
        help_text='National ID number when available',
    )
    passport_number = models.CharField(
        max_length=50, null=True, blank=True,
        help_text='Passport number when available',
    )
    birth_certificate_number = models.CharField(
        max_length=50, null=True, blank=True,
        help_text='Birth certificate number (typically under 18)',
    )
    # DHA Client Registry ID — one per person (dependents have their own CR ID)
    cr_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text='DHA Client Registry ID (unique per individual, including dependents)',
    )
    date_of_birth = models.DateField()
    age = models.PositiveIntegerField(editable=False)  # Will be calculated automatically
    phone = models.CharField(max_length=15, null=True, blank=True)
    email = models.EmailField(null=True, blank=True, help_text='Patient email (KPS.A telecom)')
    # Free-text display location (kept for legacy screens; synced from structured address)
    location = models.CharField(max_length=200)
    # KPS.A structured residential address
    country = models.CharField(max_length=100, blank=True, default='Kenya')
    county = models.CharField(max_length=100, blank=True, default='')
    sub_county = models.CharField(max_length=100, blank=True, default='')
    ward = models.CharField(max_length=100, blank=True, default='')
    village = models.CharField(max_length=100, blank=True, default='')
    postal_address = models.CharField(
        max_length=255, blank=True, default='',
        help_text='P.O. Box, street or building details',
    )
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='unknown')
    insurance_number = models.CharField(
        max_length=64, null=True, blank=True,
        help_text='Health insurance ID (e.g. SHA/SHIF member number)',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='patients_created')

    def save(self, *args, **kwargs):
        from .knhts_demographics import format_residence_location

        today = timezone.now().date()
        age = today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )
        self.age = age

        # Keep dedicated ID fields in sync with primary identifier
        id_val = (self.id_number or '').strip() or None
        if id_val:
            if self.id_type == 'NATIONAL_ID' and not self.national_id:
                self.national_id = id_val
            elif self.id_type == 'PASSPORT' and not self.passport_number:
                self.passport_number = id_val
            elif self.id_type == 'BIRTH_CERTIFICATE' and not self.birth_certificate_number:
                self.birth_certificate_number = id_val

        structured = format_residence_location(
            village=self.village,
            ward=self.ward,
            sub_county=self.sub_county,
            county=self.county,
            postal_address=self.postal_address,
        )
        if structured and (
            not self.location or self.location in ('Not specified', 'N/A')
        ):
            self.location = structured[:200]
        elif not self.location:
            self.location = structured[:200] if structured else 'Not specified'

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def knhts_gender_code(self):
        """HL7 / KNHTS administrative-gender code for HIE export."""
        return self.gender or 'unknown'

    @property
    def primary_identifier_display(self):
        label = self.get_id_type_display() if self.id_type else 'ID'
        return f"{label}: {self.id_number}" if self.id_number else '—'

class Visit(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('CASH', 'Cash'),
        ('SHA', 'SHA'),
    ]
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='visits')
    visit_date = models.DateTimeField(auto_now_add=True)
    visit_type = models.CharField(max_length=20, choices=[('IN-PATIENT', 'In-Patient'), ('OUT-PATIENT', 'Out-Patient')])
    visit_mode = models.CharField(max_length=20, choices=[('Appointment', 'Appointment'), ('Walk In', 'Walk In')])
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES, default='CASH')
    is_active = models.BooleanField(default=True)
    by_nurse = models.BooleanField(default=False, help_text='Visit created or managed via nurse workflow')
    def __str__(self):
        return f"Visit - {self.patient} ({self.visit_type})"

class TriageEntry(models.Model):
    PRIORITY_CHOICES = [
        ('LOW', 'Low Priority'),
        ('MEDIUM', 'Medium Priority'),
        ('HIGH', 'High Priority'),
        ('URGENT', 'Urgent'),
        ('CRITICAL', 'Critical'),
    ]
    
    CATEGORY_CHOICES = [
        ('GENERAL', 'General'),
        ('EMERGENCY', 'Emergency'),
        ('PEDIATRIC', 'Pediatric'),
        ('MATERNITY', 'Maternity'),
        ('SURGERY', 'Surgery'),
        ('CARDIAC', 'Cardiac'),
        ('NEURO', 'Neurological'),
        ('RESPIRATORY', 'Respiratory'),
        ('ORTHOPEDIC', 'Orthopedic'),
        ('OTHER', 'Other'),
    ]
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='triage_entries')
    triage_nurse = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='triage_entries')
    entry_date = models.DateTimeField(auto_now_add=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='GENERAL')
    
   
    # Vital signs
    temperature = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True, help_text="Temperature in °C")
    blood_pressure_systolic = models.PositiveIntegerField(null=True, blank=True, help_text="Systolic BP (mmHg)")
    blood_pressure_diastolic = models.PositiveIntegerField(null=True, blank=True, help_text="Diastolic BP (mmHg)")
    heart_rate = models.PositiveIntegerField(null=True, blank=True, help_text="Heart rate (bpm)")
    respiratory_rate = models.PositiveIntegerField(null=True, blank=True, help_text="Respiratory rate (breaths/min)")
    oxygen_saturation = models.PositiveIntegerField(null=True, blank=True, help_text="O2 saturation (%)")
    blood_glucose = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, help_text="Blood glucose (mg/dL)")
    weight = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, help_text="Weight (kg)")
    height = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, help_text="Height (cm)")
    # Pain assessment
    
    triage_notes = models.TextField(blank=True, help_text="Triage nurse assessment notes")
    disposition = models.CharField(max_length=100, blank=True, help_text="Disposition (e.g., 'Send to Emergency Room')")
    
    # Status
    is_active = models.BooleanField(default=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-entry_date']
        verbose_name = 'Triage Entry'
        verbose_name_plural = 'Triage Entries'
    
    def __str__(self):
        return f"Triage - {self.visit.patient} ({self.get_priority_display()}) - {self.entry_date.strftime('%Y-%m-%d %H:%M')}"
    
    def get_blood_pressure(self):
        """Return formatted blood pressure"""
        if self.blood_pressure_systolic and self.blood_pressure_diastolic:
            return f"{self.blood_pressure_systolic}/{self.blood_pressure_diastolic}"
        return "Not recorded"
    
    def get_priority_color(self):
        """Return color code for priority"""
        colors = {
            'LOW': '#28a745',
            'MEDIUM': '#ffc107',
            'HIGH': '#fd7e14',
            'URGENT': '#dc3545',
            'CRITICAL': '#6f42c1',
        }
        return colors.get(self.priority, '#6c757d')
    
    def get_vital_signs_status(self):
        """Check if vital signs are normal"""
        issues = []
        
        if self.temperature:
            if self.temperature < 36 or self.temperature > 37.5:
                issues.append(f"Temp: {self.temperature}°C")
        
        if self.blood_pressure_systolic and self.blood_pressure_diastolic:
            if self.blood_pressure_systolic > 140 or self.blood_pressure_diastolic > 90:
                issues.append(f"BP: {self.get_blood_pressure()}")
        
        if self.heart_rate:
            if self.heart_rate < 60 or self.heart_rate > 100:
                issues.append(f"HR: {self.heart_rate}")
        
        if self.oxygen_saturation:
            if self.oxygen_saturation < 95:
                issues.append(f"O2: {self.oxygen_saturation}%")
        
        return issues

    @property
    def bmi(self):
        """Body mass index from weight (kg) and height (cm)."""
        from .bmi_growth import calc_bmi
        return calc_bmi(self.weight, self.height)

    @property
    def bmi_category(self):
        from .bmi_growth import bmi_category
        age = None
        try:
            age = self.visit.patient.age
        except Exception:  # noqa: BLE001
            age = None
        return bmi_category(self.bmi, age_years=age)

    def mark_completed(self):
        """Mark triage entry as completed"""
        self.is_active = False
        self.completed_at = timezone.now()
        self.save()

class PatientQue(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    TYPE_CHOICES = [
        ('INITIAL', 'New Visit'),
        ('REVIEW', 'Results Review'),
    ]

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='patient_queue')
    qued_from = models.ForeignKey(Departments, on_delete=models.SET_NULL, null=True, related_name='patient_from_queue')
    sent_to = models.ForeignKey(Departments, on_delete=models.SET_NULL, null=True, related_name='patient_queue')    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    queue_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='INITIAL')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='patient_queue_created')
    updated_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='patient_queue_updated')

class Consultation(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='consultations')
    doctor = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='consultations')
    checkin_date = models.DateTimeField(auto_now_add=True)
    checkout_date = models.DateTimeField(null=True, blank=True)
    

    def __str__(self):
        return f"Consultation - {self.visit.patient} ({self.doctor}) - {self.checkin_date.strftime('%Y-%m-%d %H:%M')}"


class Symptoms(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='symptoms')
    data = models.TextField()
    days = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='symptoms_created')
    updated_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='symptoms_updated')

class Impression(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='impressions')
    data = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='impressions_created')
    updated_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='impressions_updated')


class Diagnosis(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='diagnoses')
    data = models.TextField()
    icd11_code = models.CharField(max_length=32, blank=True, db_index=True)
    icd11_entry = models.ForeignKey(
        'Icd11Code',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='visit_diagnoses',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='diagnoses_created')
    updated_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='diagnoses_updated')

class ConsultationNotes(models.Model):
    consultation = models.ForeignKey(Consultation, on_delete=models.CASCADE, related_name='consultation_notes')
    notes = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='consultation_notes_created')
    updated_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='consultation_notes_updated')

class Appointments(models.Model):
    patient = models.ForeignKey('Patient', on_delete=models.CASCADE, related_name='appointments')
    appointment_date = models.DateTimeField()
    appointment_type = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='appointments_created')
    updated_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='appointments_updated')
    is_completed = models.BooleanField(default=False)
    def __str__(self):
        return f"{self.patient.full_name} - {self.appointment_date}"

class EmergencyContact(models.Model):
    """
    Next of kin / contact person — KPS.A contactPerson.
    role uses KPSPatientContactRelationship (HL7 v2-0131); relationship is free-text kinship.
    """
    RELATIONSHIP_CHOICES = [
        ('SPOUSE', 'Spouse'),
        ('PARENT', 'Parent'),
        ('CHILD', 'Child'),
        ('SIBLING', 'Sibling'),
        ('GRANDPARENT', 'Grandparent'),
        ('GRANDCHILD', 'Grandchild'),
        ('UNCLE_AUNT', 'Uncle/Aunt'),
        ('COUSIN', 'Cousin'),
        ('FRIEND', 'Friend'),
        ('GUARDIAN', 'Guardian'),
        ('OTHER', 'Other'),
    ]
    ROLE_CHOICES = CONTACT_ROLE_CHOICES

    patient = models.ForeignKey('Patient', on_delete=models.CASCADE, related_name='emergency_contacts')
    # KPS.A contactPerson.name.given / family (optional split; name kept for display)
    given_name = models.CharField(max_length=100, blank=True, default='', help_text='First name')
    family_name = models.CharField(max_length=100, blank=True, default='', help_text='Surname')
    name = models.CharField(max_length=200, help_text="Full name of contact person")
    role = models.CharField(
        max_length=5,
        choices=ROLE_CHOICES,
        default='N',
        help_text='KPS contact role (Next-of-Kin, Emergency Contact, …)',
    )
    relationship = models.CharField(
        max_length=20,
        choices=RELATIONSHIP_CHOICES,
        help_text="Relationship to patient (e.g. father, spouse)",
    )
    phone = models.CharField(max_length=20, help_text="Contact phone number")
    email = models.EmailField(blank=True, help_text="Contact email address")
    address = models.TextField(blank=True, help_text="Contact address")
    is_primary = models.BooleanField(default=False, help_text="Primary next of kin / emergency contact")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, related_name='emergency_contacts_created'
    )

    class Meta:
        ordering = ['-is_primary', 'name']
        verbose_name = "Next of Kin / Emergency Contact"
        verbose_name_plural = "Next of Kin / Emergency Contacts"

    def save(self, *args, **kwargs):
        if not self.name and (self.given_name or self.family_name):
            self.name = f"{self.given_name} {self.family_name}".strip()
        elif self.name and not (self.given_name or self.family_name):
            parts = self.name.strip().split(None, 1)
            self.given_name = parts[0] if parts else ''
            self.family_name = parts[1] if len(parts) > 1 else ''
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} - {self.get_relationship_display()} of {self.patient.full_name}"
    

class Prescription(models.Model):
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Completed', 'Completed'),
        ('Cancelled', 'Cancelled'),
    ]
    
    patient = models.ForeignKey('Patient', on_delete=models.CASCADE, related_name='prescriptions')
    visit = models.ForeignKey('Visit', on_delete=models.SET_NULL, null=True, blank=True, related_name='prescriptions')
    invoice = models.ForeignKey('accounts.Invoice', on_delete=models.SET_NULL, null=True, blank=True, related_name='prescriptions')
    prescribed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='prescriptions_written')
    prescribed_at = models.DateTimeField(auto_now_add=True)
    diagnosis = models.TextField(help_text="ICD-11 diagnosis (CODE — Title)")
    icd11_code = models.CharField(max_length=32, blank=True, db_index=True)
    icd11_entry = models.ForeignKey(
        'Icd11Code',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='prescriptions',
    )
    notes = models.TextField(blank=True, help_text="Additional instructions or notes")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')

    # Electronic prescribing clinical context (checklist extras beyond drug items)
    problem_list_snapshot = models.JSONField(default=list, blank=True)
    medication_list_snapshot = models.JSONField(default=list, blank=True)
    diagnostic_tests_snapshot = models.JSONField(default=list, blank=True)
    erx_clinical_context = models.JSONField(default=dict, blank=True)
    includes_problem_list = models.BooleanField(default=False)
    includes_medication_list = models.BooleanField(default=False)
    includes_diagnostic_tests = models.BooleanField(default=False)
    erx_transmitted_at = models.DateTimeField(null=True, blank=True)
    erx_transmission_raw = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-prescribed_at']
        verbose_name = "Prescription"
        verbose_name_plural = "Prescriptions"
    
    @property
    def total_amount(self):
        return sum(item.total_price for item in self.items.all())

    def __str__(self):
        return f"Prescription for {self.patient.full_name} - {self.prescribed_at.strftime('%Y-%m-%d')}"


class PrescriptionItem(models.Model):

    frequency_choices = [
        ('Once Daily', 'Once Daily'),
        ('Twice Daily', 'Twice Daily'),
        ('Thrice Daily', 'Thrice Daily'),
        ('Four Times Daily', 'Four Times Daily'),
        ('Every 6 Hours', 'Every 6 Hours'),
        ('Every 8 Hours', 'Every 8 Hours'),
        ('Every 12 Hours', 'Every 12 Hours'),
        ('Every 24 Hours', 'Every 24 Hours'),
        ('As Needed', 'As Needed'),
    ]
    prescription = models.ForeignKey('Prescription', on_delete=models.CASCADE, related_name='items')
    medication = models.ForeignKey('inventory.InventoryItem', on_delete=models.PROTECT, related_name='prescription_items')
    # DHA / SHA eRx coding — MOH-PPB HPT generic product (e.g. GE10002)
    generic_concept_code = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="DHA HPT generic_concept_code (prefer GE* product codes)",
    )
    generic_concept_display = models.CharField(
        max_length=255,
        blank=True,
        help_text="DHA display name for the selected generic product",
    )
    # Snapshot at dispense — DHA actual_product_code (PH* / pack)
    actual_product_code = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="DHA HPT pack / actual_product_code used at dispense",
    )
    
    # Numeric components for auto-calculation and record keeping
    dose_count = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Units per dose (e.g., 2 tablets or 5.5 ml)")
    dose_unit = models.CharField(max_length=20, blank=True, null=True, help_text="Unit of dose (e.g., ml, g, mg)")
    frequency = models.CharField(max_length=20, choices=frequency_choices, default='Once Daily', help_text="Frequency of medication")
    number_of_days = models.IntegerField(help_text="Number of days to take the medication", null=True, blank=True)
    quantity = models.IntegerField(help_text="Total units to dispense", null=True, blank=True)
    instructions = models.TextField(blank=True, help_text="Special instructions for this medication")
    dispensed = models.BooleanField(default=False, help_text="Has this been dispensed by pharmacy?")
    dispensed_at = models.DateTimeField(null=True, blank=True)
    dispensed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='medications_dispensed')
    
    class Meta:
        verbose_name = "Prescription Item"
        verbose_name_plural = "Prescription Items"

    def save(self, *args, **kwargs):
        # Auto-calculate quantity based on dose, frequency and days
        if self.medication:
            if self.medication.is_dispensed_as_whole:
                # If quantity is not set, default to 1 for items dispensed as whole
                if self.quantity is None:
                    self.quantity = 1
            elif self.frequency != 'As Needed' and self.number_of_days:
                freq_map = {
                    'Once Daily': 1,
                    'Twice Daily': 2,
                    'Thrice Daily': 3,
                    'Four Times Daily': 4,
                    'Every 6 Hours': 4,
                    'Every 8 Hours': 3,
                    'Every 12 Hours': 2,
                    'Every 24 Hours': 1
                }
                multiplier = freq_map.get(self.frequency)
                if multiplier and self.dose_count is not None:
                    # Auto-calculate only when dose is specified; explicit quantity is kept otherwise
                    self.quantity = int(float(self.dose_count) * multiplier * self.number_of_days)
                elif self.quantity is None:
                    self.quantity = 1
        
        super().save(*args, **kwargs)
    
    @property
    def total_price(self):
        if self.medication and self.medication.selling_price:
            return self.quantity * self.medication.selling_price
        return 0

    def __str__(self):
        return f"{self.medication.name} - {self.dose_count} x {self.frequency}"

class Referral(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='referrals')
    doctor = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='referrals_created')
    referral_date = models.DateTimeField(auto_now_add=True)
    destination = models.CharField(max_length=255, help_text="Where the patient is being referred to (Hospital/Clinic Name)")
    reason = models.TextField(help_text="Reason for referral")
    clinical_summary = models.TextField(blank=True, help_text="Summary of clinical findings")
    notes = models.TextField(blank=True, help_text="Additional notes for the receiving doctor")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Referral for {self.visit.patient.full_name} to {self.destination}"


class ProcedureCompletion(models.Model):
    """
    Tracks completion of a billed procedure without changing InvoiceItem schema.
    """
    visit = models.ForeignKey('Visit', on_delete=models.CASCADE, related_name='procedure_completions')
    invoice_item = models.OneToOneField('accounts.InvoiceItem', on_delete=models.CASCADE, related_name='procedure_completion')
    completed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='procedure_completions_done')
    completed_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-completed_at']

    def __str__(self):
        return f"Procedure completion for Visit #{self.visit_id} - Item #{self.invoice_item_id}"

class Icd11Code(models.Model):
    """
    Local copy of WHO ICD-11 MMS linearization for fast offline search.

    Populated via `python manage.py sync_icd11` from the WHO Simple Tabulation release file.
    """
    CLASS_CHAPTER = 'chapter'
    CLASS_BLOCK = 'block'
    CLASS_CATEGORY = 'category'
    CLASS_KIND_CHOICES = [
        (CLASS_CHAPTER, 'Chapter'),
        (CLASS_BLOCK, 'Block'),
        (CLASS_CATEGORY, 'Category'),
    ]

    release = models.CharField(max_length=20, db_index=True)
    linearization = models.CharField(max_length=20, default='mms', db_index=True)
    foundation_uri = models.URLField(max_length=255, blank=True)
    linearization_uri = models.URLField(max_length=255)
    entity_id = models.CharField(max_length=64, blank=True, db_index=True)
    code = models.CharField(max_length=32, blank=True, db_index=True)
    block_id = models.CharField(max_length=32, blank=True)
    title = models.CharField(max_length=500)
    title_plain = models.CharField(max_length=500, blank=True, db_index=True)
    class_kind = models.CharField(max_length=16, choices=CLASS_KIND_CHOICES, blank=True)
    depth_in_kind = models.PositiveSmallIntegerField(null=True, blank=True)
    is_residual = models.BooleanField(default=False)
    chapter_no = models.CharField(max_length=8, blank=True, db_index=True)
    is_leaf = models.BooleanField(default=False)
    is_primary_tabulation = models.BooleanField(default=False)

    class Meta:
        ordering = ['code', 'title']
        constraints = [
            models.UniqueConstraint(
                fields=['release', 'linearization', 'linearization_uri'],
                name='home_icd11code_release_lin_uri_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['release', 'linearization', 'code']),
            models.Index(fields=['release', 'linearization', 'title_plain']),
        ]

    def __str__(self):
        if self.code:
            return f'{self.code} — {self.title_plain or self.title}'
        return self.title_plain or self.title

    def to_search_result(self) -> dict:
        return {
            'id': self.entity_id or None,
            'uri': self.foundation_uri or self.linearization_uri,
            'title': self.title_plain or self.title,
            'code': self.code or None,
            'is_leaf': self.is_leaf,
            'chapter': self.chapter_no or None,
        }

    def to_entity_dict(self) -> dict:
        return {
            'id': self.entity_id or None,
            'uri': self.foundation_uri or self.linearization_uri,
            'title': self.title_plain or self.title,
            'code': self.code or None,
            'definition': None,
            'class_kind': self.class_kind or None,
            'is_leaf': self.is_leaf,
            'parent': None,
            'child': None,
        }


class TBScreening(models.Model):
    visit = models.OneToOneField(Visit, on_delete=models.CASCADE, related_name='tb_screening')
    has_cough = models.BooleanField(default=False, verbose_name="Cough")
    has_chest_pain = models.BooleanField(default=False, verbose_name="Chest Pain")
    has_night_sweats = models.BooleanField(default=False, verbose_name="Night Sweats")
    has_unexplained_fever = models.BooleanField(default=False, verbose_name="Unexplained Fever")
    has_weight_loss = models.BooleanField(default=False, verbose_name="Weight Loss")
    failure_to_thrive = models.BooleanField(default=False, verbose_name="Failure to Thrive (in children)")
    
    screened_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='tb_screenings')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"TB Screening for {self.visit.patient.full_name}"


class Problem(models.Model):
    """
    Patient Problem List item — KPS Condition (problem-list-item).

    Coded with ICD-11 via local KNHTS/DHA terminology sync.
    clinical_status and verification_status use FHIR/KPS required bindings.
    """
    CLINICAL_STATUS_CHOICES = KNHTS_CLINICAL_STATUS_CHOICES
    VERIFICATION_STATUS_CHOICES = KNHTS_VERIFICATION_STATUS_CHOICES
    CATEGORY_CHOICES = KNHTS_CATEGORY_CHOICES
    SEVERITY_CHOICES = KNHTS_SEVERITY_CHOICES

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='problems')
    visit = models.ForeignKey(
        Visit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='problems',
        help_text='Encounter where this problem was recorded or last updated',
    )
    source_diagnosis = models.ForeignKey(
        'Diagnosis',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='problems',
        help_text='Visit diagnosis that seeded this problem list item',
    )

    display = models.CharField(max_length=512, help_text='ICD-11 display: CODE — Title')
    icd11_code = models.CharField(max_length=32, blank=True, db_index=True)
    icd11_entry = models.ForeignKey(
        'Icd11Code',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='problems',
    )

    clinical_status = models.CharField(
        max_length=20,
        choices=CLINICAL_STATUS_CHOICES,
        default='active',
        db_index=True,
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='confirmed',
    )
    category = models.CharField(
        max_length=32,
        choices=CATEGORY_CHOICES,
        default='problem-list-item',
    )
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, blank=True, default='')

    onset_date = models.DateField(null=True, blank=True)
    abatement_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    recorded_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, related_name='problems_recorded'
    )
    updated_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='problems_updated'
    )

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Problem'
        verbose_name_plural = 'Problem List'
        indexes = [
            models.Index(fields=['patient', 'clinical_status']),
            models.Index(fields=['patient', 'icd11_code']),
        ]

    def __str__(self):
        return f"{self.icd11_code or '—'} {self.display} [{self.clinical_status}]"

    @property
    def is_active(self):
        from .knhts_conditions import ACTIVE_CLINICAL_STATUSES
        return self.clinical_status in ACTIVE_CLINICAL_STATUSES

    def record_history(self, *, action, changed_by=None, change_summary=''):
        return ProblemHistory.objects.create(
            problem=self,
            action=action,
            display=self.display,
            icd11_code=self.icd11_code,
            clinical_status=self.clinical_status,
            verification_status=self.verification_status,
            severity=self.severity,
            onset_date=self.onset_date,
            abatement_date=self.abatement_date,
            notes=self.notes,
            change_summary=change_summary or '',
            changed_by=changed_by,
        )


class ProblemHistory(models.Model):
    """Immutable audit trail for problem list changes (Can Access Problem History)."""
    ACTION_CHOICES = KNHTS_HISTORY_ACTION_CHOICES

    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='history')
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, default='updated')
    display = models.CharField(max_length=512, blank=True, default='')
    icd11_code = models.CharField(max_length=32, blank=True, default='')
    clinical_status = models.CharField(max_length=20, blank=True, default='')
    verification_status = models.CharField(max_length=20, blank=True, default='')
    severity = models.CharField(max_length=16, blank=True, default='')
    onset_date = models.DateField(null=True, blank=True)
    abatement_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    change_summary = models.CharField(max_length=255, blank=True, default='')
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='problem_history_changes'
    )

    class Meta:
        ordering = ['-changed_at']
        verbose_name = 'Problem History Entry'
        verbose_name_plural = 'Problem History'

    def __str__(self):
        return f"{self.problem_id} {self.action} @ {self.changed_at}"


class PatientMedication(models.Model):
    """
    Longitudinal medication list (active + historical) with DHA HPT coding.

    Active = current meds. Non-active rows form medication history together
    with history audit entries.
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('stopped', 'Stopped'),
        ('on-hold', 'On hold'),
        ('entered-in-error', 'Entered in error'),
    ]
    SOURCE_CHOICES = [
        ('manual', 'Clinician entry'),
        ('prescription', 'From prescription'),
        ('ipd_chart', 'From IPD chart'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='medications')
    visit = models.ForeignKey(
        Visit, on_delete=models.SET_NULL, null=True, blank=True, related_name='patient_medications',
    )
    source_prescription_item = models.ForeignKey(
        'PrescriptionItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='patient_medication_links',
    )
    inventory_item = models.ForeignKey(
        'inventory.InventoryItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='patient_medications',
    )

    display_name = models.CharField(max_length=255)
    generic_concept_code = models.CharField(max_length=64, blank=True, db_index=True)
    generic_concept_display = models.CharField(max_length=255, blank=True)
    actual_product_code = models.CharField(max_length=64, blank=True)

    dose_text = models.CharField(max_length=128, blank=True)
    frequency = models.CharField(max_length=64, blank=True)
    route = models.CharField(max_length=64, blank=True)
    instructions = models.TextField(blank=True)

    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='active', db_index=True)
    source = models.CharField(max_length=24, choices=SOURCE_CHOICES, default='manual')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    recorded_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, related_name='patient_meds_recorded',
    )
    updated_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='patient_meds_updated',
    )

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['patient', 'status']),
            models.Index(fields=['patient', 'generic_concept_code']),
        ]

    def __str__(self):
        return f"{self.display_name} [{self.status}]"

    @property
    def is_active(self):
        return self.status == 'active'

    def record_history(self, *, action, changed_by=None, change_summary=''):
        return PatientMedicationHistory.objects.create(
            medication=self,
            action=action,
            display_name=self.display_name,
            generic_concept_code=self.generic_concept_code,
            status=self.status,
            dose_text=self.dose_text,
            frequency=self.frequency,
            start_date=self.start_date,
            end_date=self.end_date,
            notes=self.notes,
            change_summary=change_summary or '',
            changed_by=changed_by,
        )


class PatientMedicationHistory(models.Model):
    ACTION_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('status_changed', 'Status changed'),
        ('stopped', 'Stopped'),
        ('completed', 'Completed'),
        ('reactivated', 'Reactivated'),
        ('entered_in_error', 'Entered in error'),
    ]
    medication = models.ForeignKey(PatientMedication, on_delete=models.CASCADE, related_name='history')
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, default='updated')
    display_name = models.CharField(max_length=255, blank=True)
    generic_concept_code = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=24, blank=True)
    dose_text = models.CharField(max_length=128, blank=True)
    frequency = models.CharField(max_length=64, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    change_summary = models.CharField(max_length=255, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='patient_med_history_changes',
    )

    class Meta:
        ordering = ['-changed_at']


class PatientAllergy(models.Model):
    """
    Patient allergy / intolerance list with HPT allergen coding when available.

    Allergen substance prefers MOH-PPB HPT (AC*/GE*). Optional ICD-11 for
    allergy event coding (e.g. adverse drug event relating to known allergy).
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('resolved', 'Resolved'),
        ('entered-in-error', 'Entered in error'),
    ]
    TYPE_CHOICES = [
        ('allergy', 'Allergy'),
        ('intolerance', 'Intolerance'),
    ]
    CATEGORY_CHOICES = [
        ('medication', 'Medication'),
        ('food', 'Food'),
        ('environment', 'Environment'),
        ('biologic', 'Biologic'),
        ('other', 'Other'),
    ]
    CRITICALITY_CHOICES = [
        ('low', 'Low'),
        ('high', 'High'),
        ('unable-to-assess', 'Unable to assess'),
    ]
    SEVERITY_CHOICES = [
        ('', '---------'),
        ('mild', 'Mild'),
        ('moderate', 'Moderate'),
        ('severe', 'Severe'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='allergies')
    visit = models.ForeignKey(
        Visit, on_delete=models.SET_NULL, null=True, blank=True, related_name='patient_allergies',
    )

    allergen_name = models.CharField(max_length=255)
    # HPT substance / product used as allergen code
    hpt_code = models.CharField(max_length=64, blank=True, db_index=True)
    hpt_display = models.CharField(max_length=255, blank=True)
    hpt_kind = models.CharField(max_length=32, blank=True, help_text='generic_product|product|active_component|other')
    icd11_code = models.CharField(max_length=32, blank=True, db_index=True)
    icd11_display = models.CharField(max_length=255, blank=True)

    allergy_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='allergy')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='medication')
    clinical_status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='active', db_index=True)
    criticality = models.CharField(max_length=24, choices=CRITICALITY_CHOICES, blank=True, default='unable-to-assess')
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, blank=True, default='')
    reaction = models.CharField(max_length=255, blank=True, help_text='e.g. rash, anaphylaxis')
    onset_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    recorded_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, related_name='patient_allergies_recorded',
    )
    updated_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='patient_allergies_updated',
    )

    class Meta:
        ordering = ['-updated_at']
        verbose_name_plural = 'Patient allergies'
        indexes = [
            models.Index(fields=['patient', 'clinical_status']),
            models.Index(fields=['patient', 'hpt_code']),
        ]

    def __str__(self):
        return f"{self.allergen_name} [{self.clinical_status}]"

    @property
    def is_active(self):
        return self.clinical_status == 'active'

    def record_history(self, *, action, changed_by=None, change_summary=''):
        return PatientAllergyHistory.objects.create(
            allergy=self,
            action=action,
            allergen_name=self.allergen_name,
            hpt_code=self.hpt_code,
            clinical_status=self.clinical_status,
            severity=self.severity,
            reaction=self.reaction,
            notes=self.notes,
            change_summary=change_summary or '',
            changed_by=changed_by,
        )


class PatientAllergyHistory(models.Model):
    ACTION_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('status_changed', 'Status changed'),
        ('resolved', 'Resolved'),
        ('reactivated', 'Reactivated'),
        ('entered_in_error', 'Entered in error'),
    ]
    allergy = models.ForeignKey(PatientAllergy, on_delete=models.CASCADE, related_name='history')
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, default='updated')
    allergen_name = models.CharField(max_length=255, blank=True)
    hpt_code = models.CharField(max_length=64, blank=True)
    clinical_status = models.CharField(max_length=24, blank=True)
    severity = models.CharField(max_length=16, blank=True)
    reaction = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    change_summary = models.CharField(max_length=255, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='patient_allergy_history_changes',
    )

    class Meta:
        ordering = ['-changed_at']
        verbose_name_plural = 'Patient allergy history'


class ClinicalSummary(models.Model):
    """
    Generated clinical summary for a visit — human-readable + Kenya HIE FHIR document.

    Checklist coverage:
    - Human-readable narrative (narrative_text / print view)
    - Kenya HIE exchangeable FHIR Bundle (Composition document)
    - Biodata, clinical info, medications, prescriptions, care plan sections
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('generated', 'Generated'),
        ('synced', 'Synced to HIE'),
        ('error', 'Error'),
    ]
    HIE_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('synced', 'Synced'),
        ('partial', 'Partial'),
        ('error', 'Error'),
        ('skipped', 'Skipped'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='clinical_summaries')
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='clinical_summaries')

    care_plan = models.TextField(
        blank=True,
        help_text='Plan of care / follow-up instructions included in the summary',
    )
    narrative_text = models.TextField(blank=True)
    summary_json = models.JSONField(default=dict, blank=True)
    fhir_bundle = models.JSONField(default=dict, blank=True)
    sync_payload = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='draft', db_index=True)
    hie_sync_status = models.CharField(
        max_length=16, choices=HIE_STATUS_CHOICES, default='pending', db_index=True,
    )
    hie_document_id = models.CharField(max_length=128, blank=True)
    hie_sync_raw = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True)

    includes_biodata = models.BooleanField(default=True)
    includes_clinical = models.BooleanField(default=True)
    includes_medications = models.BooleanField(default=False)
    includes_prescriptions = models.BooleanField(default=False)
    includes_care_plan = models.BooleanField(default=False)

    generated_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='clinical_summaries_generated',
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-generated_at']
        verbose_name_plural = 'Clinical summaries'
        indexes = [
            models.Index(fields=['patient', 'visit']),
            models.Index(fields=['status', 'hie_sync_status']),
        ]

    def __str__(self):
        return f"ClinicalSummary #{self.pk} visit={self.visit_id} [{self.status}]"


class FamilyHistory(models.Model):
    """
    Structured family history (CPOE / FHIR FamilyMemberHistory–aligned).
    Supports recording hereditary conditions in relatives.
    """
    RELATIONSHIP_CHOICES = [
        ('father', 'Father'),
        ('mother', 'Mother'),
        ('brother', 'Brother'),
        ('sister', 'Sister'),
        ('son', 'Son'),
        ('daughter', 'Daughter'),
        ('grandfather', 'Grandfather'),
        ('grandmother', 'Grandmother'),
        ('uncle', 'Uncle'),
        ('aunt', 'Aunt'),
        ('cousin', 'Cousin'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('entered-in-error', 'Entered in error'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='family_history')
    relationship = models.CharField(max_length=32, choices=RELATIONSHIP_CHOICES)
    relative_name = models.CharField(max_length=120, blank=True, help_text='Optional name of relative')
    condition = models.CharField(max_length=255, help_text='Condition / problem in relative')
    icd11_code = models.CharField(max_length=32, blank=True, db_index=True)
    icd11_display = models.CharField(max_length=255, blank=True)
    onset_age = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text='Age of relative at onset (years)',
    )
    is_deceased = models.BooleanField(default=False)
    contributed_to_death = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='active', db_index=True)

    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    recorded_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, related_name='family_history_recorded',
    )
    updated_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='family_history_updated',
    )

    class Meta:
        ordering = ['relationship', 'condition']
        verbose_name = 'Family History'
        verbose_name_plural = 'Family History'
        indexes = [
            models.Index(fields=['patient', 'status']),
        ]

    def __str__(self):
        return f"{self.get_relationship_display()}: {self.condition}"

