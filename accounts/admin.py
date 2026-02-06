from django.contrib import admin
from .models import (
    Service, Invoice, InvoiceItem, Payment, MpesaPayment, 
    ExpenseCategory, Expense, InventoryPurchase, SupplierInvoice, SupplierPayment, InvoiceItem
)

@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'supplier', 'date', 'total_amount', 'paid_amount', 'status', 'due_date')
    list_filter = ('status', 'supplier', 'date')
    search_fields = ('invoice_number', 'notes')
    date_hierarchy = 'date'

@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'amount', 'date', 'payment_method', 'reference_number')
    list_filter = ('payment_method', 'date')
    search_fields = ('invoice__invoice_number', 'reference_number')

@admin.register(InventoryPurchase)
class InventoryPurchaseAdmin(admin.ModelAdmin):
    list_display = ('date', 'supplier', 'invoice_ref', 'total_amount')
    list_filter = ('supplier', 'date')
    search_fields = ('notes',)
    date_hierarchy = 'date'

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'description')

class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1
    readonly_fields = ('amount',)

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'total_amount', 'paid_amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('patient__first_name', 'patient__last_name')
    inlines = [InvoiceItemInline]
    readonly_fields = ('total_amount', 'paid_amount', 'created_at', 'updated_at')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'invoice', 'amount', 'payment_method', 'transaction_reference', 'payment_date')
    list_filter = ('payment_method', 'payment_date')
    search_fields = ('invoice__id', 'transaction_reference')

@admin.register(MpesaPayment)
class MpesaPaymentAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'amount', 'mpesa_receipt_number', 'is_successful', 'created_at')
    list_filter = ('is_successful', 'created_at')
    search_fields = ('phone_number', 'mpesa_receipt_number', 'checkout_request_id')

admin.site.register(InvoiceItem)