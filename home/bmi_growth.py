"""
BMI calculation and pediatric growth-chart helpers (CPOE).

Adult BMI uses WHO cut-offs. Pediatric growth uses simplified WHO
weight-for-age reference points (median / −2SD / +2SD) for charting.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def calc_bmi(weight_kg, height_cm) -> float | None:
    """Return BMI (kg/m²) or None if inputs incomplete/invalid."""
    try:
        w = float(weight_kg)
        h = float(height_cm)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    h_m = h / 100.0
    if h_m <= 0:
        return None
    return round(w / (h_m * h_m), 1)


def bmi_category(bmi: float | None, *, age_years: int | None = None) -> str:
    """Adult WHO BMI category; for under-18 returns 'pediatric' if BMI present."""
    if bmi is None:
        return ''
    if age_years is not None and age_years < 18:
        # Pediatric BMI-for-age needs LMS tables; flag for chart review
        if bmi < 14:
            return 'low (review growth chart)'
        if bmi >= 27:
            return 'high (review growth chart)'
        return 'see growth chart'
    if bmi < 18.5:
        return 'Underweight'
    if bmi < 25:
        return 'Normal'
    if bmi < 30:
        return 'Overweight'
    return 'Obese'


# Simplified WHO weight-for-age (kg): age_months -> (neg2sd, median, pos2sd)
# Boys (0–60 months). Source: WHO Child Growth Standards (rounded).
_WFA_BOYS = {
    0: (2.5, 3.3, 4.4),
    1: (3.4, 4.5, 5.8),
    2: (4.3, 5.6, 7.1),
    3: (5.0, 6.4, 8.0),
    4: (5.6, 7.0, 8.7),
    5: (6.0, 7.5, 9.3),
    6: (6.4, 7.9, 9.8),
    9: (7.1, 8.9, 10.9),
    12: (7.7, 9.6, 12.0),
    18: (8.8, 10.9, 13.7),
    24: (9.7, 12.2, 15.3),
    36: (11.3, 14.3, 18.3),
    48: (12.7, 16.3, 21.2),
    60: (14.1, 18.3, 24.2),
}

_WFA_GIRLS = {
    0: (2.4, 3.2, 4.2),
    1: (3.2, 4.2, 5.5),
    2: (3.9, 5.1, 6.6),
    3: (4.5, 5.8, 7.5),
    4: (5.0, 6.4, 8.2),
    5: (5.4, 6.9, 8.8),
    6: (5.7, 7.3, 9.3),
    9: (6.5, 8.2, 10.5),
    12: (7.0, 8.9, 11.5),
    18: (8.1, 10.2, 13.2),
    24: (9.0, 11.5, 14.8),
    36: (10.8, 13.9, 18.1),
    48: (12.3, 15.9, 21.5),
    60: (13.7, 18.2, 24.9),
}


def _interp_wfa(table: dict[int, tuple], age_months: float) -> tuple[float, float, float] | None:
    if age_months < 0 or age_months > 60:
        return None
    keys = sorted(table.keys())
    if age_months in table:
        return table[int(age_months)]
    lo = max(k for k in keys if k <= age_months)
    hi = min(k for k in keys if k >= age_months)
    if lo == hi:
        return table[lo]
    t = (age_months - lo) / (hi - lo)
    a, b = table[lo], table[hi]
    return (
        round(a[0] + t * (b[0] - a[0]), 2),
        round(a[1] + t * (b[1] - a[1]), 2),
        round(a[2] + t * (b[2] - a[2]), 2),
    )


def weight_for_age_refs(age_months: float, *, sex: str = 'male') -> dict[str, float] | None:
    """Return WHO WFA −2SD / median / +2SD for age in months (0–60)."""
    table = _WFA_GIRLS if str(sex).lower().startswith('f') else _WFA_BOYS
    pts = _interp_wfa(table, age_months)
    if not pts:
        return None
    return {'neg2sd': pts[0], 'median': pts[1], 'pos2sd': pts[2]}


def classify_weight_for_age(weight_kg, age_months: float, *, sex: str = 'male') -> str:
    refs = weight_for_age_refs(age_months, sex=sex)
    if not refs:
        return ''
    try:
        w = float(weight_kg)
    except (TypeError, ValueError):
        return ''
    if w < refs['neg2sd']:
        return 'Below −2SD (underweight)'
    if w > refs['pos2sd']:
        return 'Above +2SD (possible overweight)'
    return 'Within −2SD to +2SD'


def age_in_months(dob, on_date=None) -> float | None:
    from django.utils import timezone
    if not dob:
        return None
    on_date = on_date or timezone.localdate()
    days = (on_date - dob).days
    if days < 0:
        return None
    return round(days / 30.4375, 1)


def build_growth_series(patient, records) -> dict[str, Any]:
    """
    Build chart-ready series from CWC / triage anthropometry records.
    Each record: measured_date, weight_kg, height_cm optional.
    """
    sex = getattr(patient, 'gender', '') or 'male'
    points = []
    for r in records:
        measured = getattr(r, 'measured_date', None) or getattr(r, 'entry_date', None)
        if hasattr(measured, 'date'):
            measured = measured.date()
        weight = getattr(r, 'weight_kg', None) or getattr(r, 'weight', None)
        height = getattr(r, 'height_cm', None) or getattr(r, 'height', None)
        if weight is None or measured is None:
            continue
        months = age_in_months(patient.date_of_birth, measured)
        bmi = calc_bmi(weight, height) if height else None
        wfa = classify_weight_for_age(weight, months, sex=sex) if months is not None else ''
        refs = weight_for_age_refs(months, sex=sex) if months is not None else None
        points.append({
            'date': measured.isoformat(),
            'age_months': months,
            'weight_kg': float(weight),
            'height_cm': float(height) if height else None,
            'bmi': bmi,
            'bmi_category': bmi_category(bmi, age_years=patient.age),
            'wfa_status': wfa,
            'wfa_median': refs['median'] if refs else None,
            'wfa_neg2sd': refs['neg2sd'] if refs else None,
            'wfa_pos2sd': refs['pos2sd'] if refs else None,
        })
    points.sort(key=lambda p: p['date'])
    return {
        'patient_id': patient.pk,
        'sex': sex,
        'points': points,
        'has_pediatric_refs': any(p['age_months'] is not None and p['age_months'] <= 60 for p in points),
    }


def decimal_bmi(weight, height) -> Decimal | None:
    bmi = calc_bmi(weight, height)
    if bmi is None:
        return None
    return Decimal(str(bmi))
