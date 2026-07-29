from django.urls import path
from . import views

app_name = 'inpatient'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('reports/admissions-discharges/', views.admissions_discharges_report, name='admissions_discharges_report'),
    path('clean-admissions/', views.clean_admissions, name='clean_admissions'),
    path('clean-admissions/close/', views.clean_admissions_close, name='clean_admissions_close'),
    path('patients/<int:patient_id>/admit/', views.admit_patient, name='admit_patient'),
    path('admissions/<int:admission_id>/case-folder/', views.patient_case_folder, name='patient_case_folder'),
    path('admissions/<int:admission_id>/manage-chart/', views.manage_patient_chart, name='manage_patient_chart'),
    path('consumables/<int:consumable_id>/update/', views.api_ipd_consumable_update, name='api_ipd_consumable_update'),
    path('consumables/<int:consumable_id>/delete/', views.api_ipd_consumable_delete, name='api_ipd_consumable_delete'),
    path('admissions/<int:admission_id>/edit-date/', views.edit_admission_date, name='edit_admission_date'),
    path('admissions/<int:admission_id>/add-vitals/', views.add_vitals, name='add_vitals'),
    path('admissions/<int:admission_id>/add-note/', views.add_clinical_note, name='add_clinical_note'),
    path('admissions/<int:admission_id>/add-fluid/', views.add_fluid_balance, name='add_fluid'),
    path('admissions/<int:admission_id>/transfer/', views.transfer_patient, name='transfer_patient'),
    path('admissions/<int:admission_id>/add-medication/', views.add_medication, name='add_medication'),
    path('medications/<int:medication_id>/administer/', views.administer_medication, name='administer_medication'),
    path('medications/<int:medication_id>/discontinue/', views.discontinue_medication, name='discontinue_medication'),
    path('admissions/<int:admission_id>/add-service/', views.add_service, name='add_service'),
    path('admissions/<int:admission_id>/add-instruction/', views.add_doctor_instruction, name='add_doctor_instruction'),
    path('instructions/<int:instruction_id>/complete/', views.complete_instruction, name='complete_instruction'),
    path('admissions/<int:admission_id>/add-nutrition/', views.add_nutrition_order, name='add_nutrition'),
    path('admissions/<int:admission_id>/discharge/', views.discharge_patient, name='discharge_patient'),
    path('discharges/<int:pk>/summary/', views.discharge_summary, name='discharge_summary'),
    path('discharges/<int:pk>/summary/print/', views.discharge_summary, {'template_name': 'inpatient/discharge_summary_printable.html'}, name='discharge_summary_print'),
    path('wards/<int:ward_id>/available-beds/', views.get_available_beds, name='get_available_beds'),
    path('admit/new/', views.admission_patient_list, name='new_admission'),
    path('admissions/<int:admission_id>/gatepass/generate/', views.generate_gatepass, name='generate_gatepass'),
    path('gatepasses/<int:pass_id>/view/', views.view_gatepass, name='view_gatepass'),
    path('admissions/<int:admission_id>/move-to-morgue/', views.move_to_morgue, name='move_to_morgue'),
    path('notes/<int:note_id>/edit/', views.edit_clinical_note, name='edit_clinical_note'),
]
