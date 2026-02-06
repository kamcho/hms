from django.contrib import admin
from .models import Ward, Bed, Admission, MedicationChart, ServiceAdmissionLink

@admin.register(Ward)
class WardAdmin(admin.ModelAdmin):
    list_display = ('name', 'ward_type', 'base_charge_per_day')
    list_filter = ('ward_type',)

@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ('bed_number', 'ward', 'is_occupied', 'bed_type')
    list_filter = ('ward', 'is_occupied', 'bed_type')

@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = ('patient', 'bed', 'admitted_at', 'status')
    list_filter = ('status', 'admitted_at', 'bed__ward')
    search_fields = ('patient__first_name', 'patient__last_name', 'provisional_diagnosis')

@admin.register(MedicationChart)
class MedicationChartAdmin(admin.ModelAdmin):
    list_display = ('item', 'admission', 'dosage', 'frequency', 'is_administered')
    list_filter = ('is_administered', 'prescribed_at')

@admin.register(ServiceAdmissionLink)
class ServiceAdmissionLinkAdmin(admin.ModelAdmin):
    list_display = ('service', 'admission', 'quantity', 'date_provided')
    list_filter = ('date_provided', 'service__category')

from .models import PatientVitals, ClinicalNote, FluidBalance, WardTransfer

@admin.register(PatientVitals)
class PatientVitalsAdmin(admin.ModelAdmin):
    list_display = ('admission', 'temperature', 'pulse_rate', 'systolic_bp', 'diastolic_bp', 'recorded_at')
    list_filter = ('recorded_at',)

@admin.register(ClinicalNote)
class ClinicalNoteAdmin(admin.ModelAdmin):
    list_display = ('admission', 'note_type', 'created_at', 'created_by')
    list_filter = ('note_type', 'created_at')

@admin.register(FluidBalance)
class FluidBalanceAdmin(admin.ModelAdmin):
    list_display = ('admission', 'fluid_type', 'amount_ml', 'item', 'recorded_at')
    list_filter = ('fluid_type', 'recorded_at')

@admin.register(WardTransfer)
class WardTransferAdmin(admin.ModelAdmin):
    list_display = ('admission', 'from_bed', 'to_bed', 'transferred_at')
    list_filter = ('transferred_at',)
