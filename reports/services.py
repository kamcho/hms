"""
Build NVIP MOH 710 counts from maternity ImmunizationRecord data.
"""
from calendar import monthrange
from datetime import date

from django.db.models import Q

from maternity.models import ImmunizationRecord


def _patient_age_years(patient, on_date: date) -> float:
    if not patient or not patient.date_of_birth:
        return 0
    dob = patient.date_of_birth
    return (on_date - dob).days / 365.25


def _age_bucket_years(age_years: float, row_suffix: str) -> bool:
    """Match row_key suffix to patient age."""
    if row_suffix in ('under_1', 'within_2w'):
        return age_years < 1
    if row_suffix == 'above_1':
        return age_years >= 1
    if row_suffix == 'above_2w':
        return age_years >= 0.038  # ~2 weeks as fraction of year — use days for birth OPV
    if row_suffix in ('18_24m', '2_3y'):
        return 1.5 <= age_years < 3
    if row_suffix in ('above_2y', 'above_3y'):
        return age_years >= 2 if '2y' in row_suffix else age_years >= 3
    if row_suffix == '6_11':
        return 0.5 <= age_years < 1
    if row_suffix in ('12_59',):
        return 1 <= age_years < 5
    return True


def _age_bucket_days(age_days: int, row_key: str) -> bool:
    if row_key == 'opv_birth_within_2w':
        return age_days <= 14
    if row_key == 'opv_birth_above_2w':
        return age_days > 14
    return True


def _map_record_to_row_key(record: ImmunizationRecord) -> str | None:
    """Map an immunization record to a MOH 710 row_key if possible."""
    abbr = (record.vaccine.abbreviation or '').upper()
    dose = record.dose_number or 1
    patient = record.patient
    if not patient and record.newborn:
        patient = getattr(record.newborn, 'patient_profile', None)
    if not patient:
        return None

    on_date = record.date_administered
    age_years = _patient_age_years(patient, on_date)
    age_days = (on_date - patient.date_of_birth).days if patient.date_of_birth else 0
    under_1 = age_years < 1
    above_1 = age_years >= 1

    mapping = {
        'BCG': 'bcg_under_1' if under_1 else 'bcg_above_1',
        'OPV': None,
        'IPV': f'ipv{dose}_under_1' if under_1 else f'ipv{dose}_above_1',
        'DPT-HEPB-HIB': f'pent{dose}_under_1' if under_1 else f'pent{dose}_above_1',
        'DPT-HepB-Hib': f'pent{dose}_under_1' if under_1 else f'pent{dose}_above_1',
        'ROTA': f'rota{dose}_under_1' if under_1 and dose <= 3 else None,
        'PCV': f'pcv{dose}_under_1' if under_1 else f'pcv{dose}_above_1',
        'MR': f'mr{dose}_under_1' if dose == 1 and under_1 else (
            f'mr{dose}_above_1' if dose == 1 else (
                'mr2_18_24m' if age_years < 2 else 'mr2_above_2y'
            )
        ),
        'YF': 'yf_under_1' if under_1 else 'yf_above_1',
        'Vit A 100k': 'vit_a_6_11' if 0.5 <= age_years < 1 else None,
        'Vit A 200k': 'vit_a_12_59' if 1 <= age_years < 5 else None,
        'TT': f'td_pw_dose{dose}' if dose <= 5 else 'tt_trauma',
        'TCV': 'tcv_under_1' if under_1 else 'tcv_above_1',
        'HPV': f'hpv_dose{dose}' if dose <= 2 else None,
    }

    if abbr == 'OPV':
        if dose == 0 or 'birth' in (record.vaccine.name or '').lower():
            return 'opv_birth_within_2w' if age_days <= 14 else 'opv_birth_above_2w'
        if dose <= 3:
            return f'opv{dose}_under_1' if under_1 else f'opv{dose}_above_1'
    return mapping.get(abbr)


def build_counts_from_immunization(month: int, year: int) -> dict[str, dict[int, int]]:
    """
    Returns {row_key: {day: count}} for all immunizations in the given month.
    """
    last_day = monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, last_day)

    records = ImmunizationRecord.objects.filter(
        date_administered__gte=start,
        date_administered__lte=end,
    ).filter(
        Q(patient__isnull=False) | Q(newborn__isnull=False)
    ).select_related('vaccine', 'patient', 'newborn')

    counts: dict[str, dict[int, int]] = {}
    for rec in records:
        row_key = _map_record_to_row_key(rec)
        if not row_key:
            continue
        day = rec.date_administered.day
        counts.setdefault(row_key, {})
        counts[row_key][day] = counts[row_key].get(day, 0) + 1

    return counts


def apply_immunization_counts_to_report(report) -> int:
    """Populate report lines from ImmunizationRecord; returns rows updated."""
    from .models import NvipLineDefinition, NvipReportLine

    counts = build_counts_from_immunization(report.month, report.year)
    updated = 0
    for line_def in NvipLineDefinition.objects.filter(is_active=True):
        line, _ = NvipReportLine.objects.get_or_create(
            report=report,
            line_definition=line_def,
            defaults={'daily_data': {}},
        )
        day_map = counts.get(line_def.row_key, {})
        if not day_map:
            continue
        data = {}
        total = 0
        for day, cnt in day_map.items():
            data[str(day)] = {'d': cnt, 's': cnt, 'o': 0}
            total += cnt
        line.daily_data = data
        line.total_static = total
        line.total_outreach = 0
        line.save()
        updated += 1
    return updated
