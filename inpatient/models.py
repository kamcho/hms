from django.db import models
from django.conf import settings
from django.utils import timezone

class Ward(models.Model):
    WARD_TYPES = [
        ('General', 'General'),

        ('ICU', 'ICU'),
        ('HDU', 'HDU'),
        ('Pediatric', 'Pediatric'),
        ('Maternity', 'Maternity'),
        ('Surgical', 'Surgical'),
        ('Emergency', 'Emergency'),
    ]
    name = models.CharField(max_length=100)
    ward_type = models.CharField(max_length=20, choices=WARD_TYPES, default='General')
    base_charge_per_day = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.name} ({self.ward_type})"

class Bed(models.Model):
    BED_TYPES = [
        ('Normal', 'Normal'),
        ('Oxygen', 'Oxygen Support'),
        ('Ventilator', 'Ventilator'),
        ('Cradle', 'Cradle/Cot'),
    ]
    bed_number = models.CharField(max_length=20)
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name='beds')
    is_occupied = models.BooleanField(default=False)
    bed_type = models.CharField(max_length=20, choices=BED_TYPES, default='Normal')

    def __str__(self):
        return f"Bed {self.bed_number} - {self.ward.name}"

class Admission(models.Model):
    STATUS_CHOICES = [
        ('Admitted', 'Admitted'),
        ('Discharged', 'Discharged'),
        ('Transferred', 'Transferred'),
        ('Deceased', 'Deceased'),
    ]
    patient = models.ForeignKey('home.Patient', on_delete=models.CASCADE, related_name='admissions')
    visit = models.ForeignKey('home.Visit', on_delete=models.CASCADE, related_name='admissions')
    bed = models.ForeignKey(Bed, on_delete=models.SET_NULL, null=True, blank=True, related_name='admissions')
    admitted_at = models.DateTimeField(auto_now_add=True)
    admitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='admissions_processed')
    provisional_diagnosis = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Admitted')
    
    # Discharge fields (consolidated for ease)
    discharged_at = models.DateTimeField(null=True, blank=True)
    discharged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='discharges_processed')
    final_diagnosis = models.TextField(blank=True, null=True)
    discharge_summary = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Admission: {self.patient.full_name} - {self.admitted_at.strftime('%Y-%m-%d')}"

    def save(self, *args, **kwargs):
        # Automatically handle bed occupancy if bed is assigned
        if self.bed and self.status == 'Admitted':
            self.bed.is_occupied = True
            self.bed.save()
        elif self.status in ['Discharged', 'Transferred', 'Deceased'] and self.bed:
            self.bed.is_occupied = False
            self.bed.save()
        super().save(*args, **kwargs)

class MedicationChart(models.Model):
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

    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='medications')
    item = models.ForeignKey('inventory.InventoryItem', on_delete=models.CASCADE, related_name='inpatient_medications')
    
    dose_count = models.PositiveIntegerField(default=1, help_text="Units per dose (e.g., 2 tablets)")
    frequency = models.CharField(max_length=20, choices=frequency_choices, default='Once Daily', help_text="Frequency of medication")
    quantity = models.PositiveIntegerField(default=1, help_text="Total units to dispense")
    
    # DEPRECATED: Kept for backwards compatibility with existing records
    dosage = models.CharField(max_length=100, blank=True, null=True)
    frequency_count = models.PositiveIntegerField(default=1, help_text="DEPRECATED - kept for old records")
    duration_days = models.PositiveIntegerField(default=1, help_text="DEPRECATED - kept for old records")
    
    prescribed_at = models.DateTimeField(auto_now_add=True)
    prescribed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='medications_prescribed')
    
    # Dispensing status
    is_dispensed = models.BooleanField(default=False, help_text="Has this been dispensed by pharmacy?")
    dispensed_at = models.DateTimeField(null=True, blank=True)
    dispensed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='medications_dispensed_ipd')
    instructions = models.TextField(blank=True, null=True, help_text="Specific instructions for this medication")
    
    # Administration status
    administered_at = models.DateTimeField(null=True, blank=True)
    administered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='medications_administered')
    is_administered = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.item.name} - {self.dose_count} x {self.frequency} for {self.admission.patient.full_name}"

class ServiceAdmissionLink(models.Model):
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='services')
    service = models.ForeignKey('accounts.Service', on_delete=models.CASCADE, related_name='admission_placements')
    quantity = models.PositiveIntegerField(default=1)
    date_provided = models.DateTimeField(default=timezone.now)
    provided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"{self.service.name} for {self.admission.patient.full_name}"
        
from django.utils import timezone

class InpatientDischarge(models.Model):
    """Formal record of patient discharge and final billing snapshot"""
    admission = models.OneToOneField(Admission, on_delete=models.CASCADE, related_name='discharge_record')
    discharge_date = models.DateTimeField(default=timezone.now)
    
    # Clinical Summary
    final_diagnosis = models.TextField()
    discharge_summary = models.TextField()
    
    # Financial Snapshot
    total_bill_snapshot = models.DecimalField(max_digits=12, decimal_places=2, help_text="Total bill at time of discharge")
    
    # Accountable Staff
    discharged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='discharges_authorized')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Discharge: {self.admission.patient.full_name} ({self.discharge_date.date()})"

    class Meta:
        verbose_name = "Inpatient Discharge"
        verbose_name_plural = "Inpatient Discharges"
        ordering = ['-discharge_date']

class PatientVitals(models.Model):
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='vitals')
    recorded_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    
    temperature = models.DecimalField(max_digits=4, decimal_places=1, help_text="°C", null=True, blank=True)
    pulse_rate = models.PositiveIntegerField(help_text="bpm", null=True, blank=True)
    respiratory_rate = models.PositiveIntegerField(help_text="breaths/min", null=True, blank=True)
    systolic_bp = models.PositiveIntegerField(null=True, blank=True)
    diastolic_bp = models.PositiveIntegerField(null=True, blank=True)
    spo2 = models.PositiveIntegerField(help_text="%", null=True, blank=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, help_text="kg", null=True, blank=True)
    blood_sugar = models.DecimalField(max_digits=4, decimal_places=1, help_text="mmol/L", null=True, blank=True)

    class Meta:
        ordering = ['-recorded_at']
        verbose_name_plural = "Patient Vitals"

    def __str__(self):
        return f"Vitals for {self.admission.patient.full_name} at {self.recorded_at}"

class ClinicalNote(models.Document if False else models.Model): # Dummy check for IDE focus
    NOTE_TYPES = [
        ('Doctor', "Doctor's Note"),
        ('Nursing', 'Nursing Note'),
        ('Consultation', 'Consultation Note'),
        ('Operational', 'Operation Note'),
    ]
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='clinical_notes')
    note_type = models.CharField(max_length=20, choices=NOTE_TYPES, default='Doctor')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.note_type} Note - {self.admission.patient.full_name} ({self.created_at.date()})"

class FluidBalance(models.Model):
    FLUID_TYPES = [
        ('Intake', 'Intake'),
        ('Output', 'Output'),
    ]
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='fluid_balances')
    fluid_type = models.CharField(max_length=10, choices=FLUID_TYPES)
    item = models.CharField(max_length=100, help_text="e.g., Normal Saline, Urine, Vomitus")
    amount_ml = models.PositiveIntegerField()
    recorded_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"{self.fluid_type}: {self.amount_ml}ml ({self.item})"

class WardTransfer(models.Model):
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='transfers')
    from_bed = models.ForeignKey(Bed, on_delete=models.SET_NULL, null=True, related_name='transfers_from')
    to_bed = models.ForeignKey(Bed, on_delete=models.SET_NULL, null=True, related_name='transfers_to')
    reason = models.TextField(blank=True)
    transferred_at = models.DateTimeField(auto_now_add=True)
    transferred_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"Transfer: {self.admission.patient.full_name} to {self.to_bed}"

    def save(self, *args, **kwargs):
        if not self.pk: # Only on creation
            # Free old bed
            if self.from_bed:
                self.from_bed.is_occupied = False
                self.from_bed.save()
            # Occupy new bed
            if self.to_bed:
                self.to_bed.is_occupied = True
                self.to_bed.save()
            # Update admission's current bed
            self.admission.bed = self.to_bed
            self.admission.save()
        super().save(*args, **kwargs)

class DoctorInstruction(models.Model):
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='instructions')
    instruction = models.TextField()
    instruction_type = models.CharField(max_length=50, choices=[
        ('Treatment', 'Treatment'),
        ('Activity', 'Activity/Mobility'),
        ('Monitoring', 'Monitoring'),
        ('General', 'General'),
    ], default='General')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='instructions_given')
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='instructions_completed')

    def __str__(self):
        return f"Instruction for {self.admission.patient.full_name} - {self.instruction_type}"

class NutritionOrder(models.Model):
    DIET_TYPES = [
        ('Full', 'Full Diet'),
        ('Soft', 'Soft Diet'),
        ('Liquid', 'Liquid Diet'),
        ('Diabetic', 'Diabetic Diet'),
        ('Renal', 'Renal Diet'),
        ('Low-Salt', 'Low Salt Diet'),
        ('NPO', 'Nil Per Os (Nothing by Mouth)'),
    ]
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='nutrition_orders')
    diet_type = models.CharField(max_length=50, choices=DIET_TYPES, default='Full')
    specific_instructions = models.TextField(blank=True)
    prescribed_at = models.DateTimeField(auto_now_add=True)
    prescribed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='nutrition_prescribed')
    
    def __str__(self):
        return f"Nutrition: {self.diet_type} for {self.admission.patient.full_name}"

class InpatientConsumable(models.Model):
    """Tracks consumable requests for admitted patients to be billed upon dispense"""
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='consumables')
    item = models.ForeignKey('inventory.InventoryItem', on_delete=models.CASCADE, related_name='inpatient_consumables')
    quantity = models.PositiveIntegerField(default=1)
    
    prescribed_at = models.DateTimeField(auto_now_add=True)
    prescribed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='consumables_prescribed')
    
    # Dispensing status
    is_dispensed = models.BooleanField(default=False)
    dispensed_at = models.DateTimeField(null=True, blank=True)
    dispensed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='consumables_dispensed')
    instructions = models.TextField(blank=True, null=True, help_text="Specific instructions for this consumable")

    def __str__(self):
        return f"{self.item.name} x{self.quantity} for {self.admission.patient.full_name}"

    class Meta:
        verbose_name = "Inpatient Consumable"
        verbose_name_plural = "Inpatient Consumables"
        ordering = ['-prescribed_at']

from django.db.models.signals import post_delete
from django.dispatch import receiver

@receiver(post_delete, sender=Admission)
def release_bed_on_admission_delete(sender, instance, **kwargs):
    """Ensure bed is freed if admission is deleted (e.g. via visit deletion)"""
    if instance.bed:
        instance.bed.is_occupied = False
        instance.bed.save()
