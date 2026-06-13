from django.urls import path
from . import views, loan_views

app_name = 'inventory'

urlpatterns = [
    path('items/', views.item_list, name='item_list'),
    path('items/add/', views.add_item, name='add_item'),
    path('items/<int:item_id>/add-stock/', views.add_stock, name='add_stock'),
    path('requests/create/', views.create_request, name='create_request'),
    path('requests/', views.request_list, name='request_list'),
    path('requests/<int:request_id>/update/', views.update_request_status, name='update_request_status'),
    
    # Dispensing APIs
    path('api/search/', views.search_inventory, name='search_inventory'),
    path('api/dispense/', views.dispense_item, name='dispense_item'),
    
    # Procurement
    path('procurement/', views.procurement_dashboard, name='procurement_dashboard'),
    path('procurement/add/', views.add_inventory_purchase, name='add_inventory_purchase'),
    path('procurement/<int:grn_id>/add-items/', views.add_grn_item, name='add_grn_item'),
    path('procurement/<int:grn_id>/delete-item/<int:record_id>/', views.delete_grn_item, name='delete_grn_item'),
    path('stock-activity/', views.stock_activity, name='stock_activity'),
    path('items/<int:item_id>/distribution/', views.inventory_distribution, name='inventory_distribution'),
    path('items/<int:item_id>/update-details/', views.update_item_details, name='update_item_details'),
    path('items/<int:item_id>/reconcile/<int:location_id>/', views.reconcile_stock, name='reconcile_stock'),
    path('items/<int:item_id>/delete/', views.delete_item, name='delete_item'),
    path('clean-duplicates/', views.clean_duplicates, name='clean_duplicates'),
    path('transfer/', views.transfer_stock, name='transfer_stock'),
    path('record-usage/', views.record_usage, name='record_usage'),
    
    # IPD Pharmacy
    path('ipd-pharmacy/', views.ipd_pharmacy_dashboard, name='ipd_pharmacy_dashboard'),
    path('ipd-pharmacy/fulfill/', views.confirm_ipd_fulfillment, name='confirm_ipd_fulfillment'),

    # Inter-facility stock loans
    path('loan-institutions/', loan_views.loan_institution_list, name='loan_institution_list'),
    path('loan-institutions/add/', loan_views.loan_institution_create, name='loan_institution_create'),
    path('loan-institutions/<int:pk>/', loan_views.loan_institution_detail, name='loan_institution_detail'),
    path('loan-institutions/<int:pk>/edit/', loan_views.loan_institution_edit, name='loan_institution_edit'),
    path('stock-loans/', loan_views.stock_loan_list, name='stock_loan_list'),
    path('stock-loans/create/', loan_views.stock_loan_create, name='stock_loan_create'),
    path('stock-loans/<int:pk>/', loan_views.stock_loan_detail, name='stock_loan_detail'),
    path('stock-loans/<int:pk>/lines/<int:line_id>/return/', loan_views.stock_loan_return, name='stock_loan_return'),
    path('stock-loans/<int:pk>/lines/<int:line_id>/writeoff/', loan_views.stock_loan_writeoff, name='stock_loan_writeoff'),
    path('api/loan-item-stock/', loan_views.api_loan_item_stock, name='api_loan_item_stock'),
]
