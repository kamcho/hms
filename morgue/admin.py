from django.contrib import admin
from .models import Deceased, NextOfKin, MorgueAdmission, PerformedMortuaryService, MortuaryDischarge


class NextOfKinInline(admin.TabularInline):
    model = NextOfKin
    extra = 1
    fields = ['name', 'relationship', 'phone', 'email', 'is_primary']


class MorgueAdmissionInline(admin.TabularInline):
    model = MorgueAdmission
    extra = 0
    readonly_fields = ['admission_number', 'admission_datetime', 'created_by']
    fields = ['admission_number', 'status', 'admission_datetime', 'release_date', 'released_to', 'created_by']


@admin.register(Deceased)
class DeceasedAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'tag', 'sex', 'date_of_death', 'time_of_death', 'storage_chamber', 'is_released', 'created_at']
    list_filter = ['sex', 'deceased_type', 'scheme', 'storage_area', 'storage_chamber', 'is_released', 'date_of_death']
    search_fields = ['surname', 'other_names', 'tag', 'id_number']
    readonly_fields = ['created_at', 'updated_at', 'created_by']
    inlines = [NextOfKinInline, MorgueAdmissionInline]
    
    fieldsets = (
        ('Deceased Details', {
            'fields': ('deceased_type', 'surname', 'other_names', 'sex', 'scheme', 'id_type', 'id_number')
        }),
        ('Physical Address', {
            'fields': ('physical_address', 'residence', 'town', 'nationality')
        }),
        ('Death Details', {
            'fields': ('date_of_death', 'time_of_death', 'place_of_death', 'cause_of_death')
        }),
        ('Admission Details', {
            'fields': ('storage_area', 'storage_chamber', 'expected_removal_date', 'tag')
        }),
        ('System Information', {
            'fields': ('is_released', 'release_date', 'created_at', 'updated_at', 'created_by'),
            'classes': ('collapse',)
        })
    )
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(NextOfKin)
class NextOfKinAdmin(admin.ModelAdmin):
    list_display = ['name', 'deceased', 'relationship', 'phone', 'is_primary']
    list_filter = ['relationship', 'is_primary']
    search_fields = ['name', 'deceased__surname', 'deceased__other_names', 'phone']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PerformedMortuaryService)
class PerformedMortuaryServiceAdmin(admin.ModelAdmin):
    list_display = ('service', 'deceased', 'quantity', 'date_performed')
    list_filter = ('date_performed', 'service__department')
    search_fields = ('deceased__surname', 'deceased__other_names', 'service__name')

@admin.register(MortuaryDischarge)
class MortuaryDischargeAdmin(admin.ModelAdmin):
    list_display = ('deceased', 'discharge_date', 'released_to', 'total_bill_snapshot', 'authorized_by')
    list_filter = ('discharge_date', 'authorized_by')
    search_fields = ('deceased__surname', 'deceased__other_names', 'released_to')
    readonly_fields = ('total_bill_snapshot', 'authorized_by', 'discharge_date')


@admin.register(MorgueAdmission)
class MorgueAdmissionAdmin(admin.ModelAdmin):
    list_display = ['admission_number', 'deceased', 'status', 'created_at', 'release_date', 'released_to']
    list_filter = ['status', 'created_at', 'release_date']
    search_fields = ['admission_number', 'deceased__surname', 'deceased__other_names', 'released_to']
    readonly_fields = ['admission_number', 'created_at', 'updated_at', 'created_by']
    
    fieldsets = (
        ('Admission Information', {
            'fields': ('deceased', 'admission_number', 'status')
        }),
        ('Release Information', {
            'fields': ('release_date', 'released_to', 'release_notes'),
            'classes': ('collapse',)
        }),
        ('System Information', {
            'fields': ('created_at', 'updated_at', 'created_by'),
            'classes': ('collapse',)
        })
    )
