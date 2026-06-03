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


class Moh705bColumnDefinition(models.Model):
    """MOH 705B age/sex column (1–16)."""
    col_key = models.CharField(max_length=16, unique=True)
    col_number = models.PositiveSmallIntegerField(unique=True)
    label = models.CharField(max_length=10, help_text='Header number on form')
    full_label = models.CharField(max_length=80, help_text='Age/sex group')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['col_number']

    def __str__(self):
        return f'{self.col_number}. {self.full_label}'


class Moh705bLineDefinition(models.Model):
    """MOH 705B disease / attendance row."""
    CATEGORY_CHOICES = [
        ('disease', 'Disease'),
        ('attendance', 'Attendance'),
        ('referral', 'Referral'),
        ('other', 'Other'),
        ('spacer', 'Spacer'),
    ]

    row_key = models.CharField(max_length=16, unique=True)
    line_number = models.PositiveSmallIntegerField()
    disease_name = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='disease')
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'line_number']

    def __str__(self):
        return f'{self.line_number}. {self.disease_name or "(blank)"}'


class Moh705bMonthlyReport(models.Model):
    """MOH 705B Outpatient Over 5 years — monthly summary."""

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

    compiled_by = models.CharField(max_length=200, blank=True)
    compiled_designation = models.CharField(max_length=120, blank=True)
    compiled_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='moh705b_reports_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-year', '-month']
        verbose_name = 'MOH 705B Monthly Report'
        constraints = [
            models.UniqueConstraint(
                fields=['facility_name', 'month', 'year'],
                name='unique_moh705b_report_facility_month',
            ),
        ]

    def __str__(self):
        return f'MOH 705B {self.facility_name} — {self.month}/{self.year}'

    @property
    def month_name(self):
        import calendar
        return calendar.month_name[self.month]


class Moh705bReportLine(models.Model):
    """Counts per disease row across 16 columns. column_data: {"1": 0, "2": 0, ...}"""

    report = models.ForeignKey(
        Moh705bMonthlyReport,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    line_definition = models.ForeignKey(
        Moh705bLineDefinition,
        on_delete=models.PROTECT,
        related_name='report_lines',
    )
    column_data = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [['report', 'line_definition']]
        ordering = ['line_definition__sort_order']

    def __str__(self):
        return f'{self.report} — {self.line_definition}'

    def col_count(self, col_number: int) -> int:
        return int(self.column_data.get(str(col_number), 0) or 0)

    def set_col_count(self, col_number: int, count: int):
        data = dict(self.column_data or {})
        data[str(col_number)] = max(0, int(count))
        self.column_data = data

    @property
    def row_total(self) -> int:
        return sum(self.col_count(c) for c in range(1, 17))


class Moh717LineDefinition(models.Model):
    """MOH 717 outpatient service row."""
    CATEGORY_CHOICES = [
        ('section', 'Section header'),
        ('data', 'Data row'),
        ('total', 'Section total'),
        ('summary', 'Summary total'),
    ]

    row_key = models.CharField(max_length=32, unique=True)
    code = models.CharField(max_length=20, blank=True)
    description = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='data')
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order']

    def __str__(self):
        return f'{self.code} {self.description}'.strip()


class Moh717MonthlyReport(models.Model):
    """MOH 717 Monthly Service Workload Report."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
    ]
    MONTH_CHOICES = [(i, i) for i in range(1, 13)]

    facility_name = models.CharField(max_length=200)
    kmhfl_code = models.CharField(max_length=50, blank=True, verbose_name='KMHFL Code')
    month = models.PositiveSmallIntegerField(choices=MONTH_CHOICES)
    year = models.PositiveIntegerField()
    sub_county = models.CharField(max_length=120, blank=True)
    county = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)

    compiled_by = models.CharField(max_length=200, blank=True)
    compiled_designation = models.CharField(max_length=120, blank=True)
    compiled_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='moh717_reports_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-year', '-month']
        verbose_name = 'MOH 717 Monthly Report'
        constraints = [
            models.UniqueConstraint(
                fields=['facility_name', 'month', 'year'],
                name='unique_moh717_report_facility_month',
            ),
        ]

    def __str__(self):
        return f'MOH 717 {self.facility_name} — {self.month}/{self.year}'

    @property
    def month_name(self):
        import calendar
        return calendar.month_name[self.month]


class Moh717ReportLine(models.Model):
    """NEW / RE-ATT counts per service line; total = new + re_att."""

    report = models.ForeignKey(
        Moh717MonthlyReport,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    line_definition = models.ForeignKey(
        Moh717LineDefinition,
        on_delete=models.PROTECT,
        related_name='report_lines',
    )
    new_count = models.PositiveIntegerField(default=0)
    re_att_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [['report', 'line_definition']]
        ordering = ['line_definition__sort_order']

    def __str__(self):
        return f'{self.report} — {self.line_definition}'

    @property
    def total_count(self) -> int:
        return self.new_count + self.re_att_count
