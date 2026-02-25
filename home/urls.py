from django.urls import path
from . import views


urlpatterns = [
    path('dashboard/', views.reception_dashboard, name='reception_dashboard'),
    path('appointments/', views.appointments_dashboard, name='appointments_dashboard'),
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
    path('visit/<int:visit_id>/refer/', views.refer_patient, name='refer_patient'),
    
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
    path('prescription/create/<int:visit_id>/', views.create_prescription, name='create_prescription'),
    path('prescription/<int:prescription_id>/', views.prescription_detail, name='prescription_detail'),
    path('prescription/patient/<int:patient_id>/', views.prescription_list, name='prescription_list'),
    
    # Pharmacy URLs
    path('pharmacy/dashboard/', views.pharmacy_dashboard, name='pharmacy_dashboard'),
    path('pharmacy/dispense-all/<int:visit_id>/', views.dispense_all_visit_items, name='dispense_all_visit_items'),
    
    # Health Records
    path('health-records/', views.health_records_view, name='health_records'),
    path('procedure-room/', views.procedure_room_dashboard, name='procedure_room_dashboard'),
    path('procedure-room/visit/<int:visit_id>/', views.procedure_detail, name='procedure_detail'),
    
    # Ambulance URLs
    path('ambulance/dashboard/', views.ambulance_dashboard, name='ambulance_dashboard'),
    
    # Ward Management URLs
    path('ward-management/', views.ward_management, name='ward_management'),
    path('ward-management/add-ward/', views.add_ward, name='add_ward'),
    path('ward-management/add-bed/', views.add_bed, name='add_bed'),
    path('appointments/add/', views.add_appointment, name='add_appointment'),
]
