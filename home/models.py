from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone


class Departments(models.Model):
    name = models.CharField(max_length=100, unique=True)
    hod = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='departments_hod')
    abbreviation = models.CharField(max_length=10, null=True, blank=True, unique=True)

    def __str__(self):
        return self.name
class Patient(models.Model):
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
        ('N', 'Prefer not to say')
    ]
    
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    id_number = models.CharField(max_length=20, unique=True, null=True, blank=True)
    date_of_birth = models.DateField()
    age = models.PositiveIntegerField(editable=False)  # Will be calculated automatically
    phone = models.CharField(max_length=15)
    location = models.CharField(max_length=200)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='patients_created')
    
    def save(self, *args, **kwargs):
        # Calculate age based on date of birth
        today = timezone.now().date()
        age = today.year - self.date_of_birth.year - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
        self.age = age
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

class Visit(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='visits')
    visit_date = models.DateTimeField(auto_now_add=True)
    visit_type = models.CharField(max_length=20, choices=[('IN-PATIENT', 'In-Patient'), ('OUT-PATIENT', 'Out-Patient')])
    visit_mode = models.CharField(max_length=20, choices=[('Appointment', 'Appointment'), ('Walk In', 'Walk In')])
    is_active = models.BooleanField(default=True)
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
    """Model for storing emergency contact information for patients"""
    
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
    
    patient = models.ForeignKey('Patient', on_delete=models.CASCADE, related_name='emergency_contacts')
    name = models.CharField(max_length=200, help_text="Emergency contact person name")
    relationship = models.CharField(max_length=20, choices=RELATIONSHIP_CHOICES, help_text="Relationship to patient")
    phone = models.CharField(max_length=20, help_text="Emergency contact phone number")
    email = models.EmailField(blank=True, help_text="Emergency contact email address")
    address = models.TextField(blank=True, help_text="Emergency contact address")
    is_primary = models.BooleanField(default=False, help_text="Primary emergency contact")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='emergency_contacts_created')
    
    class Meta:
        ordering = ['-is_primary', 'name']
        verbose_name = "Emergency Contact"
        verbose_name_plural = "Emergency Contacts"
    
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
    diagnosis = models.TextField(help_text="Reason for prescription")
    notes = models.TextField(blank=True, help_text="Additional instructions or notes")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    
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
    
    # Numeric components for auto-calculation and record keeping
    dose_count = models.PositiveIntegerField(default=1, help_text="Units per dose (e.g., 2 tablets)")
    frequency = models.CharField(max_length=20, choices=frequency_choices, default='Once Daily', help_text="Frequency of medication")
    
    quantity = models.IntegerField(help_text="Total units to dispense")
    instructions = models.TextField(blank=True, help_text="Special instructions for this medication")
    dispensed = models.BooleanField(default=False, help_text="Has this been dispensed by pharmacy?")
    dispensed_at = models.DateTimeField(null=True, blank=True)
    dispensed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='medications_dispensed')
    
    class Meta:
        verbose_name = "Prescription Item"
        verbose_name_plural = "Prescription Items"
    
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
