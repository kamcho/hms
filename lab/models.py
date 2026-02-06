from django.db import models
from django.contrib.auth import get_user_model
from accounts.models import Service, Invoice
from home.models import Patient

User = get_user_model()

class LabResult(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('In Progress', 'In Progress'),
        ('Completed', 'Completed'),
        ('Cancelled', 'Cancelled'),
    ]
    
    PRIORITY_CHOICES = [
        ('Low', 'Low'),
        ('Normal', 'Normal'),
        ('High', 'High'),
        ('Urgent', 'Urgent'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, null=True, blank=True)
    invoice_item = models.ForeignKey('accounts.InvoiceItem', on_delete=models.SET_NULL, null=True, blank=True)
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='requested_tests')
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='performed_tests')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='Normal')
    
    requested_at = models.DateTimeField(auto_now_add=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    clinical_notes = models.TextField(blank=True)
    results = models.TextField(blank=True)
    interpretation = models.TextField(blank=True)
    
    def __str__(self):
        return f"{self.patient.full_name} - {self.service.name} ({self.status})"

class LabReport(models.Model):
    lab_result = models.OneToOneField(LabResult, on_delete=models.CASCADE)
    report_file = models.FileField(upload_to='lab_reports/%Y/%m/', null=True, blank=True)
    report_text = models.TextField(blank=True)
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    is_final = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_reports')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Report for {self.lab_result}"
