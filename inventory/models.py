from django.db import models
from django.conf import settings
from django.utils import timezone

class Supplier(models.Model):
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=200, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

class DrugClass(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Drug Classes"

    def __str__(self):
        return self.name

class InventoryCategory(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Inventory Categories"
        ordering = ['name']

    def __str__(self):
        return self.name

class InventoryItem(models.Model):

    
    name = models.CharField(max_length=200)
    category = models.ForeignKey(InventoryCategory, on_delete=models.CASCADE, related_name='items')
    
    # Dispensing Logic
    dispensing_unit = models.CharField(max_length=50, help_text="Smallest unit sold (e.g., Tablet, ml, Piece)")
    is_dispensed_as_whole = models.BooleanField(default=False, help_text="If true, item is only sold as a whole unit (e.g., a small box)")
    
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Selling price per dispensing unit")
    buying_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Cost price per dispensing unit")
    reorder_level = models.IntegerField(default=10, help_text="Minimum stock level before reordering")
    is_updated = models.BooleanField(default=False, help_text="Set to True once the item has been reviewed/updated")
    # SHA benefit intervention for pharmacy billing / preauth advisories
    sha_intervention_code = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text="SHA intervention code for preauth / claims (optional)",
    )

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Medication(models.Model):
    """
    Local pharmaceutical master aligned to DHA HPT terminology.

    Prescribe standard = GE* generic product (strength + form).
    Ingredient ≈ AC*; optional preferred pack ≈ PH* (actual_product_code).
    """
    FORMULATION_CHOICES = [
        ('Tablet', 'Tablet'),
        ('Capsule', 'Capsule'),
        ('Syrup', 'Syrup'),
        ('Injection', 'Injection'),
        ('Infusion', 'Infusion'),
        ('Ointment', 'Ointment'),
        ('Drops', 'Drops'),
        ('Inhaler', 'Inhaler'),
        ('Suppository', 'Suppository'),
        ('Cream', 'Cream'),
        ('Suspension', 'Suspension'),
        ('Solution', 'Solution'),
        ('Other', 'Other'),
    ]
    STRENGTH_UNIT_CHOICES = [
        ('mg', 'mg'),
        ('g', 'g'),
        ('ml', 'ml'),
        ('mcg', 'mcg'),
        ('IU', 'IU'),
        ('%', '%'),
        ('other', 'Other'),
    ]

    item = models.OneToOneField(InventoryItem, on_delete=models.CASCADE, related_name='medication')
    # Local / clinical labels (kept for UX; prefer DHA display when mapped)
    generic_name = models.CharField(max_length=200, help_text="Active ingredient / INN (≈ DHA AC*)")
    drug_class = models.ForeignKey(DrugClass, on_delete=models.SET_NULL, null=True, blank=True, related_name='medications')
    formulation = models.CharField(max_length=50, choices=FORMULATION_CHOICES)

    # DHA HPT — generic product (GE*) used as eRx generic_concept_code
    generic_concept_code = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="DHA HPT GE* code (e.g. GE10177)",
    )
    generic_concept_display = models.CharField(
        max_length=255,
        blank=True,
        help_text="DHA fully specified name (e.g. Paracetamol 500 mg Oral Tablet)",
    )
    active_component_code = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="DHA HPT AC* active component code",
    )
    strength_amount = models.CharField(max_length=32, blank=True, help_text="e.g. 500")
    strength_unit = models.CharField(
        max_length=16,
        blank=True,
        choices=STRENGTH_UNIT_CHOICES,
        help_text="e.g. mg",
    )
    atc_code = models.CharField(max_length=16, blank=True, help_text="WHO ATC code from DHA")
    dha_form_id = models.CharField(max_length=32, blank=True)
    dha_route_id = models.CharField(max_length=32, blank=True)
    # Preferred registered pack for this stocked item (dispense / actual_product_code)
    actual_product_code = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Optional DHA HPT PH* pack code for the product usually stocked",
    )
    dha_mapped_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        if self.generic_concept_display:
            return self.generic_concept_display
        if self.strength_amount and self.strength_unit:
            return f"{self.generic_name} {self.strength_amount} {self.strength_unit} {self.formulation}"
        return f"{self.generic_name}"

    @property
    def is_dha_mapped(self) -> bool:
        return bool((self.generic_concept_code or "").strip())

    def standard_display_name(self) -> str:
        """Prefer DHA FSN; otherwise compose local strength + form."""
        if (self.generic_concept_display or "").strip():
            return self.generic_concept_display.strip()
        parts = [self.generic_name]
        if self.strength_amount and self.strength_unit:
            parts.append(f"{self.strength_amount} {self.strength_unit}")
        if self.formulation:
            parts.append(self.formulation)
        return " ".join(p for p in parts if p).strip() or self.item.name


class ConsumableDetail(models.Model):
    item = models.OneToOneField(InventoryItem, on_delete=models.CASCADE, related_name='consumable_detail')
    material = models.CharField(max_length=100, blank=True, null=True, help_text="e.g., Plastic, Glass, Latex")
    is_sterile = models.BooleanField(default=False)
    size = models.CharField(max_length=50, blank=True, null=True, help_text="e.g., 5ml, 21G, Medium")

    def __str__(self):
        return f"Details for {self.item.name}"

class StockRecord(models.Model):
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='stock_records')
    batch_number = models.CharField(max_length=100)
    quantity = models.IntegerField()
    expiry_date = models.DateField(blank=True, null=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    received_date = models.DateField(auto_now_add=True)
    receiving_notes = models.TextField(blank=True, null=True, help_text="Notes on condition during receipt")
    purchase_ref = models.ForeignKey('accounts.InventoryPurchase', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_records')
    current_location = models.ForeignKey('home.Departments', on_delete=models.CASCADE, related_name='stock_records')

    def __str__(self):
        return f"{self.item.name} - Batch {self.batch_number} at {self.current_location}"

class StockAdjustment(models.Model):
    ADJUSTMENT_TYPES = [
        ('Usage', 'Usage'),
        ('Damage', 'Damage'),
        ('Disposal', 'Disposal'),
        ('Addition', 'Addition'),
        ('Correction', 'Correction'),
        ('Loan Out', 'Loan Out'),
        ('Loan Return', 'Loan Return'),
        ('Loan Write-off', 'Loan Write-off'),
    ]
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='adjustments')
    quantity = models.IntegerField(help_text="Use negative numbers for stock reduction")
    adjustment_type = models.CharField(max_length=25, choices=ADJUSTMENT_TYPES)
    reason = models.TextField()
    adjusted_at = models.DateTimeField(auto_now_add=True)
    adjusted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    adjusted_from = models.ForeignKey('home.Departments', on_delete=models.CASCADE)
    stock_loan_line = models.ForeignKey(
        'StockLoanLine',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='adjustments',
    )

    def __str__(self):
        return f"{self.item.name} - {self.adjustment_type} ({self.quantity}) from {self.adjusted_from}"


class ExternalInstitution(models.Model):
    """Neighbor / partner hospital that borrows stock from us."""

    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def outstanding_line_count(self):
        from django.db.models import F
        return (
            StockLoanLine.objects.filter(
                loan__institution=self,
                loan__status__in=['Open', 'Partial'],
            )
            .annotate(
                outstanding_qty=F('quantity_lent') - F('quantity_returned') - F('quantity_written_off'),
            )
            .filter(outstanding_qty__gt=0)
            .count()
        )


class StockLoan(models.Model):
    STATUS_CHOICES = [
        ('Open', 'Open'),
        ('Partial', 'Partially returned'),
        ('Closed', 'Closed'),
    ]

    institution = models.ForeignKey(
        ExternalInstitution,
        on_delete=models.PROTECT,
        related_name='loans',
    )
    source_department = models.ForeignKey(
        'home.Departments',
        on_delete=models.PROTECT,
        related_name='stock_loans_out',
    )
    loan_date = models.DateTimeField(default=timezone.now)
    expected_return_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Open')
    notes = models.TextField(blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='stock_loans_issued',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-loan_date']

    def __str__(self):
        return f'Loan #{self.id} — {self.institution.name}'

    def refresh_status(self):
        lines = self.lines.all()
        if not lines.exists():
            self.status = 'Closed'
        elif all(line.outstanding <= 0 for line in lines):
            self.status = 'Closed'
        elif any(line.quantity_returned > 0 or line.quantity_written_off > 0 for line in lines):
            self.status = 'Partial'
        else:
            self.status = 'Open'
        self.save(update_fields=['status'])

    @property
    def total_outstanding(self):
        return sum(max(0, line.outstanding) for line in self.lines.all())


class StockLoanLine(models.Model):
    loan = models.ForeignKey(StockLoan, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name='loan_lines')
    batch_number = models.CharField(max_length=100)
    quantity_lent = models.PositiveIntegerField()
    quantity_returned = models.PositiveIntegerField(default=0)
    quantity_written_off = models.PositiveIntegerField(default=0)
    expiry_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.item.name} x{self.quantity_lent} (Loan #{self.loan_id})'

    @property
    def outstanding(self):
        return self.quantity_lent - self.quantity_returned - self.quantity_written_off


class InventoryRequest(models.Model):
    location = models.ForeignKey('home.Departments', on_delete=models.CASCADE, related_name='inventory_requests')
    requested_from = models.ForeignKey('home.Departments', on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_source_requests')
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='requests')
    quantity = models.IntegerField()
    adjusted_quantity = models.IntegerField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=[('Pending', 'Pending'), ('Approved', 'Approved'), ('Rejected', 'Rejected')], default='Pending')

    def __str__(self):
        return f"{self.item.name} - {self.quantity} for {self.location}"

class InventoryAcknowledgement(models.Model):
    request = models.ForeignKey(InventoryRequest, on_delete=models.CASCADE, related_name='acknowledgements')
    received_at = models.DateTimeField(auto_now_add=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    def __str__(self):
        return f"{self.request.item.name} - {self.request.quantity} - {self.request.location}"

class DispensedItem(models.Model):
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='dispensed_items')
    patient = models.ForeignKey('home.Patient', on_delete=models.CASCADE, related_name='dispensed_items')
    visit = models.ForeignKey('home.Visit', on_delete=models.SET_NULL, null=True, blank=True, related_name='dispensed_items')
    quantity = models.IntegerField(help_text="Quantity Dispensed")
    dispensed_at = models.DateTimeField(auto_now_add=True)
    dispensed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='dispensed_items')
    department = models.ForeignKey('home.Departments', on_delete=models.SET_NULL, null=True, related_name='dispensed_items')
    
    class Meta:
        ordering = ['-dispensed_at']

    def __str__(self):
        return f"{self.item.name} x{self.quantity} to {self.patient}"