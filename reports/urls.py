from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_hub, name='hub'),
    path('nvip/', views.nvip_report_list, name='nvip_list'),
    path('nvip/new/', views.nvip_report_create, name='nvip_create'),
    path('nvip/<int:pk>/', views.nvip_report_edit, name='nvip_edit'),
    path('nvip/<int:pk>/save/', views.nvip_report_save, name='nvip_save'),
    path('nvip/<int:pk>/sync/', views.nvip_sync_immunization, name='nvip_sync'),
    path('nvip/<int:pk>/print/', views.nvip_report_print, name='nvip_print'),
]
