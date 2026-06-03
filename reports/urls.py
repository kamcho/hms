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
    path('moh705b/', views.moh705b_report_list, name='moh705b_list'),
    path('moh705b/new/', views.moh705b_report_create, name='moh705b_create'),
    path('moh705b/<int:pk>/', views.moh705b_report_edit, name='moh705b_edit'),
    path('moh705b/<int:pk>/save/', views.moh705b_report_save, name='moh705b_save'),
    path('moh705b/<int:pk>/print/', views.moh705b_report_print, name='moh705b_print'),
]
