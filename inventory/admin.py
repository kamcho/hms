from django.contrib import admin
from .models import Supplier, InventoryCategory, InventoryItem, StockRecord, StockAdjustment

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'phone', 'email')
    search_fields = ('name', 'contact_person')

@admin.register(InventoryCategory)
class InventoryCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')

@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'unit', 'selling_price', 'reorder_level')
    list_filter = ('category',)
    search_fields = ('name',)

@admin.register(StockRecord)
class StockRecordAdmin(admin.ModelAdmin):
    list_display = ('item', 'batch_number', 'quantity', 'expiry_date', 'supplier', 'received_date')
    list_filter = ('expiry_date', 'supplier', 'item__category')
    search_fields = ('batch_number', 'item__name')

@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ('item', 'quantity', 'adjustment_type', 'adjusted_at', 'adjusted_by')
    list_filter = ('adjustment_type', 'adjusted_at')
    search_fields = ('item__name', 'reason')
