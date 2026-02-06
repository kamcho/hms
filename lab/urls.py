from django.urls import path
from . import views

app_name = 'lab'

urlpatterns = [
    path('dashboard/', views.radiology_dashboard, name='radiology_dashboard'),
    path('results/', views.LabResultListView.as_view(), name='lab_result_list'),
    path('result/<int:result_id>/', views.lab_result_detail, name='lab_result_detail'),
    path('create/<int:invoice_id>/', views.create_lab_result, name='create_lab_result'),
]
