from django.urls import path
from . import views


urlpatterns = [
    path('dashboard/', views.reception_dashboard, name='reception_dashboard'),
    path('opd-dashboard/', views.opd_dashboard, name='opd_dashboard'),
    path('patients/', views.PatientListView.as_view(), name='patient_list'),
    path('patients/add/', views.PatientCreateView.as_view(), name='patient_create'),
    path('patients/<int:pk>/', views.PatientDetailView.as_view(), name='patient_detail'),
    path('patients/<int:pk>/edit/', views.PatientUpdateView.as_view(), name='patient_update'),
    path('triage/quick-entry/', views.quick_triage_entry, name='quick_triage_entry'),
    path('triage/create/', views.create_triage_entry, name='create_triage'),
    path('notes/add/', views.add_consultation_note, name='add_consultation_note'),
    path('next-action/submit/', views.submit_next_action, name='submit_next_action'),
    path('symptoms/add/', views.add_symptoms, name='add_symptoms'),
    path('impression/add/', views.add_impression, name='add_impression'),
    path('diagnosis/add/', views.add_diagnosis, name='add_diagnosis'),
    path('patients/<int:pk>/delete/', views.PatientDeleteView.as_view(), name='patient_delete'),
    path('patients/admit/', views.admit_patient_visit, name='admit_patient_visit'),
    
    # Emergency Contact URLs
    path('patients/<int:patient_pk>/emergency-contact/add/', 
         views.EmergencyContactCreateView.as_view(), name='emergency_contact_create'),
    path('emergency-contact/<int:pk>/edit/', 
         views.EmergencyContactUpdateView.as_view(), name='emergency_contact_update'),
    path('emergency-contact/<int:pk>/delete/', 
         views.EmergencyContactDeleteView.as_view(), name='emergency_contact_delete'),
    path('patients/<int:patient_pk>/emergency-contact/<int:contact_pk>/set-primary/', 
         views.set_primary_emergency_contact, name='set_primary_emergency_contact'),
    
    # Prescription URLs
    path('prescription/create/<int:patient_id>/', views.create_prescription, name='create_prescription'),
    path('prescription/<int:prescription_id>/', views.prescription_detail, name='prescription_detail'),
    path('prescription/patient/<int:patient_id>/', views.prescription_list, name='prescription_list'),
    
    # Pharmacy URLs
    path('pharmacy/dashboard/', views.pharmacy_dashboard, name='pharmacy_dashboard'),
    path('pharmacy/dispense/<int:item_id>/', views.dispense_medication, name='dispense_medication'),
    path('pharmacy/dispense-all/<int:prescription_id>/', views.dispense_all_medications, name='dispense_all_medications'),
    path('pharmacy/dispense-ipd/<int:item_id>/', views.dispense_ipd_medication, name='dispense_ipd_medication'),
]
