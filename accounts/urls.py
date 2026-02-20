from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('accountant/dashboard/', views.accountant_dashboard, name='accountant_dashboard'),
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('invoice/create/', views.create_invoice, name='create_invoice'),
    path('invoice/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoice/<int:pk>/payment/', views.record_payment, name='record_payment'),
    path('invoice/<int:pk>/delete/', views.delete_invoice, name='delete_invoice'),
    path('invoice/item/<int:item_id>/delete/', views.delete_invoice_item, name='delete_invoice_item'),
    
    # Expense Module
    path('expenses/', views.expense_dashboard, name='expense_dashboard'),
    path('expenses/add/', views.add_expense, name='add_expense'),
    path('expenses/category/add/', views.add_expense_category, name='add_expense_category'),
    path('expenses/invoice/add/', views.add_supplier_invoice, name='add_supplier_invoice'),
    path('expenses/payment/add/', views.record_supplier_payment, name='record_supplier_payment'),

    # Discharge Billing
    path('discharge/dashboard/', views.discharge_billing_dashboard, name='discharge_dashboard'),
    path('discharge/detail/<str:admission_type>/<int:admission_id>/', views.discharge_billing_detail, name='discharge_detail'),
    path('discharge/authorize/<int:pk>/', views.authorize_discharge, name='authorize_discharge'),

    # Insurance Manager
    path('insurance-manager/', views.insurance_manager, name='insurance_manager'),
    path('api/insurance/invoice-items/<int:invoice_id>/', views.get_invoice_items, name='get_invoice_items'),
    path('api/insurance/process-claim/', views.process_insurance_claim, name='process_insurance_claim'),
    
    # Procedure APIs
    path('api/procedures/search/', views.search_procedures, name='search_procedures'),
    path('api/procedures/charge/', views.charge_procedure, name='charge_procedure'),
]
