from django.conf import settings
from django.db import models


class NvipLineDefinition(models.Model):
    """Catalog row for MOH 710 Section A (seeded once)."""
    row_key = models.CharField(max_length=64, unique=True)
    antigen = models.CharField(max_length=120)
    age_group = models.CharField(max_length=120, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    section = models.CharField(max_length=10, default='A')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'row_key']

    def __str__(self):
        if self.age_group:
            return f'{self.antigen} — {self.age_group}'
        return self.antigen


class NvipMonthlyReport(models.Model):
    """MOH 710 monthly NVIP summary for a facility."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
    ]

    MONTH_CHOICES = [(i, i) for i in range(1, 13)]

    facility_name = models.CharField(max_length=200)
    kmhfl_code = models.CharField(max_length=50, blank=True, verbose_name='KMHFL Code')
    month = models.PositiveSmallIntegerField(choices=MONTH_CHOICES)
    year = models.PositiveIntegerField()
    ward = models.CharField(max_length=120, blank=True)
    sub_county = models.CharField(max_length=120, blank=True)
    county = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='nvip_reports_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-year', '-month']
        verbose_name = 'NVIP Monthly Report (MOH 710)'
        verbose_name_plural = 'NVIP Monthly Reports (MOH 710)'
        constraints = [
            models.UniqueConstraint(
                fields=['facility_name', 'month', 'year'],
                name='unique_nvip_report_facility_month',
            ),
        ]

    def __str__(self):
        return f'NVIP {self.facility_name} — {self.month}/{self.year}'

    @property
    def month_name(self):
        import calendar
        return calendar.month_name[self.month]


class NvipReportLine(models.Model):
    """
    One MOH 710 row: daily tallies (days 1–31) plus static/outreach month totals.
    daily_data: {"1": {"d": 0, "s": 0, "o": 0}, ...}  d=daily total, s/o optional split
    """

    report = models.ForeignKey(
        NvipMonthlyReport,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    line_definition = models.ForeignKey(
        NvipLineDefinition,
        on_delete=models.PROTECT,
        related_name='report_lines',
    )
    daily_data = models.JSONField(default=dict, blank=True)
    total_static = models.PositiveIntegerField(default=0, help_text='Facility static total')
    total_outreach = models.PositiveIntegerField(default=0, help_text='Outreach total')

    class Meta:
        unique_together = [['report', 'line_definition']]
        ordering = ['line_definition__sort_order']

    def __str__(self):
        return f'{self.report} — {self.line_definition}'

    def day_count(self, day: int) -> int:
        entry = self.daily_data.get(str(day), {})
        if isinstance(entry, dict):
            return int(entry.get('d', 0) or 0)
        return int(entry or 0)

    def set_day_count(self, day: int, count: int, static: int = None, outreach: int = None):
        data = dict(self.daily_data or {})
        cell = {'d': max(0, int(count))}
        if static is not None:
            cell['s'] = max(0, int(static))
        if outreach is not None:
            cell['o'] = max(0, int(outreach))
        data[str(day)] = cell
        self.daily_data = data

    @property
    def computed_daily_sum(self) -> int:
        total = 0
        for day in range(1, 32):
            total += self.day_count(day)
        return total

    @property
    def grand_total(self) -> int:
        ts = self.total_static if self.total_static else self.computed_daily_sum
        return ts + self.total_outreach
