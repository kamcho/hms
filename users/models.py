from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone


class CustomUserManager(BaseUserManager):
    def create_user(self, id_number, password=None, **extra_fields):
        if not id_number:
            raise ValueError('The ID Number must be set')
        user = self.model(id_number=id_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, id_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self.create_user(id_number, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    roles = [
        ('Admin', 'Admin'),
        ('Receptionist', 'Receptionist'),
        ('Doctor', 'Doctor'),
        ('Nurse', 'Nurse'),
        ('Pharmacist', 'Pharmacist'),
        ('Lab Technician', 'Lab Technician'),
        ('Accountant', 'Accountant'),
        ('HR Manager', 'HR Manager'),
        ('Triage Nurse', 'Triage Nurse'),
        ('Radiographer', 'Radiographer'),
        ('Procurement Officer', 'Procurement Officer'),
        ('SHA Manager', 'SHA Manager'),
        ('Mortuary Officer', 'Mortuary Officer'),
    ]
    id_number = models.CharField(max_length=20, unique=True)
    first_name = models.CharField(max_length=50, blank=True, null=True)
    last_name = models.CharField(max_length=50, blank=True, null=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    
    role = models.CharField(max_length=20, choices=roles)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    # DHA practitioner registry fields (for eRx / claims)
    REGULATION_BODY_CHOICES = [
        ('KMPDC', 'KMPDC'),
        ('COC', 'COC'),
        ('NCK', 'NCK'),
        ('PPB', 'PPB'),
    ]
    PRACTITIONER_ID_TYPE_CHOICES = [
        ('registration_number', 'Registration number'),
        ('National ID', 'National ID'),
        ('Alien ID', 'Alien ID'),
        ('Refugee ID', 'Refugee ID'),
    ]
    practitioner_identification_type = models.CharField(
        max_length=40,
        choices=PRACTITIONER_ID_TYPE_CHOICES,
        blank=True,
        default='registration_number',
    )
    practitioner_licence_number = models.CharField(
        max_length=64,
        blank=True,
        help_text='KMPDC/NCK/etc registration number used on SHA eClaims',
    )
    practitioner_regulation_body = models.CharField(
        max_length=16,
        choices=REGULATION_BODY_CHOICES,
        blank=True,
        default='KMPDC',
    )

    USERNAME_FIELD = 'id_number'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.id_number
    
    @property
    def username(self):
        return f"{self.first_name} {self.last_name}".strip() if self.first_name or self.last_name else self.id_number
    
    def get_full_name(self):
        return self.username
