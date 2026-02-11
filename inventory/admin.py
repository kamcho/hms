from django.contrib import admin
from .models import Supplier, InventoryCategory, InventoryItem, StockRecord, StockAdjustment, InventoryRequest

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'phone', 'email')
    search_fields = ('name', 'contact_person')

@admin.register(InventoryCategory)
class InventoryCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')

@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'dispensing_unit', 'selling_price', 'is_dispensed_as_whole')
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

@admin.register(InventoryRequest)
class InventoryRequestAdmin(admin.ModelAdmin):
    list_display = ('item', 'quantity', 'location', 'status', 'requested_at', 'requested_by')
    list_filter = ('status', 'requested_at', 'location')
    search_fields = ('item__name', 'requested_by__username')
