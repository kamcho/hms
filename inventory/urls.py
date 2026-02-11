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
]
