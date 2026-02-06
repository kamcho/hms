from django.urls import path
from django.contrib.auth.views import LogoutView
from django.views.generic import TemplateView
from . import views

app_name = 'users'

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('invoices/mark-paid/<int:patient_id>/', views.mark_invoices_paid, name='mark_invoices_paid'),
    
    # Error pages
    path('404/', TemplateView.as_view(template_name='404.html'), name='404'),
    path('500/', TemplateView.as_view(template_name='500.html'), name='500'),
]
