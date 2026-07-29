from django.contrib import admin

from .models import (
    Moh645DailyEntry,
    Moh645DailyReport,
    Moh705bColumnDefinition,
    Moh705bLineDefinition,
    Moh705bMonthlyReport,
    Moh705bReportLine,
    Moh717LineDefinition,
    Moh717MonthlyReport,
    Moh717ReportLine,
    Moh743CommodityDefinition,
    Moh743CommodityLine,
    Moh743MonthlyReport,
    NvipLineDefinition,
    NvipMonthlyReport,
    NvipReportLine,
)


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


@admin.register(Moh705bColumnDefinition)
class Moh705bColumnDefinitionAdmin(admin.ModelAdmin):
    list_display = ('col_number', 'full_label', 'label', 'is_active')


@admin.register(Moh705bLineDefinition)
class Moh705bLineDefinitionAdmin(admin.ModelAdmin):
    list_display = ('line_number', 'disease_name', 'category', 'is_active')
    list_filter = ('category',)


class Moh705bReportLineInline(admin.TabularInline):
    model = Moh705bReportLine
    extra = 0


@admin.register(Moh705bMonthlyReport)
class Moh705bMonthlyReportAdmin(admin.ModelAdmin):
    list_display = ('facility_name', 'month', 'year', 'status', 'updated_at')
    list_filter = ('year', 'month', 'status')
    inlines = [Moh705bReportLineInline]


@admin.register(Moh717LineDefinition)
class Moh717LineDefinitionAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'category', 'sort_order', 'is_active')
    list_filter = ('category',)


class Moh717ReportLineInline(admin.TabularInline):
    model = Moh717ReportLine
    extra = 0


@admin.register(Moh717MonthlyReport)
class Moh717MonthlyReportAdmin(admin.ModelAdmin):
    list_display = ('facility_name', 'month', 'year', 'county', 'status', 'updated_at')
    list_filter = ('year', 'month', 'status')
    inlines = [Moh717ReportLineInline]


class Moh645DailyEntryInline(admin.TabularInline):
    model = Moh645DailyEntry
    extra = 0


@admin.register(Moh645DailyReport)
class Moh645DailyReportAdmin(admin.ModelAdmin):
    list_display = ('facility_name', 'report_date', 'page_number', 'status', 'updated_at')
    list_filter = ('report_date', 'status')
    inlines = [Moh645DailyEntryInline]


@admin.register(Moh743CommodityDefinition)
class Moh743CommodityDefinitionAdmin(admin.ModelAdmin):
    list_display = ('sort_order', 'commodity_name', 'basic_unit', 'row_key', 'is_active')
    list_filter = ('is_active',)


class Moh743CommodityLineInline(admin.TabularInline):
    model = Moh743CommodityLine
    extra = 0


@admin.register(Moh743MonthlyReport)
class Moh743MonthlyReportAdmin(admin.ModelAdmin):
    list_display = ('facility_name', 'month', 'year', 'county', 'status', 'updated_at')
    list_filter = ('year', 'month', 'status')
    inlines = [Moh743CommodityLineInline]
