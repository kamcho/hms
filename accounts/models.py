from django.db import models
from django.utils import timezone
from decimal import Decimal

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
    is_updated = models.BooleanField(default=False, help_text="Set to True once the service has been reviewed/updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.department:
            return f"{self.name} ({self.department.name})"
        return f"{self.name}"
    
    class Meta:
        ordering = ['department__name', 'name']



class Invoice(models.Model):
    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Pending', 'Pending Payment'),
        ('Partial', 'Partially Paid'),
        ('Paid', 'Paid'),
        ('Cancelled', 'Cancelled'),
    ]
    
    patient = models.ForeignKey('home.Patient', on_delete=models.CASCADE, related_name='invoices', null=True, blank=True)
    deceased = models.OneToOneField('morgue.Deceased', on_delete=models.CASCADE, related_name='invoice', null=True, blank=True)
    visit = models.OneToOneField('home.Visit', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoice')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Draft')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    insurance_adjustment = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Per-diem shortfall absorbed by facility for insurance patients")
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
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
        total = self.items.aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
        self.total_amount = total
        
        # Determine status based on effective amount (after insurance adjustment)
        effective = self.effective_amount
        if self.paid_amount >= effective and effective > 0:
            self.status = 'Paid'
        elif self.paid_amount > 0:
            self.status = 'Partial'
        elif self.status != 'Cancelled':
            self.status = 'Pending'
            
        self.save()
    
    @property
    def effective_amount(self):
        """Amount the hospital expects to collect (after insurance adjustment)"""
        return self.total_amount - self.insurance_adjustment
    
    @property
    def balance(self):
        """Calculate remaining balance based on effective amount"""
        return self.effective_amount - self.paid_amount

    def distribute_payments(self):
        """
        Distributes the total paid amount across invoice items using FIFO logic.
        """
        total_paid = self.payments.aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
        self.paid_amount = total_paid
        
        remaining_pool = total_paid
        items = self.items.all().order_by('created_at')
        
        for item in items:
            if remaining_pool <= 0:
                item.paid_amount = 0
            elif remaining_pool >= item.amount:
                item.paid_amount = item.amount
                remaining_pool -= item.amount
            else:
                item.paid_amount = remaining_pool
                remaining_pool = 0
            
            # Using update to avoid recursive save calls
            self.items.filter(id=item.id).update(paid_amount=item.paid_amount)
        
        # After distributing, update the status without triggering distribute again
        self.update_totals()


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True)
    inventory_item = models.ForeignKey('inventory.InventoryItem', on_delete=models.SET_NULL, null=True, blank=True)
    
    name = models.CharField(max_length=255, help_text="Snapshot of item name at time of invoice creation")
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price at moment of sale")
    amount = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_invoice_items')
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    @property
    def balance(self):
        return self.amount - self.paid_amount

    @property
    def is_settled(self):
        return self.paid_amount >= self.amount

    @property
    def is_dispensed(self):
        """
        Checks if this item has been physically dispensed.
        Matches by inventory_item, visit, and quantity.
        """
        if not self.inventory_item or not self.invoice.visit:
            return False
            
        from inventory.models import DispensedItem
        return DispensedItem.objects.filter(
            visit=self.invoice.visit,
            item=self.inventory_item,
            quantity=self.quantity
        ).exists()

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
        ('Free Visit', 'Free Visit'),
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
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Distribute payment to invoice items (FIFO)
        self.invoice.distribute_payments()
        
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
