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
    path('moh717/', views.moh717_report_list, name='moh717_list'),
    path('moh717/new/', views.moh717_report_create, name='moh717_create'),
    path('moh717/<int:pk>/', views.moh717_report_edit, name='moh717_edit'),
    path('moh717/<int:pk>/save/', views.moh717_report_save, name='moh717_save'),
    path('moh717/<int:pk>/print/', views.moh717_report_print, name='moh717_print'),
    path('malaria/', views.malaria_reports_hub, name='malaria_hub'),
    path('malaria/moh645/', views.moh645_report_list, name='moh645_list'),
    path('malaria/moh645/new/', views.moh645_report_create, name='moh645_create'),
    path('malaria/moh645/<int:pk>/', views.moh645_report_edit, name='moh645_edit'),
    path('malaria/moh645/<int:pk>/save/', views.moh645_report_save, name='moh645_save'),
    path('malaria/moh645/<int:pk>/sync/', views.moh645_sync_from_hms, name='moh645_sync'),
    path('malaria/moh645/<int:pk>/print/', views.moh645_report_print, name='moh645_print'),
    path('malaria/moh743/', views.moh743_report_list, name='moh743_list'),
    path('malaria/moh743/new/', views.moh743_report_create, name='moh743_create'),
    path('malaria/moh743/<int:pk>/', views.moh743_report_edit, name='moh743_edit'),
    path('malaria/moh743/<int:pk>/save/', views.moh743_report_save, name='moh743_save'),
    path('malaria/moh743/<int:pk>/sync/', views.moh743_sync_from_hms, name='moh743_sync'),
    path('malaria/moh743/<int:pk>/print/', views.moh743_report_print, name='moh743_print'),
]
