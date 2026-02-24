from django.urls import path
from . import views

app_name = 'morgue'

urlpatterns = [
    # Dashboard
    path('', views.morgue_dashboard, name='dashboard'),
    
    # Deceased CRUD
    path('deceased/', views.DeceasedListView.as_view(), name='deceased_list'),
    path('deceased/create/', views.DeceasedCreateView.as_view(), name='deceased_create'),
    path('deceased/<int:pk>/', views.DeceasedDetailView.as_view(), name='deceased_detail'),
    path('deceased/<int:pk>/update/', views.DeceasedUpdateView.as_view(), name='deceased_update'),
    path('deceased/<int:pk>/delete/', views.DeceasedDeleteView.as_view(), name='deceased_delete'),
    
    # Next of Kin
    path('deceased/<int:deceased_pk>/next-of-kin/add/', views.NextOfKinCreateView.as_view(), name='next_of_kin_create'),
    
    # Admission and Release
    path('deceased/<int:deceased_pk>/admission/', views.create_admission, name='create_admission'),
    path('deceased/<int:pk>/release/', views.release_deceased, name='release_deceased'),
    
    # Mortuary Services
    path('deceased/<int:deceased_pk>/log-service/', views.log_mortuary_service, name='log_service'),
    path('management/', views.morgue_management, name='morgue_management'),
    path('management/add-morgue/', views.add_morgue, name='add_morgue'),
    path('management/add-chamber/', views.add_chamber, name='add_chamber'),
    path('deceased/<int:deceased_pk>/create-invoice/', views.create_deceased_invoice, name='create_deceased_invoice'),
    path('discharges/<int:pk>/summary/', views.discharge_summary, name='discharge_summary'),
]
