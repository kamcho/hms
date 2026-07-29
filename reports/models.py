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


class Moh645DailyReport(models.Model):
    """MOH 645 — Health Facility Daily Activity Register for Malaria Commodities."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
    ]

    facility_name = models.CharField(max_length=200)
    report_date = models.DateField()
    page_number = models.PositiveSmallIntegerField(default=1)
    receipt_date = models.DateField(null=True, blank=True)
    receipt_reference = models.CharField(max_length=120, blank=True)
    balance_previous = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Balance from previous page (A)')
    qty_received = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Quantities received (B)')
    losses = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Losses (D)')
    remarks = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='moh645_reports_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-report_date', '-page_number']
        verbose_name = 'MOH 645 Daily Malaria Register'
        constraints = [
            models.UniqueConstraint(
                fields=['facility_name', 'report_date', 'page_number'],
                name='unique_moh645_facility_date_page',
            ),
        ]

    def __str__(self):
        return f'MOH 645 {self.facility_name} — {self.report_date} p{self.page_number}'

    @property
    def total_stock_available(self):
        return self.balance_previous + self.qty_received

    @property
    def total_dispensed(self):
        return sum(entry.total_dispensed_qty for entry in self.entries.all())

    @property
    def balance_end(self):
        return self.total_stock_available - self.total_dispensed - self.losses


class Moh645DailyEntry(models.Model):
    """One patient row on MOH 645."""

    VISIT_TYPE_CHOICES = [('IP', 'In-Patient'), ('OP', 'Out-Patient')]
    TEST_METHOD_CHOICES = [
        ('none', 'No test done'),
        ('microscopy', 'Microscopy'),
        ('mrdt', 'mRDT'),
    ]
    TEST_RESULT_CHOICES = [
        ('', '—'),
        ('positive', 'Positive'),
        ('negative', 'Negative'),
        ('invalid', 'Invalid'),
    ]
    AL_BAND_CHOICES = [
        ('', '—'),
        ('lt15', '<15 Kg (<3 yrs)'),
        ('bw15_25', '15 to <25 Kg (3 to <8 yrs)'),
        ('bw25_35', '25 to <35 Kg (8 to <12 yrs)'),
        ('gte35', '35+ Kg (≥12 yrs)'),
    ]

    report = models.ForeignKey(Moh645DailyReport, on_delete=models.CASCADE, related_name='entries')
    visit = models.ForeignKey('home.Visit', on_delete=models.SET_NULL, null=True, blank=True)
    patient_name = models.CharField(max_length=200, blank=True)
    visit_type = models.CharField(max_length=2, choices=VISIT_TYPE_CHOICES, default='OP')
    test_method = models.CharField(max_length=20, choices=TEST_METHOD_CHOICES, default='none')
    test_result = models.CharField(max_length=10, choices=TEST_RESULT_CHOICES, blank=True, default='')
    al_weight_band = models.CharField(max_length=10, choices=AL_BAND_CHOICES, blank=True, default='')
    qty_rdts = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    qty_al_6 = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    qty_al_12 = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    qty_al_18 = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    qty_al_24 = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    qty_artesunate = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    source = models.CharField(max_length=20, default='manual')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.patient_name or "Entry"} — {self.report.report_date}'

    @property
    def total_dispensed_qty(self):
        return (
            self.qty_rdts + self.qty_al_6 + self.qty_al_12
            + self.qty_al_18 + self.qty_al_24 + self.qty_artesunate
        )


class Moh743CommodityDefinition(models.Model):
    """Catalog row for MOH 743 commodity lines."""

    row_key = models.CharField(max_length=32, unique=True)
    commodity_name = models.CharField(max_length=200)
    basic_unit = models.CharField(max_length=40)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order']

    def __str__(self):
        return self.commodity_name


class Moh743MonthlyReport(models.Model):
    """MOH 743 — Health Facility Monthly Summary Report for Malaria Commodities."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
    ]
    MONTH_CHOICES = [(i, i) for i in range(1, 13)]
    FACILITY_LEVEL_CHOICES = [(str(i), f'Level {i}') for i in range(2, 7)]

    facility_name = models.CharField(max_length=200)
    kmhfl_code = models.CharField(max_length=50, blank=True)
    county = models.CharField(max_length=120, blank=True)
    sub_county = models.CharField(max_length=120, blank=True)
    facility_level = models.CharField(max_length=2, choices=FACILITY_LEVEL_CHOICES, blank=True)
    month = models.PositiveSmallIntegerField(choices=MONTH_CHOICES)
    year = models.PositiveIntegerField()
    period_begin = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)

    al_stockout_days = models.PositiveIntegerField(default=0)
    iptp_pregnant_women = models.PositiveIntegerField(default=0)
    comments = models.TextField(blank=True)

    diagnostics_data = models.JSONField(default=dict, blank=True)
    al_weight_data = models.JSONField(default=dict, blank=True)

    prepared_by = models.CharField(max_length=200, blank=True)
    prepared_signature = models.CharField(max_length=200, blank=True)
    prepared_date = models.DateField(null=True, blank=True)
    prepared_phone = models.CharField(max_length=30, blank=True)
    reviewed_by = models.CharField(max_length=200, blank=True)
    reviewed_signature = models.CharField(max_length=200, blank=True)
    reviewed_date = models.DateField(null=True, blank=True)
    reviewed_phone = models.CharField(max_length=30, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='moh743_reports_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-year', '-month']
        verbose_name = 'MOH 743 Monthly Malaria Summary'
        constraints = [
            models.UniqueConstraint(
                fields=['facility_name', 'month', 'year'],
                name='unique_moh743_facility_month',
            ),
        ]

    def __str__(self):
        return f'MOH 743 {self.facility_name} — {self.month}/{self.year}'

    @property
    def month_name(self):
        import calendar
        return calendar.month_name[self.month]


class Moh743CommodityLine(models.Model):
    """One commodity row on MOH 743 with columns A–J."""

    report = models.ForeignKey(Moh743MonthlyReport, on_delete=models.CASCADE, related_name='lines')
    line_definition = models.ForeignKey(
        Moh743CommodityDefinition,
        on_delete=models.PROTECT,
        related_name='report_lines',
    )
    col_a = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Beginning balance')
    col_b = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Received')
    col_c = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Dispensed')
    col_d = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Losses')
    col_e = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Positive adjustments')
    col_f = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Negative adjustments')
    col_g = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Physical count')
    col_h = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Expired')
    col_i = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='6 months to expiry')
    col_j = models.PositiveIntegerField(default=0, verbose_name='Days out of stock')

    class Meta:
        unique_together = [['report', 'line_definition']]
        ordering = ['line_definition__sort_order']

    def __str__(self):
        return f'{self.report} — {self.line_definition}'

    @property
    def quantity_to_reorder(self):
        return max(self.col_c, 0)
