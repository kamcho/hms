from django.contrib import admin
from .models import (
    Patient,
    Departments,
    PatientQue,
    Visit,
    TriageEntry,
    Consultation,
    ConsultationNotes,
    EmergencyContact,
    Prescription,
    PrescriptionItem,
)


class PrescriptionItemInline(admin.TabularInline):
    model = PrescriptionItem
    extra = 0
    fields = (
        'medication',
        'dose_count',
        'dose_unit',
        'frequency',
        'number_of_days',
        'quantity',
        'instructions',
        'dispensed',
        'dispensed_at',
        'dispensed_by',
    )
    readonly_fields = ('dispensed_at',)
    autocomplete_fields = ('medication',)
    show_change_link = True


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = (
        'patient',
        'visit',
        'prescribed_by',
        'prescribed_at',
        'status',
        'item_count',
    )
    list_filter = ('status', 'prescribed_at')
    search_fields = (
        'patient__first_name',
        'patient__last_name',
        'diagnosis',
        'visit__id',
    )
    readonly_fields = ('prescribed_at',)
    autocomplete_fields = ('patient', 'visit', 'invoice', 'prescribed_by')
    inlines = [PrescriptionItemInline]
    fieldsets = (
        (None, {
            'fields': ('patient', 'visit', 'invoice', 'prescribed_by', 'prescribed_at', 'status'),
        }),
        ('Clinical', {
            'fields': ('diagnosis', 'notes'),
        }),
    )

    @admin.display(description='Items')
    def item_count(self, obj):
        return obj.items.count()


@admin.register(PrescriptionItem)
class PrescriptionItemAdmin(admin.ModelAdmin):
    list_display = (
        'prescription',
        'medication',
        'frequency',
        'quantity',
        'dispensed',
    )
    list_filter = ('dispensed', 'frequency')
    search_fields = (
        'prescription__patient__first_name',
        'prescription__patient__last_name',
        'medication__name',
    )
    autocomplete_fields = ('prescription', 'medication', 'dispensed_by')


# Register your models here.
admin.site.register(PatientQue)
admin.site.register(TriageEntry)
admin.site.register(Consultation)
admin.site.register(ConsultationNotes)


@admin.register(Departments)
class DepartmentsAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation')
    search_fields = ('name', 'abbreviation')


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'visit_date', 'visit_type', 'is_active')
    list_filter = ('visit_type', 'is_active', 'visit_date')
    search_fields = ('patient__first_name', 'patient__last_name', 'id')
    autocomplete_fields = ('patient',)

class EmergencyContactInline(admin.TabularInline):
    model = EmergencyContact
    extra = 1
    fields = ['name', 'relationship', 'phone', 'email', 'is_primary']


@admin.register(EmergencyContact)
class EmergencyContactAdmin(admin.ModelAdmin):
    list_display = ['name', 'patient', 'relationship', 'phone', 'is_primary']
    list_filter = ['relationship', 'is_primary']
    search_fields = ['name', 'patient__first_name', 'patient__last_name', 'phone']
    readonly_fields = ['created_at', 'updated_at', 'created_by']
    
    fieldsets = (
        ('Contact Information', {
            'fields': ('patient', 'name', 'relationship', 'phone', 'email', 'address', 'is_primary')
        }),
        ('System Information', {
            'fields': ('created_at', 'updated_at', 'created_by'),
            'classes': ('collapse',)
        })
    )
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# Add EmergencyContact inline to Patient admin
@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'age', 'phone', 'location', 'gender', 'created_at']
    list_filter = ['gender', 'created_at']
    search_fields = ['first_name', 'last_name', 'phone']
    readonly_fields = ['created_at', 'updated_at', 'created_by']
    inlines = [EmergencyContactInline]
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
