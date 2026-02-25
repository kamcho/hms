from django.urls import path
from . import views

app_name = 'maternity'

urlpatterns = [
    path('', views.maternity_dashboard, name='dashboard'),
    path('register/', views.register_pregnancy, name='register_pregnancy'),
    path('register/external/', views.register_external_delivery, name='register_external_delivery'),
    path('pregnancy/<int:pregnancy_id>/', views.pregnancy_detail, name='pregnancy_detail'),
    path('pregnancy/<int:pregnancy_id>/update-blood-group/', views.update_pregnancy_blood_group, name='update_pregnancy_blood_group'),
    path('pregnancy/<int:pregnancy_id>/anc/add/', views.record_anc_visit, name='record_anc_visit'),
    path('pregnancy/<int:pregnancy_id>/anc/<int:visit_id>/edit/', views.record_anc_visit, name='edit_anc_visit'),
    path('anc/visit/<int:visit_id>/close/', views.close_anc_visit, name='close_anc_visit'),
    path('pregnancy/<int:pregnancy_id>/delivery/add/', views.record_delivery, name='record_delivery'),
    path('pregnancy/<int:pregnancy_id>/newborn/add/', views.register_newborn, name='register_newborn'),
    path('newborn/<int:newborn_id>/edit/', views.edit_newborn, name='edit_newborn'),
    path('pregnancy/<int:pregnancy_id>/pnc/mother/add/', views.record_mother_pnc_visit, name='record_mother_pnc_visit'),
    path('newborn/<int:newborn_id>/pnc/add/', views.record_baby_pnc_visit, name='record_baby_pnc_visit'),
    path('anc/', views.anc_dashboard, name='anc_dashboard'),
    path('anc/arrivals/<int:que_id>/receive/', views.receive_anc_arrival, name='receive_anc_arrival'),
    path('pnc/', views.pnc_dashboard, name='pnc_dashboard'),
    path('pnc/arrivals/<int:que_id>/receive/', views.receive_pnc_arrival, name='receive_pnc_arrival'),
    path('pregnancy/<int:pregnancy_id>/discharge/', views.record_maternity_discharge, name='record_maternity_discharge'),
    path('pregnancy/<int:pregnancy_id>/referral/', views.record_maternity_referral, name='record_maternity_referral'),
    path('newborn/<int:newborn_id>/vaccination/add/', views.record_vaccination, name='record_vaccination'),
    path('vaccination/', views.vaccination_dashboard, name='vaccination_dashboard'),
    path('vaccination/administer/<int:que_id>/', views.administer_vaccine, name='administer_vaccine'),
    path('visit-queue-center/', views.visit_queue_center, name='visit_queue_center'),

    path('referral/<int:referral_id>/print/', views.generate_referral_letter, name='generate_referral_letter'),
    path('pregnancy/<int:pregnancy_id>/discharge/print/', views.generate_discharge_summary, name='generate_discharge_summary'),
]
