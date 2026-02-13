from django.urls import path
from . import views

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
]
