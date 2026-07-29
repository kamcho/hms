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
    Icd11Code,
    Problem,
    ProblemHistory,
    PatientMedication,
    PatientMedicationHistory,
    PatientAllergy,
    PatientAllergyHistory,
    ClinicalSummary,
    FamilyHistory,
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
    fields = ['given_name', 'family_name', 'name', 'role', 'relationship', 'phone', 'email', 'is_primary']


@admin.register(EmergencyContact)
class EmergencyContactAdmin(admin.ModelAdmin):
    list_display = ['name', 'patient', 'role', 'relationship', 'phone', 'is_primary']
    list_filter = ['role', 'relationship', 'is_primary']
    search_fields = ['name', 'given_name', 'family_name', 'patient__first_name', 'patient__last_name', 'phone']
    readonly_fields = ['created_at', 'updated_at', 'created_by']

    fieldsets = (
        ('Contact Information', {
            'fields': (
                'patient', 'given_name', 'family_name', 'name',
                'role', 'relationship', 'phone', 'email', 'address', 'is_primary',
            )
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
    list_display = [
        'full_name', 'id_type', 'id_number', 'cr_id', 'age',
        'phone', 'county', 'gender', 'created_at',
    ]
    list_filter = ['gender', 'id_type', 'county', 'created_at']
    search_fields = [
        'first_name', 'last_name', 'phone', 'id_number', 'cr_id',
        'national_id', 'passport_number', 'birth_certificate_number',
    ]
    readonly_fields = ['created_at', 'updated_at', 'created_by', 'age']
    inlines = [EmergencyContactInline]
    fieldsets = (
        ('Name', {
            'fields': ('first_name', 'last_name'),
        }),
        ('Identifiers (KNHTS / KPS.A)', {
            'fields': (
                'id_type', 'id_number',
                'national_id', 'passport_number', 'birth_certificate_number',
                'cr_id', 'insurance_number',
            ),
        }),
        ('Demographics', {
            'fields': ('date_of_birth', 'age', 'gender', 'phone', 'email'),
        }),
        ('Residence (KPS.A address)', {
            'fields': (
                'country', 'county', 'sub_county', 'ward', 'village',
                'postal_address', 'location',
            ),
        }),
        ('System', {
            'fields': ('created_at', 'updated_at', 'created_by'),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Icd11Code)
class Icd11CodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'title_plain', 'class_kind', 'chapter_no', 'is_leaf', 'release')
    list_filter = ('release', 'linearization', 'class_kind', 'is_leaf', 'chapter_no')
    search_fields = ('code', 'title', 'title_plain', 'entity_id')
    readonly_fields = ('linearization_uri', 'foundation_uri')


class ProblemHistoryInline(admin.TabularInline):
    model = ProblemHistory
    extra = 0
    readonly_fields = (
        'action', 'display', 'icd11_code', 'clinical_status', 'verification_status',
        'change_summary', 'changed_at', 'changed_by',
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    list_display = (
        'display', 'patient', 'icd11_code', 'clinical_status',
        'verification_status', 'updated_at',
    )
    list_filter = ('clinical_status', 'verification_status', 'category', 'severity')
    search_fields = (
        'display', 'icd11_code',
        'patient__first_name', 'patient__last_name', 'patient__id_number',
    )
    autocomplete_fields = ('patient', 'icd11_entry')
    readonly_fields = ('recorded_at', 'updated_at')
    inlines = [ProblemHistoryInline]


class PatientMedicationHistoryInline(admin.TabularInline):
    model = PatientMedicationHistory
    extra = 0
    readonly_fields = (
        'action', 'display_name', 'generic_concept_code', 'status',
        'change_summary', 'changed_at', 'changed_by',
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PatientMedication)
class PatientMedicationAdmin(admin.ModelAdmin):
    list_display = (
        'display_name', 'patient', 'generic_concept_code', 'status',
        'source', 'updated_at',
    )
    list_filter = ('status', 'source')
    search_fields = (
        'display_name', 'generic_concept_code',
        'patient__first_name', 'patient__last_name',
    )
    autocomplete_fields = ('patient',)
    readonly_fields = ('recorded_at', 'updated_at')
    inlines = [PatientMedicationHistoryInline]


class PatientAllergyHistoryInline(admin.TabularInline):
    model = PatientAllergyHistory
    extra = 0
    readonly_fields = (
        'action', 'allergen_name', 'hpt_code', 'clinical_status',
        'change_summary', 'changed_at', 'changed_by',
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PatientAllergy)
class PatientAllergyAdmin(admin.ModelAdmin):
    list_display = (
        'allergen_name', 'patient', 'hpt_code', 'clinical_status',
        'severity', 'category', 'updated_at',
    )
    list_filter = ('clinical_status', 'category', 'allergy_type', 'severity')
    search_fields = (
        'allergen_name', 'hpt_code',
        'patient__first_name', 'patient__last_name',
    )
    autocomplete_fields = ('patient',)
    readonly_fields = ('recorded_at', 'updated_at')
    inlines = [PatientAllergyHistoryInline]


@admin.register(FamilyHistory)
class FamilyHistoryAdmin(admin.ModelAdmin):
    list_display = (
        'patient', 'relationship', 'condition', 'onset_age',
        'is_deceased', 'status', 'recorded_at',
    )
    list_filter = ('relationship', 'status', 'is_deceased')
    search_fields = (
        'condition', 'relative_name', 'icd11_code',
        'patient__first_name', 'patient__last_name',
    )
    autocomplete_fields = ('patient',)
    readonly_fields = ('recorded_at', 'updated_at')


@admin.register(ClinicalSummary)
class ClinicalSummaryAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'patient', 'visit', 'status', 'hie_sync_status',
        'includes_care_plan', 'generated_at',
    )
    list_filter = ('status', 'hie_sync_status')
    search_fields = (
        'patient__first_name', 'patient__last_name', 'hie_document_id',
    )
    readonly_fields = (
        'narrative_text', 'summary_json', 'fhir_bundle', 'sync_payload',
        'hie_sync_raw', 'generated_at', 'synced_at', 'updated_at',
    )
    autocomplete_fields = ('patient', 'visit')
