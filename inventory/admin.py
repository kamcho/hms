from django.contrib import admin
from .models import (
    Supplier, InventoryCategory, InventoryItem, Medication, StockRecord, StockAdjustment,
    InventoryRequest, ExternalInstitution, StockLoan, StockLoanLine,
)

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'phone', 'email')
    search_fields = ('name', 'contact_person')

@admin.register(InventoryCategory)
class InventoryCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')


class MedicationInline(admin.StackedInline):
    model = Medication
    extra = 0
    fieldsets = (
        (None, {
            'fields': ('generic_name', 'drug_class', 'formulation', 'strength_amount', 'strength_unit'),
        }),
        ('DHA HPT (MOH-PPB)', {
            'fields': (
                'generic_concept_code',
                'generic_concept_display',
                'active_component_code',
                'atc_code',
                'actual_product_code',
                'dha_form_id',
                'dha_route_id',
                'dha_mapped_at',
            ),
        }),
    )
    readonly_fields = ('dha_mapped_at',)


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'dispensing_unit', 'selling_price', 'is_dispensed_as_whole')
    list_filter = ('category',)
    search_fields = ('name', 'medication__generic_concept_code', 'medication__generic_name')
    inlines = [MedicationInline]


@admin.register(Medication)
class MedicationAdmin(admin.ModelAdmin):
    list_display = (
        'generic_name',
        'generic_concept_code',
        'strength_amount',
        'strength_unit',
        'formulation',
        'atc_code',
        'item',
    )
    list_filter = ('formulation', 'strength_unit')
    search_fields = (
        'generic_name',
        'generic_concept_code',
        'generic_concept_display',
        'atc_code',
        'item__name',
    )
    readonly_fields = ('dha_mapped_at',)

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


class StockLoanLineInline(admin.TabularInline):
    model = StockLoanLine
    extra = 0
    readonly_fields = ('item', 'batch_number', 'quantity_lent', 'quantity_returned', 'quantity_written_off')


@admin.register(ExternalInstitution)
class ExternalInstitutionAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'phone', 'is_active')
    search_fields = ('name', 'contact_person')
    list_filter = ('is_active',)


@admin.register(StockLoan)
class StockLoanAdmin(admin.ModelAdmin):
    list_display = ('id', 'institution', 'source_department', 'loan_date', 'status', 'issued_by')
    list_filter = ('status', 'loan_date')
    search_fields = ('institution__name',)
    inlines = [StockLoanLineInline]
