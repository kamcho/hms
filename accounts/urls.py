from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('accountant/dashboard/', views.accountant_dashboard, name='accountant_dashboard'),
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('invoice/create/', views.create_invoice, name='create_invoice'),
    path('invoice/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoice/<int:pk>/payment/', views.record_payment, name='record_payment'),
    path('payment/<int:payment_id>/receipt/', views.print_receipt, name='print_receipt'),
    path('invoice/<int:pk>/delete/', views.delete_invoice, name='delete_invoice'),
    path('invoice/item/<int:item_id>/delete/', views.delete_invoice_item, name='delete_invoice_item'),
    path('invoice/item/<int:item_id>/price/', views.update_invoice_item_price, name='update_invoice_item_price'),
    path('invoice/<int:pk>/maternity-sha-rebate/', views.apply_maternity_sha_rebate, name='apply_maternity_sha_rebate'),
    
    # Expense Module
    path('expenses/', views.expense_dashboard, name='expense_dashboard'),
    path('expenses/add/', views.add_expense, name='add_expense'),
    path('expenses/category/add/', views.add_expense_category, name='add_expense_category'),
    path('expenses/invoice/add/', views.add_supplier_invoice, name='add_supplier_invoice'),
    path('expenses/payment/add/', views.record_supplier_payment, name='record_supplier_payment'),
    path('expenses/supplier/add/', views.add_supplier, name='add_supplier'),

    # Discharge Billing
    path('discharge/dashboard/', views.discharge_billing_dashboard, name='discharge_dashboard'),
    path('discharge/detail/<str:admission_type>/<int:admission_id>/', views.discharge_billing_detail, name='discharge_detail'),
    path('discharge/authorize/<int:pk>/', views.authorize_discharge, name='authorize_discharge'),

    # Insurance Manager
    path('insurance-manager/', views.insurance_manager, name='insurance_manager'),
    path('api/insurance/invoice-items/<int:invoice_id>/', views.get_invoice_items, name='get_invoice_items'),
    path('api/insurance/process-claim/', views.process_insurance_claim, name='process_insurance_claim'),
    path('api/discharge-code/<int:visit_id>/', views.get_discharge_code, name='get_discharge_code'),
    
    # Procedure APIs
    path('api/procedures/search/', views.search_procedures, name='search_procedures'),
    path('api/procedures/charge/', views.charge_procedure, name='charge_procedure'),

    # Service Management
    path('services/', views.service_list, name='service_list'),
    path('services/create/', views.create_service, name='create_service'),
    path('services/<int:pk>/edit/', views.edit_service, name='edit_service'),
    path('services/<int:pk>/toggle/', views.toggle_service, name='toggle_service'),

    # SHA Manager
    path('api/visit/set-sha/', views.set_visit_sha, name='set_visit_sha'),
    path('api/visit/bulk-set-sha/', views.bulk_set_visit_sha, name='bulk_set_visit_sha'),
    path('api/sha/patient-by-id/', views.sha_patient_by_id_number, name='sha_patient_by_id'),
    path('api/sha/eligibility/', views.sha_patient_by_id_number, name='sha_eligibility_api'),
    path('api/sha/diagnostics/', views.sha_diagnostics_api, name='sha_diagnostics_api'),
    path('api/sha/facility-by-code/', views.sha_facility_by_code, name='sha_facility_by_code'),
    path('api/sha/create-visit/', views.sha_create_visit_from_eligibility, name='sha_create_visit'),
    path('api/sha/consent/contacts/', views.sha_consent_contacts, name='sha_consent_contacts'),
    path('api/sha/consent/send-otp/', views.sha_consent_send_otp, name='sha_consent_send_otp'),
    path('api/sha/consent/authorize/', views.sha_consent_authorize, name='sha_consent_authorize'),
    path('sha/eligibility/', views.sha_eligibility_page, name='sha_eligibility'),
    path('sha/facility-search/', views.sha_facility_search_page, name='sha_facility_search'),
    path('sha/claims/<int:visit_id>/', views.sha_claims_desk, name='sha_claims_desk'),
    path('sha/tracker/', views.sha_claims_tracker, name='sha_claims_tracker'),
    path('api/sha/claims/<int:visit_id>/', views.sha_claims_action, name='sha_claims_action'),
    path('api/sha/session/<int:session_id>/live-status/', views.sha_claim_live_status, name='sha_claim_live_status'),

    # Superuser Invoice Manager
    path('manage-invoices/<int:visit_id>/', views.manage_visit_invoices, name='manage_visit_invoices'),
]
