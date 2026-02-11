from django.db import models
from django.conf import settings

class Supplier(models.Model):
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=200, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)

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

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Medication(models.Model):
    FORMULATION_CHOICES = [
        ('Tablet', 'Tablet'),
        ('Capsule', 'Capsule'),
        ('Syrup', 'Syrup'),
        ('Injection', 'Injection'),
        ('Infusion', 'Infusion'),
        ('Ointment', 'Ointment'),
        ('Drops', 'Drops'),
        ('Inhaler', 'Inhaler'),
    ]
    
    item = models.OneToOneField(InventoryItem, on_delete=models.CASCADE, related_name='medication')
    generic_name = models.CharField(max_length=200)
    drug_class = models.ForeignKey(DrugClass, on_delete=models.SET_NULL, null=True, blank=True, related_name='medications')
    formulation = models.CharField(max_length=50, choices=FORMULATION_CHOICES)

    def __str__(self):
        return f"{self.generic_name}"

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
    ]
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='adjustments')
    quantity = models.IntegerField(help_text="Use negative numbers for stock reduction")
    adjustment_type = models.CharField(max_length=20, choices=ADJUSTMENT_TYPES)
    reason = models.TextField()
    adjusted_at = models.DateTimeField(auto_now_add=True)
    adjusted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    adjusted_from = models.ForeignKey('home.Departments', on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.item.name} - {self.adjustment_type} ({self.quantity}) from {self.adjusted_from}"


class InventoryRequest(models.Model):
    location = models.ForeignKey('home.Departments', on_delete=models.CASCADE, related_name='inventory_requests')
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