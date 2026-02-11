from django.db import models
from django.utils import timezone

class Service(models.Model):
    CATEGORY_CHOICES = [
        ('Consultation', 'Consultation'),
        ('Lab', 'Laboratory'),
        ('Imaging', 'Imaging/Radiology'),
        ('Procedure', 'Procedure'),
        ('Pharmacy', 'Pharmacy'),
        ('Nursing', 'Nursing Care'),
        ('Antenatal', 'Antenatal Care'),
        ('Surgery', 'Surgery'),
        ('Admission', 'Admission/Accommodation'),
        ('Mortuary', 'Mortuary'),
        ('Other', 'Other'),
    ]
    name = models.CharField(max_length=200)
    department = models.ForeignKey('home.Departments', on_delete=models.PROTECT, related_name='services', null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.department:
            return f"{self.name} ({self.department.name})"
        return f"{self.name} ({self.category or 'N/A'})"
    
    class Meta:
        ordering = ['department__name', 'name']

class ServiceParameters(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='parameters')
    name = models.CharField(max_length=100)
    value = models.CharField(max_length=100)
    ranges = models.CharField(max_length=100)
    unit = models.CharField(max_length=100)
    
    def __str__(self):
        return self.name



class Invoice(models.Model):
    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Pending', 'Pending Payment'),
        ('Partial', 'Partially Paid'),
        ('Paid', 'Paid'),
        ('Cancelled', 'Cancelled'),
    ]
    
    patient = models.ForeignKey('home.Patient', on_delete=models.CASCADE, related_name='invoices', null=True, blank=True)
    deceased = models.ForeignKey('morgue.Deceased', on_delete=models.CASCADE, related_name='invoices', null=True, blank=True)
    visit = models.ForeignKey('home.Visit', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Draft')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True, help_text="Additional notes or reference information")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='created_invoices')
    
    def __str__(self):
        if self.deceased:
            return f"INV-{self.id} - {self.deceased.full_name} (Deceased) - {self.status}"
        elif self.patient:
            return f"INV-{self.id} - {self.patient.full_name} - {self.status}"
        return f"INV-{self.id} - {self.status}"
    
    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.patient and not self.deceased:
            raise ValidationError("Invoice must be linked to either a patient or deceased person.")
        if self.patient and self.deceased:
            raise ValidationError("Invoice cannot be linked to both patient and deceased.")
    
    def update_totals(self):
        """Recalculate total amount linked to this invoice"""
        total = self.items.aggregate(total=models.Sum('amount'))['total'] or 0
        self.total_amount = total
        
        # Determine status
        if self.paid_amount >= self.total_amount and self.total_amount > 0:
            self.status = 'Paid'
        elif self.paid_amount > 0:
            self.status = 'Partial'
        elif self.status != 'Cancelled':
            self.status = 'Pending'
            
        self.save()
    
    @property
    def balance(self):
        """Calculate remaining balance"""
        return self.total_amount - self.paid_amount


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True)
    inventory_item = models.ForeignKey('inventory.InventoryItem', on_delete=models.SET_NULL, null=True, blank=True)
    
    name = models.CharField(max_length=255, help_text="Snapshot of item name at time of invoice creation")
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price at moment of sale")
    amount = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Auto-calculate amount
        self.amount = self.quantity * self.unit_price
        super().save(*args, **kwargs)
        # Update parent invoice totals
        self.invoice.update_totals()

    def __str__(self):
        return f"{self.name} x{self.quantity}"


class Payment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('Cash', 'Cash'),
        ('M-Pesa', 'M-Pesa'),
        ('Insurance', 'Insurance'),
        ('Bank Transfer', 'Bank Transfer'),
        ('Other', 'Other'),
    ]
    
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    transaction_reference = models.CharField(max_length=100, blank=True, null=True, help_text="M-Pesa Receipt Number, Insurance Claim ID, etc.")
    notes = models.TextField(blank=True, null=True)
    payment_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Updates invoice paid amount
        total_paid = self.invoice.payments.aggregate(total=models.Sum('amount'))['total'] or 0
        self.invoice.paid_amount = total_paid
        self.invoice.update_totals()

    def __str__(self):
        return f"Payment {self.id} - {self.payment_method} - {self.amount}"
    
    class Meta:
        ordering = ['-payment_date']


class MpesaPayment(models.Model):
    """
    Technical log of M-Pesa transactions.
    Links to the actual financial 'Payment' record upon success.
    """
    payment = models.OneToOneField(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='mpesa_log')
    patient = models.ForeignKey('home.Patient', on_delete=models.SET_NULL, null=True, blank=True)
    
    merchant_request_id = models.CharField(max_length=100, unique=True)
    checkout_request_id = models.CharField(max_length=100, unique=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_description = models.TextField(null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    mpesa_receipt_number = models.CharField(max_length=100, null=True, blank=True)
    transaction_date = models.DateTimeField(null=True, blank=True)
    phone_number = models.CharField(max_length=15)
    is_successful = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        status = "Success" if self.is_successful else "Failed/Pending"
        return f"M-Pesa {self.phone_number} - {self.amount} ({status})"

    class Meta:
        verbose_name = "M-Pesa Transaction Log"
        verbose_name_plural = "M-Pesa Transaction Logs"
        ordering = ['-created_at']

class ExpenseCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Expense Categories"

class Expense(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('Cash', 'Cash'),
        ('M-Pesa', 'M-Pesa'),
        ('Bank Transfer', 'Bank Transfer'),
        ('Cheque', 'Cheque'),
        ('Other', 'Other'),
    ]
    
    date = models.DateField(default=timezone.now)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='expenses')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='Cash')
    reference_number = models.CharField(max_length=100, blank=True, null=True, help_text="Receipt #, Transaction ID, etc.")
    description = models.TextField()
    recorded_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.category.name} - {self.amount} ({self.date})"

    class Meta:
        ordering = ['-date', '-created_at']

class SupplierInvoice(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Partial', 'Partially Paid'),
        ('Paid', 'Paid'),
        ('Overdue', 'Overdue'),
        ('Cancelled', 'Cancelled'),
    ]
    
    supplier = models.ForeignKey('inventory.Supplier', on_delete=models.CASCADE, related_name='invoices')
    invoice_number = models.CharField(max_length=100)
    date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    invoice_file = models.FileField(upload_to='supplier_invoices/', null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    recorded_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"INV-{self.invoice_number} from {self.supplier.name}"

    @property
    def balance_due(self):
        return self.total_amount - self.paid_amount

    def update_status(self):
        payments = self.payments.aggregate(total=models.Sum('amount'))['total'] or 0
        self.paid_amount = payments
        if self.paid_amount >= self.total_amount:
            self.status = 'Paid'
        elif self.paid_amount > 0:
            self.status = 'Partial'
        else:
            self.status = 'Pending'
        self.save()

    class Meta:
        ordering = ['-date', '-created_at']

class SupplierPayment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('Cash', 'Cash'),
        ('M-Pesa', 'M-Pesa'),
        ('Bank Transfer', 'Bank Transfer'),
        ('Cheque', 'Cheque'),
        ('Other', 'Other'),
    ]
    
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateTimeField(default=timezone.now)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='Cash')
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    recorded_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.invoice.update_status()

    def __str__(self):
        return f"Payment of {self.amount} for {self.invoice.invoice_number}"

class InventoryPurchase(models.Model):
    """
    Acts as a Goods Received Note (GRN) tracking physical stock intake.
    Linked to a SupplierInvoice for financial reconciliation.
    """
    date = models.DateField(default=timezone.now)
    supplier = models.ForeignKey('inventory.Supplier', on_delete=models.CASCADE, related_name='purchases')
    invoice_ref = models.ForeignKey(SupplierInvoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='grns')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Total value of items received")
    notes = models.TextField(blank=True, null=True)
    recorded_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"GRN from {self.supplier.name} - {self.total_amount} ({self.date})"

    class Meta:
        verbose_name = "Goods Received Note"
        verbose_name_plural = "Goods Received Notes"
        ordering = ['-date', '-created_at']
