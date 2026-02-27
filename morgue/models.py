from django.db import models
from django.utils import timezone
from users.models import User
from home.models import Patient

class Morgue(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    base_charge_per_day = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return self.name

class Chamber(models.Model):
    morgue = models.ForeignKey(Morgue, on_delete=models.CASCADE, related_name='chambers')
    chamber_number = models.CharField(max_length=20)
    is_occupied = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.chamber_number} - {self.morgue.name}"

class Deceased(models.Model):
    """Model for storing deceased person information"""
    
    DECEASED_TYPE_CHOICES = [
        ('INTERNAL', 'Internal'),
        ('EXTERNAL', 'External'),
    ]
    
    SEX_CHOICES = [
        ('MALE', 'Male'),
        ('FEMALE', 'Female'),
        ('OTHER', 'Other'),
    ]
    
    SCHEME_CHOICES = [
        ('CASH_PAYERS', 'Cash Payers'),
        ('INSURANCE', 'Insurance'),
        ('NHIF', 'NHIF'),
    ]
    
    ID_TYPE_CHOICES = [
        ('NATIONAL_ID', 'National ID'),
        ('PASSPORT', 'Passport'),
        ('BIRTH_CERTIFICATE', 'Birth Certificate'),
        ('DRIVING_LICENSE', 'Driving License'),
        ('OTHER', 'Other'),
    ]
    
    # Deceased Details
    deceased_type = models.CharField(max_length=20, choices=DECEASED_TYPE_CHOICES, default='INTERNAL')
    surname = models.CharField(max_length=100)
    other_names = models.CharField(max_length=200)
    sex = models.CharField(max_length=10, choices=SEX_CHOICES)
    scheme = models.CharField(max_length=20, choices=SCHEME_CHOICES, default='CASH_PAYERS')
    id_type = models.CharField(max_length=20, choices=ID_TYPE_CHOICES, blank=True, default='')
    id_number = models.CharField(max_length=50, blank=True, default='')
    
    # Physical Address
    physical_address = models.TextField(blank=True, default='')
    residence = models.CharField(max_length=100, blank=True, default='')
    town = models.CharField(max_length=100, blank=True, default='')
    nationality = models.CharField(max_length=100, default='Kenyan')
    
    # Death Details
    date_of_death = models.DateField()
    time_of_death = models.TimeField()
    place_of_death = models.CharField(max_length=200)
    cause_of_death = models.TextField()
    
    # Storage Details
    storage_area = models.ForeignKey(Morgue, on_delete=models.SET_NULL, null=True, blank=True)
    storage_chamber = models.ForeignKey(Chamber, on_delete=models.SET_NULL, null=True, blank=True)
    expected_removal_date = models.DateField(null=True, blank=True)
    tag = models.CharField(max_length=50, unique=True, blank=True, null=True, help_text="Unique identification tag for the deceased")
    
    # Link to hospital patient (for internal deceased)
    patient = models.ForeignKey(Patient, on_delete=models.SET_NULL, null=True, blank=True, related_name='deceased_records')
    
    # System Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    is_released = models.BooleanField(default=False)
    release_date = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Deceased"
        verbose_name_plural = "Deceased"
    
    def __str__(self):
        return f"{self.surname}, {self.other_names} ({self.tag})"
    
    @property
    def full_name(self):
        return f"{self.surname} {self.other_names}"
    
    @property
    def datetime_of_death(self):
        """Combined date and time of death"""
        import datetime
        return datetime.datetime.combine(self.date_of_death, self.time_of_death)


class NextOfKin(models.Model):
    """Model for storing next of kin information"""
    
    ID_TYPE_CHOICES = [
        ('NATIONAL_ID', 'National ID'),
        ('PASSPORT', 'Passport'),
        ('BIRTH_CERTIFICATE', 'Birth Certificate'),
        ('DRIVING_LICENSE', 'Driving License'),
        ('OTHER', 'Other'),
    ]
    
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
        ('OTHER', 'Other'),
    ]
    
    deceased = models.ForeignKey(Deceased, on_delete=models.CASCADE, related_name='next_of_kin')
    name = models.CharField(max_length=200)
    id_type = models.CharField(max_length=20, choices=ID_TYPE_CHOICES)
    id_number = models.CharField(max_length=50)
    relationship = models.CharField(max_length=20, choices=RELATIONSHIP_CHOICES)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    is_primary = models.BooleanField(default=False, help_text="Primary contact person")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_primary', 'name']
        verbose_name = "Next of Kin"
        verbose_name_plural = "Next of Kin"
    
    def __str__(self):
        return f"{self.name} - {self.get_relationship_display()} of {self.deceased.full_name}"


class MorgueAdmission(models.Model):
    """Model for tracking morgue admission and release records"""
    
    ADMISSION_STATUS_CHOICES = [
        ('ADMITTED', 'Admitted'),
        ('RELEASED', 'Released'),
        ('TRANSFERRED', 'Transferred'),
    ]
    
    deceased = models.ForeignKey(Deceased, on_delete=models.CASCADE, related_name='admissions')
    admission_number = models.CharField(max_length=50, unique=True)
    admission_datetime = models.DateTimeField(help_text="Date and time when deceased was admitted to morgue")
    status = models.CharField(max_length=20, choices=ADMISSION_STATUS_CHOICES, default='ADMITTED')
    release_date = models.DateTimeField(null=True, blank=True)
    released_to = models.CharField(max_length=200, blank=True, help_text="Person/organization released to")
    release_notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    
    class Meta:
        ordering = ['-admission_datetime']
        verbose_name = "Morgue Admission"
        verbose_name_plural = "Morgue Admissions"
    
    def __str__(self):
        return f"Admission {self.admission_number} - {self.deceased.full_name}"
    
    @property
    def admission_date(self):
        """Alias for backward compatibility - returns admission datetime"""
        return self.admission_datetime

class PerformedMortuaryService(models.Model):
    deceased = models.ForeignKey(Deceased, on_delete=models.CASCADE, related_name='performed_services')
    service = models.ForeignKey('accounts.Service', on_delete=models.CASCADE, related_name='morgue_placements')
    quantity = models.PositiveIntegerField(default=1)
    date_performed = models.DateTimeField(default=timezone.now)
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='morgue_services_performed')

    def __str__(self):
        return f"{self.service.name} for {self.deceased.full_name}"

    @property
    def subtotal(self):
        """Calculate subtotal for this service"""
        return self.service.price * self.quantity

    class Meta:
        verbose_name = "Performed Mortuary Service"
        verbose_name_plural = "Performed Mortuary Services"
        ordering = ['-date_performed']

class MortuaryDischarge(models.Model):
    """Formal record of deceased release and final billing"""
    deceased = models.OneToOneField(Deceased, on_delete=models.CASCADE, related_name='discharge_record')
    admission = models.ForeignKey(MorgueAdmission, on_delete=models.SET_NULL, null=True, related_name='discharges')
    discharge_date = models.DateTimeField(default=timezone.now)
    
    # Receiver Details
    released_to = models.CharField(max_length=255)
    relationship = models.CharField(max_length=100)
    receiver_id_number = models.CharField(max_length=50)
    receiver_phone = models.CharField(max_length=20, blank=True)
    
    # Financial Snapshot
    total_bill_snapshot = models.DecimalField(max_digits=12, decimal_places=2, help_text="Total bill at time of discharge")
    
    # Authorization
    authorized_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='morgue_discharges_authorized')
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Discharge: {self.deceased.full_name} on {self.discharge_date.date()}"

    class Meta:
        verbose_name = "Mortuary Discharge"
        verbose_name_plural = "Mortuary Discharges"
