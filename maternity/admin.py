from django.contrib import admin
from .models import (
    Pregnancy, AntenatalVisit, LaborDelivery, 
    Newborn, PostnatalMotherVisit, PostnatalBabyVisit,
    MaternityDischarge, MaternityReferral, Vaccine, ImmunizationRecord
)


class AntenatalVisitInline(admin.TabularInline):
    model = AntenatalVisit
    extra = 0
    fields = ['visit_number', 'visit_date', 'gestational_age', 'bp_systolic', 'bp_diastolic', 'fetal_heart_rate']
    readonly_fields = ['visit_date']


class NewbornInline(admin.TabularInline):
    model = Newborn
    extra = 0
    fields = ['baby_number', 'gender', 'birth_weight', 'apgar_1min', 'apgar_5min', 'status']


@admin.register(Pregnancy)
class PregnancyAdmin(admin.ModelAdmin):
    list_display = ['id', 'patient', 'para_code', 'gestational_age_weeks', 'edd', 'risk_level', 'status']
    list_filter = ['status', 'risk_level', 'registration_date']
    search_fields = ['patient__first_name', 'patient__last_name', 'patient__patient_id']
    readonly_fields = ['para_code', 'gestational_age_weeks', 'created_at', 'updated_at']
    inlines = [AntenatalVisitInline]
    
    fieldsets = (
        ('Patient Information', {
            'fields': ('patient', 'registration_date', 'created_by')
        }),
        ('Pregnancy Details', {
            'fields': ('lmp', 'edd', 'gravida', 'para', 'abortion', 'living', 'para_code', 'gestational_age_weeks')
        }),
        ('Medical History', {
            'fields': ('blood_group', 'allergies', 'previous_cs', 'chronic_conditions')
        }),
        ('Current Status', {
            'fields': ('status', 'risk_level')
        }),
    )


@admin.register(AntenatalVisit)
class AntenatalVisitAdmin(admin.ModelAdmin):
    list_display = ['pregnancy', 'visit_number', 'visit_date', 'gestational_age', 'bp_reading', 'fetal_heart_rate']
    list_filter = ['visit_date', 'hiv_status']
    search_fields = ['pregnancy__patient__first_name', 'pregnancy__patient__last_name']
    readonly_fields = ['created_at']
    
    def bp_reading(self, obj):
        if obj.bp_systolic and obj.bp_diastolic:
            return f"{obj.bp_systolic}/{obj.bp_diastolic}"
        return "-"
    bp_reading.short_description = 'BP'


@admin.register(LaborDelivery)
class LaborDeliveryAdmin(admin.ModelAdmin):
    list_display = ['pregnancy_patient', 'delivery_datetime', 'delivery_mode', 'gestational_age_at_delivery', 'mother_condition']
    list_filter = ['delivery_mode', 'labor_onset', 'mother_condition', 'delivery_datetime']
    search_fields = ['pregnancy__patient__first_name', 'pregnancy__patient__last_name']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [NewbornInline]
    
    def pregnancy_patient(self, obj):
        return obj.pregnancy.patient.full_name
    pregnancy_patient.short_description = 'Patient'
    
    fieldsets = (
        ('Pregnancy & Admission', {
            'fields': ('pregnancy', 'admission', 'admission_date', 'gestational_age_at_delivery')
        }),
        ('Labor', {
            'fields': ('labor_onset', 'rupture_of_membranes', 'labor_duration')
        }),
        ('Delivery', {
            'fields': ('delivery_datetime', 'delivery_mode', 'delivery_by')
        }),
        ('Complications', {
            'fields': ('maternal_complications', 'episiotomy', 'perineal_tear', 'estimated_blood_loss', 'blood_transfusion')
        }),
        ('Placenta', {
            'fields': ('placenta_delivery',)
        }),
        ('Outcome', {
            'fields': ('mother_condition', 'delivery_notes')
        }),
    )


@admin.register(Newborn)
class NewbornAdmin(admin.ModelAdmin):
    list_display = ['delivery_patient', 'baby_number', 'gender', 'birth_weight', 'apgar_1min', 'apgar_5min', 'status']
    list_filter = ['gender', 'status', 'resuscitation_required', 'birth_datetime']
    search_fields = ['delivery__pregnancy__patient__first_name', 'delivery__pregnancy__patient__last_name']
    readonly_fields = ['created_at']
    
    def delivery_patient(self, obj):
        return f"{obj.delivery.pregnancy.patient.full_name} - Baby {obj.baby_number}"
    delivery_patient.short_description = 'Baby'


@admin.register(PostnatalMotherVisit)
class PostnatalMotherVisitAdmin(admin.ModelAdmin):
    list_display = ['delivery_patient', 'visit_day', 'visit_date', 'bp_reading', 'breastfeeding_status']
    list_filter = ['visit_date', 'breastfeeding_status', 'mood_assessment']
    search_fields = ['delivery__pregnancy__patient__first_name', 'delivery__pregnancy__patient__last_name']
    readonly_fields = ['created_at']
    
    def delivery_patient(self, obj):
        return obj.delivery.pregnancy.patient.full_name
    delivery_patient.short_description = 'Patient'
    
    def bp_reading(self, obj):
        if obj.bp_systolic and obj.bp_diastolic:
            return f"{obj.bp_systolic}/{obj.bp_diastolic}"
        return "-"
    bp_reading.short_description = 'BP'


@admin.register(PostnatalBabyVisit)
class PostnatalBabyVisitAdmin(admin.ModelAdmin):
    list_display = ['newborn_info', 'visit_day', 'visit_date', 'weight', 'feeding_type', 'jaundice']
    list_filter = ['visit_date', 'feeding_type', 'jaundice', 'umbilical_cord']
    search_fields = ['newborn__delivery__pregnancy__patient__first_name', 'newborn__delivery__pregnancy__patient__last_name']
    readonly_fields = ['created_at']
    
    def newborn_info(self, obj):
        return f"Baby {obj.newborn.baby_number} - {obj.newborn.delivery.pregnancy.patient.full_name}"
    newborn_info.short_description = 'Baby'

@admin.register(MaternityDischarge)
class MaternityDischargeAdmin(admin.ModelAdmin):
    list_display = ['pregnancy', 'discharge_date', 'mother_condition_at_discharge', 'discharged_by']
    list_filter = ['discharge_date', 'mother_condition_at_discharge']
    search_fields = ['pregnancy__patient__first_name', 'pregnancy__patient__last_name']
    readonly_fields = ['created_at']


@admin.register(MaternityReferral)
class MaternityReferralAdmin(admin.ModelAdmin):
    list_display = ['pregnancy', 'referral_date', 'referred_to_facility', 'urgent', 'referred_by']
    list_filter = ['referral_date', 'urgent', 'transport_mode']
    search_fields = ['pregnancy__patient__first_name', 'pregnancy__patient__last_name', 'referred_to_facility']
    readonly_fields = ['created_at']

@admin.register(Vaccine)
class VaccineAdmin(admin.ModelAdmin):
    list_display = ['name', 'abbreviation', 'route']
    search_fields = ['name', 'abbreviation']


@admin.register(ImmunizationRecord)
class ImmunizationRecordAdmin(admin.ModelAdmin):
    list_display = ['newborn_info', 'vaccine', 'dose_number', 'date_administered', 'administered_by']
    list_filter = ['date_administered', 'vaccine']
    search_fields = ['newborn__delivery__pregnancy__patient__first_name', 'newborn__delivery__pregnancy__patient__last_name']
    readonly_fields = ['created_at']

    def newborn_info(self, obj):
        return f"Baby {obj.newborn.baby_number} - {obj.newborn.delivery.pregnancy.patient.full_name}"
    newborn_info.short_description = 'Baby'
