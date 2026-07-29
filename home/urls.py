from django.urls import path
from . import views


urlpatterns = [
    path('dashboard/', views.reception_dashboard, name='reception_dashboard'),
    path('appointments/', views.appointments_dashboard, name='appointments_dashboard'),
    path('opd-dashboard/', views.opd_dashboard, name='opd_dashboard'),
    path('patients/', views.PatientListView.as_view(), name='patient_list'),
    path('patients/add/', views.PatientCreateView.as_view(), name='patient_create'),
    path('patients/create-sha-household/', views.create_sha_household_patients, name='create_sha_household'),
    path('patients/<int:pk>/', views.PatientDetailView.as_view(), name='patient_detail'),
    path('patients/<int:pk>/edit/', views.PatientUpdateView.as_view(), name='patient_update'),
    path('triage/quick-entry/', views.quick_triage_entry, name='quick_triage_entry'),
    path('triage/create/', views.create_triage_entry, name='create_triage'),
    path('notes/add/', views.add_consultation_note, name='add_consultation_note'),
    path('next-action/submit/', views.submit_next_action, name='submit_next_action'),
    path('symptoms/add/', views.add_symptoms, name='add_symptoms'),
    path('impression/add/', views.add_impression, name='add_impression'),
    path('impression/<int:pk>/update/', views.update_impression, name='update_impression'),
    path('diagnosis/add/', views.add_diagnosis, name='add_diagnosis'),
    path('tb-screening/add/', views.add_tb_screening, name='add_tb_screening'),
    path('diagnosis/<int:pk>/update/', views.update_diagnosis, name='update_diagnosis'),
    path('patients/<int:patient_pk>/problems/add/', views.add_problem, name='add_problem'),
    path('problems/<int:pk>/update/', views.update_problem, name='update_problem'),
    path('patients/<int:patient_pk>/problems/', views.problem_history, name='problem_list'),
    path('problems/<int:pk>/history/', views.problem_detail_history, name='problem_history'),
    path('patients/<int:patient_pk>/medications/add/', views.add_patient_medication, name='add_patient_medication'),
    path('medications/<int:pk>/update/', views.update_patient_medication, name='update_patient_medication'),
    path('patients/<int:patient_pk>/medications/', views.patient_medication_history, name='patient_medication_list'),
    path('patients/<int:patient_pk>/allergies/add/', views.add_patient_allergy, name='add_patient_allergy'),
    path('allergies/<int:pk>/update/', views.update_patient_allergy, name='update_patient_allergy'),
    path('patients/<int:patient_pk>/allergies/', views.patient_allergy_history, name='patient_allergy_list'),
    path('patients/<int:patient_pk>/family-history/add/', views.add_family_history, name='add_family_history'),
    path('family-history/<int:pk>/update/', views.update_family_history, name='update_family_history'),
    path('patients/<int:patient_pk>/growth-chart/', views.patient_growth_chart_api, name='patient_growth_chart'),
    path('visit/<int:visit_id>/clinical-summary/generate/', views.generate_clinical_summary_view, name='generate_clinical_summary'),
    path('clinical-summary/<int:pk>/', views.clinical_summary_detail, name='clinical_summary_detail'),
    path('clinical-summary/<int:pk>/print/', views.clinical_summary_print, name='clinical_summary_print'),
    path('clinical-summary/<int:pk>/fhir.json', views.clinical_summary_fhir_json, name='clinical_summary_fhir'),
    path('clinical-summary/<int:pk>/sync/', views.sync_clinical_summary_view, name='sync_clinical_summary'),
    path('notes/<int:pk>/update/', views.update_consultation_note, name='update_consultation_note'),
    path('patients/<int:pk>/delete/', views.PatientDeleteView.as_view(), name='patient_delete'),
    path('patients/check-active-visit/', views.check_active_visit, name='check_active_visit'),
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
    path('prescription/<int:prescription_id>/edit/', views.edit_prescription, name='edit_prescription'),
    path('prescription/<int:prescription_id>/transmit-erx/', views.transmit_prescription_erx, name='transmit_prescription_erx'),
    path('prescription/patient/<int:patient_id>/', views.prescription_list, name='prescription_list'),
    
    # Pharmacy URLs
    path('pharmacy/dashboard/', views.pharmacy_dashboard, name='pharmacy_dashboard'),
    path('pharmacy/consumable/<int:item_id>/update/', views.api_pharmacy_update_consumable, name='api_pharmacy_update_consumable'),
    path('pharmacy/consumable/<int:item_id>/delete/', views.api_pharmacy_delete_consumable, name='api_pharmacy_delete_consumable'),
    path('pharmacy/dispense-all/<int:visit_id>/', views.dispense_all_visit_items, name='dispense_all_visit_items'),
    path('pharmacy/night-dashboard/', views.night_pharmacy_dashboard, name='night_pharmacy_dashboard'),
    path('pharmacy/night-payment/<int:invoice_id>/', views.night_pharmacy_record_payment, name='night_pharmacy_record_payment'),
    path('pharmacy/night-dispense-all/<int:visit_id>/', views.dispense_night_opd_items, name='dispense_night_opd_items'),
    
    # Health Records
    path('health-records/', views.health_records_view, name='health_records'),
    path('procedure-room/', views.procedure_room_dashboard, name='procedure_room_dashboard'),
    path('procedure-room/visit/<int:visit_id>/', views.procedure_detail, name='procedure_detail'),
    path('procedure-room/item/<int:item_id>/mark-done/', views.mark_procedure_done, name='mark_procedure_done'),
    
    # Ambulance URLs
    path('ambulance/dashboard/', views.ambulance_dashboard, name='ambulance_dashboard'),
    
    # Ward Management URLs
    path('ward-management/', views.ward_management, name='ward_management'),
    path('ward-management/add-ward/', views.add_ward, name='add_ward'),
    path('ward-management/add-bed/', views.add_bed, name='add_bed'),
    path('appointments/add/', views.add_appointment, name='add_appointment'),
    path('appointments/<int:appointment_id>/attend/', views.mark_appointment_attended, name='mark_appointment_attended'),

    # WHO ICD-11
    path('icd11/', views.icd11_search_page, name='icd11_search'),
    path('api/icd11/search/', views.icd11_search_api, name='icd11_search_api'),
    path('api/icd11/validate/', views.icd11_validate_api, name='icd11_validate_api'),
    path('api/icd11/entity/', views.icd11_entity_api, name='icd11_entity_api'),
    path('api/icd11/code/', views.icd11_code_api, name='icd11_code_api'),
    # DHA HPT medication terminology (MOH-PPB)
    path('api/hpt/search/', views.hpt_search_api, name='hpt_search_api'),
    path('api/hpt/suggest/', views.hpt_suggest_api, name='hpt_suggest_api'),
    path('api/hpt/allergy-search/', views.hpt_allergy_search_api, name='hpt_allergy_search_api'),
    # Clinical Decision Support
    path('patients/<int:patient_pk>/cds/', views.clinical_decision_support_api, name='clinical_decision_support'),
    path('patients/<int:patient_pk>/cds/check-medication/', views.cds_check_medication_api, name='cds_check_medication'),
]
