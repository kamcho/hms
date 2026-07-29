"""Sync MOH 645 / MOH 743 malaria reports from lab tests and pharmacy dispensing."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from inventory.models import DispensedItem
from lab.models import LabResult

from .models import (
    Moh645DailyEntry,
    Moh645DailyReport,
    Moh743CommodityDefinition,
    Moh743CommodityLine,
    Moh743MonthlyReport,
)

MALARIA_LAB_FILTER = Q(service__name__icontains='malaria') | Q(service__name__icontains='mps')
MRDT_KEYWORDS = ('mrdt', 'rdt', 'rapid')
MICROSCOPY_KEYWORDS = ('microscopy', 'blood smear', 'mps', 'bs', 'thick', 'thin')

COMMODITY_ITEM_PATTERNS = {
    'al_6': ('lumefantrin', '6 tab'),
    'al_12': ('lumefantrin', '12 tab'),
    'al_18': ('lumefantrin', '18 tab'),
    'al_24': ('lumefantrin', '24 tab'),
    'artesunate_60': ('artesunate', '60'),
    'quinine_200': ('quinine', '200'),
    'quinine_300': ('quinine', '300'),
    'quinine_inj': ('quinine', 'inj'),
    'sp': ('sulphadoxine', 'pyrimethamine'),
    'dhp_160': ('dihydroartemisinin', '160'),
    'dhp_320': ('dihydroartemisinin', '320'),
    'rdts': ('rdt',),
    'llins': ('llin', 'mosquito net'),
}

DEFAULT_DIAGNOSTICS = {
    'microscopy': {'positive': 0, 'negative': 0, 'invalid': 0},
    'mrdt': {'positive': 0, 'negative': 0, 'invalid': 0},
    'not_tested': 0,
}

DEFAULT_AL_WEIGHT = {
    'lt15': 0,
    'bw15_25': 0,
    'bw25_35': 0,
    'gte35': 0,
}


def _empty_diagnostics():
    return {
        'microscopy': {'positive': 0, 'negative': 0, 'invalid': 0},
        'mrdt': {'positive': 0, 'negative': 0, 'invalid': 0},
        'not_tested': 0,
    }


def _empty_al_weight():
    return {'lt15': 0, 'bw15_25': 0, 'bw25_35': 0, 'gte35': 0}


def _parse_test_method(service_name: str, results_text: str = '') -> str:
    name = (service_name or '').lower()
    text = (results_text or '').lower()
    combined = f'{name} {text}'
    if any(k in combined for k in MRDT_KEYWORDS):
        return 'mrdt'
    if any(k in combined for k in MICROSCOPY_KEYWORDS):
        return 'microscopy'
    if 'test' in name and 'malaria' in name:
        return 'mrdt'
    return 'microscopy'


def _parse_test_result(results: str = '', interpretation: str = '') -> str:
    text = f'{results or ""} {interpretation or ""}'.lower()
    if 'invalid' in text:
        return 'invalid'
    if any(tok in text for tok in ('positive', 'pos', 'reactive', 'detected')):
        return 'positive'
    if any(tok in text for tok in ('negative', 'neg', 'non-reactive', 'not detected')):
        return 'negative'
    return ''


def _visit_for_lab_result(lab_result: LabResult):
    if lab_result.invoice_id and lab_result.invoice.visit_id:
        return lab_result.invoice.visit
    if lab_result.completed_at:
        return (
            lab_result.patient.visits.filter(
                visit_date__date=lab_result.completed_at.date(),
            )
            .order_by('-id')
            .first()
        )
    return lab_result.patient.visits.order_by('-id').first()


def _visit_type_code(visit) -> str:
    if not visit:
        return 'OP'
    return 'IP' if visit.visit_type == 'IN-PATIENT' else 'OP'


def _patient_display_name(patient) -> str:
    return getattr(patient, 'full_name', None) or str(patient)


def _commodity_key_for_dispensed_item(item) -> str | None:
    name = (item.name or '').lower()
    unit = (item.dispensing_unit or '').lower()
    blob = f'{name} {unit}'
    for key, patterns in COMMODITY_ITEM_PATTERNS.items():
        if all(p in blob for p in patterns):
            return key
    if 'lumefantrin' in blob or 'lumefantrine' in blob:
        for pack, token in (('al_6', '6'), ('al_12', '12'), ('al_18', '18'), ('al_24', '24')):
            if token in unit or f'{token} tab' in blob:
                return pack
    return None


def _qty_field_for_commodity(key: str) -> str | None:
    mapping = {
        'al_6': 'qty_al_6',
        'al_12': 'qty_al_12',
        'al_18': 'qty_al_18',
        'al_24': 'qty_al_24',
        'artesunate_60': 'qty_artesunate',
        'rdts': 'qty_rdts',
    }
    return mapping.get(key)


def _accumulate_diagnostics(store: dict, method: str, result: str) -> None:
    if method == 'none' or not result:
        if method == 'none':
            store['not_tested'] += 1
        return
    bucket = store.get(method)
    if bucket is None:
        return
    if result in bucket:
        bucket[result] += 1


def _accumulate_al_weight(store: dict, band: str) -> None:
    if band and band in store:
        store[band] += 1


def sync_moh645_from_hms(report: Moh645DailyReport) -> dict:
    """Pull completed malaria lab tests and dispensing for the report date."""
    report_date = report.report_date
    report.entries.filter(source='hms').delete()

    rows_by_key: dict[str, dict] = {}
    sort_order = 0

    lab_results = (
        LabResult.objects.filter(
            status='Completed',
            completed_at__date=report_date,
        )
        .filter(MALARIA_LAB_FILTER)
        .select_related('patient', 'service', 'invoice', 'invoice__visit')
    )

    for lab_result in lab_results:
        visit = _visit_for_lab_result(lab_result)
        key = f'visit:{visit.pk}' if visit else f'lab:{lab_result.pk}'
        method = _parse_test_method(lab_result.service.name, lab_result.results)
        result = _parse_test_result(lab_result.results, lab_result.interpretation)
        row = rows_by_key.setdefault(
            key,
            {
                'visit': visit,
                'patient_name': _patient_display_name(lab_result.patient),
                'visit_type': _visit_type_code(visit),
                'test_method': method,
                'test_result': result,
                'al_weight_band': '',
                'qty_rdts': Decimal('0'),
                'qty_al_6': Decimal('0'),
                'qty_al_12': Decimal('0'),
                'qty_al_18': Decimal('0'),
                'qty_al_24': Decimal('0'),
                'qty_artesunate': Decimal('0'),
            },
        )
        if method == 'mrdt' and result:
            row['qty_rdts'] += Decimal('1')

    dispensed = (
        DispensedItem.objects.filter(dispensed_at__date=report_date)
        .select_related('item', 'patient', 'visit')
    )
    for disp in dispensed:
        commodity_key = _commodity_key_for_dispensed_item(disp.item)
        if not commodity_key:
            continue
        visit = disp.visit
        key = f'visit:{visit.pk}' if visit else f'disp:{disp.pk}'
        row = rows_by_key.setdefault(
            key,
            {
                'visit': visit,
                'patient_name': _patient_display_name(disp.patient),
                'visit_type': _visit_type_code(visit),
                'test_method': 'none',
                'test_result': '',
                'al_weight_band': '',
                'qty_rdts': Decimal('0'),
                'qty_al_6': Decimal('0'),
                'qty_al_12': Decimal('0'),
                'qty_al_18': Decimal('0'),
                'qty_al_24': Decimal('0'),
                'qty_artesunate': Decimal('0'),
            },
        )
        field = _qty_field_for_commodity(commodity_key)
        if field:
            row[field] += Decimal(str(disp.quantity))
            if commodity_key.startswith('al_') and not row['al_weight_band']:
                row['al_weight_band'] = _infer_al_band_from_visit(visit, disp.patient)

    created = 0
    for row in rows_by_key.values():
        Moh645DailyEntry.objects.create(
            report=report,
            visit=row['visit'],
            patient_name=row['patient_name'],
            visit_type=row['visit_type'],
            test_method=row['test_method'],
            test_result=row['test_result'],
            al_weight_band=row['al_weight_band'],
            qty_rdts=row['qty_rdts'],
            qty_al_6=row['qty_al_6'],
            qty_al_12=row['qty_al_12'],
            qty_al_18=row['qty_al_18'],
            qty_al_24=row['qty_al_24'],
            qty_artesunate=row['qty_artesunate'],
            source='hms',
            sort_order=sort_order,
        )
        sort_order += 1
        created += 1

    return {'entries_created': created, 'lab_tests': lab_results.count()}


def _infer_al_band_from_visit(visit, patient) -> str:
    age_years = getattr(patient, 'age', None)
    if age_years is None and hasattr(patient, 'date_of_birth') and patient.date_of_birth:
        today = timezone.localdate()
        dob = patient.date_of_birth
        age_years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age_years is not None:
        if age_years < 3:
            return 'lt15'
        if age_years < 8:
            return 'bw15_25'
        if age_years < 12:
            return 'bw25_35'
        return 'gte35'
    return ''


def _month_date_range(year: int, month: int):
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1)
    end = datetime(year, month, last_day, 23, 59, 59)
    if timezone.is_naive(start):
        start = timezone.make_aware(start)
        end = timezone.make_aware(end)
    return start, end


def sync_moh743_from_hms(report: Moh743MonthlyReport) -> dict:
    """Roll up daily MOH 645 entries and dispensing into the monthly MOH 743 report."""
    start, end = _month_date_range(report.year, report.month)

    diagnostics = _empty_diagnostics()
    al_weight = _empty_al_weight()
    dispensed_totals: dict[str, Decimal] = defaultdict(lambda: Decimal('0'))

    daily_reports = Moh645DailyReport.objects.filter(
        report_date__year=report.year,
        report_date__month=report.month,
    )
    entries = Moh645DailyEntry.objects.filter(report__in=daily_reports)
    for entry in entries:
        _accumulate_diagnostics(diagnostics, entry.test_method, entry.test_result)
        if entry.al_weight_band:
            _accumulate_al_weight(al_weight, entry.al_weight_band)
        dispensed_totals['al_6'] += entry.qty_al_6
        dispensed_totals['al_12'] += entry.qty_al_12
        dispensed_totals['al_18'] += entry.qty_al_18
        dispensed_totals['al_24'] += entry.qty_al_24
        dispensed_totals['artesunate_60'] += entry.qty_artesunate
        dispensed_totals['rdts'] += entry.qty_rdts

    for disp in DispensedItem.objects.filter(dispensed_at__range=(start, end)).select_related('item'):
        key = _commodity_key_for_dispensed_item(disp.item)
        if key:
            dispensed_totals[key] += Decimal(str(disp.quantity))

    report.diagnostics_data = diagnostics
    report.al_weight_data = al_weight
    report.save(update_fields=['diagnostics_data', 'al_weight_data', 'updated_at'])

    lines_updated = 0
    for line in report.lines.select_related('line_definition'):
        key = line.line_definition.row_key
        if key in dispensed_totals:
            line.col_c = dispensed_totals[key]
            line.save(update_fields=['col_c'])
            lines_updated += 1

    return {
        'lines_updated': lines_updated,
        'daily_entries': entries.count(),
        'diagnostics': diagnostics,
    }


def ensure_moh743_commodity_definitions():
    from .moh743_lines import MOH743_COMMODITIES
    for row in MOH743_COMMODITIES:
        Moh743CommodityDefinition.objects.update_or_create(
            row_key=row['row_key'],
            defaults={
                'commodity_name': row['commodity_name'],
                'basic_unit': row['basic_unit'],
                'sort_order': row['sort_order'],
                'is_active': True,
            },
        )


def ensure_moh743_report_lines(report: Moh743MonthlyReport):
    ensure_moh743_commodity_definitions()
    for definition in Moh743CommodityDefinition.objects.filter(is_active=True):
        Moh743CommodityLine.objects.get_or_create(
            report=report,
            line_definition=definition,
        )
