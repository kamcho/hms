from django.contrib import admin
from .models import Patient, Departments, PatientQue, Visit, TriageEntry, Consultation, ConsultationNotes, EmergencyContact, Prescription
# Register your models here.
admin.site.register(Patient)
admin.site.register(Departments)
admin.site.register(PatientQue)
admin.site.register(Visit)
admin.site.register(TriageEntry)
admin.site.register(Consultation)
admin.site.register(ConsultationNotes)

admin.site.register(Prescription)
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

# Unregister and re-register Patient with new admin
admin.site.unregister(Patient)
admin.site.register(Patient, PatientAdmin)
