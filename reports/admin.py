from django.contrib import admin

from .models import NvipLineDefinition, NvipMonthlyReport, NvipReportLine


class NvipReportLineInline(admin.TabularInline):
    model = NvipReportLine
    extra = 0
    readonly_fields = ('line_definition',)


@admin.register(NvipLineDefinition)
class NvipLineDefinitionAdmin(admin.ModelAdmin):
    list_display = ('sort_order', 'antigen', 'age_group', 'row_key', 'is_active')
    list_filter = ('is_active', 'section')
    search_fields = ('antigen', 'row_key')


@admin.register(NvipMonthlyReport)
class NvipMonthlyReportAdmin(admin.ModelAdmin):
    list_display = ('facility_name', 'month', 'year', 'status', 'updated_at')
    list_filter = ('year', 'month', 'status')
    inlines = [NvipReportLineInline]
