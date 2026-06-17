from django.contrib import admin
from .models import (
    Ward,
    Bed,
    Admission,
    MedicationChart,
    ServiceAdmissionLink,
    InpatientConsumable,
)


class MedicationChartInline(admin.TabularInline):
    model = MedicationChart
    extra = 0
    verbose_name = 'Medication chart entry'
    verbose_name_plural = 'Medication chart'
    fields = (
        'item',
        'administration_type',
        'dose_count',
        'frequency',
        'quantity',
        'duration_days',
        'total_quantity',
        'quantity_dispensed',
        'is_dispensed',
        'is_active',
        'prescribed_at',
        'prescribed_by',
        'instructions',
    )
    readonly_fields = ('prescribed_at',)
    autocomplete_fields = ('item', 'prescribed_by')
    show_change_link = True


class InpatientConsumableInline(admin.TabularInline):
    model = InpatientConsumable
    extra = 0
    verbose_name = 'Prescribed consumable'
    verbose_name_plural = 'Prescribed consumables'
    fields = (
        'item',
        'quantity',
        'total_quantity',
        'quantity_dispensed',
        'is_dispensed',
        'prescribed_at',
        'prescribed_by',
        'request_location',
        'instructions',
    )
    readonly_fields = ('prescribed_at',)
    autocomplete_fields = ('item', 'prescribed_by', 'request_location')
    show_change_link = True


@admin.register(Ward)
class WardAdmin(admin.ModelAdmin):
    list_display = ('name', 'ward_type', 'base_charge_per_day')
    list_filter = ('ward_type',)

@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ('bed_number', 'ward', 'is_occupied', 'bed_type')
    list_filter = ('ward', 'is_occupied', 'bed_type')
    search_fields = ('bed_number', 'ward__name')

@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = ('patient', 'bed', 'admitted_at', 'status', 'medication_count', 'consumable_count')
    list_filter = ('status', 'admitted_at', 'bed__ward')
    search_fields = ('patient__first_name', 'patient__last_name', 'provisional_diagnosis')
    readonly_fields = ('admitted_at',)
    autocomplete_fields = ('patient', 'visit', 'bed', 'admitted_by', 'discharged_by')
    inlines = [MedicationChartInline, InpatientConsumableInline]
    fieldsets = (
        (None, {
            'fields': ('patient', 'visit', 'bed', 'status', 'admitted_at', 'admitted_by'),
        }),
        ('Clinical', {
            'fields': ('provisional_diagnosis', 'final_diagnosis', 'discharge_summary'),
        }),
        ('Discharge', {
            'fields': ('discharged_at', 'discharged_by'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Chart meds')
    def medication_count(self, obj):
        return obj.medications.count()

    @admin.display(description='Consumables')
    def consumable_count(self, obj):
        return obj.consumables.count()

@admin.register(MedicationChart)
class MedicationChartAdmin(admin.ModelAdmin):
    list_display = ('item', 'admission', 'frequency', 'quantity', 'is_dispensed', 'is_administered')
    list_filter = ('is_dispensed', 'is_administered', 'is_active', 'prescribed_at')
    search_fields = ('item__name', 'admission__patient__first_name', 'admission__patient__last_name')
    autocomplete_fields = ('admission', 'item', 'prescribed_by')


@admin.register(InpatientConsumable)
class InpatientConsumableAdmin(admin.ModelAdmin):
    list_display = ('item', 'admission', 'quantity', 'is_dispensed', 'prescribed_at')
    list_filter = ('is_dispensed', 'prescribed_at')
    search_fields = ('item__name', 'admission__patient__first_name', 'admission__patient__last_name')
    autocomplete_fields = ('admission', 'item', 'prescribed_by')

@admin.register(ServiceAdmissionLink)
class ServiceAdmissionLinkAdmin(admin.ModelAdmin):
    list_display = ('service', 'admission', 'quantity', 'date_provided')
    list_filter = ('date_provided', 'service__department')

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
