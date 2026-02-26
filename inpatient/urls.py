from django.urls import path
from . import views

app_name = 'inpatient'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('patients/<int:patient_id>/admit/', views.admit_patient, name='admit_patient'),
    path('admissions/<int:admission_id>/case-folder/', views.patient_case_folder, name='patient_case_folder'),
    path('admissions/<int:admission_id>/add-vitals/', views.add_vitals, name='add_vitals'),
    path('admissions/<int:admission_id>/add-note/', views.add_clinical_note, name='add_clinical_note'),
    path('admissions/<int:admission_id>/add-fluid/', views.add_fluid_balance, name='add_fluid'),
    path('admissions/<int:admission_id>/transfer/', views.transfer_patient, name='transfer_patient'),
    path('admissions/<int:admission_id>/add-medication/', views.add_medication, name='add_medication'),
    path('medications/<int:medication_id>/administer/', views.administer_medication, name='administer_medication'),
    path('admissions/<int:admission_id>/add-service/', views.add_service, name='add_service'),
    path('admissions/<int:admission_id>/add-instruction/', views.add_doctor_instruction, name='add_doctor_instruction'),
    path('instructions/<int:instruction_id>/complete/', views.complete_instruction, name='complete_instruction'),
    path('admissions/<int:admission_id>/add-nutrition/', views.add_nutrition_order, name='add_nutrition'),
    path('admissions/<int:admission_id>/discharge/', views.discharge_patient, name='discharge_patient'),
    path('discharges/<int:pk>/summary/', views.discharge_summary, name='discharge_summary'),
    path('discharges/<int:pk>/summary/print/', views.discharge_summary, {'template_name': 'inpatient/discharge_summary_printable.html'}, name='discharge_summary_print'),
    path('wards/<int:ward_id>/available-beds/', views.get_available_beds, name='get_available_beds'),
    path('admit/new/', views.admission_patient_list, name='new_admission'),
]
