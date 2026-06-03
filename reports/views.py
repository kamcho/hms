import calendar
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms import Moh705bReportHeaderForm, Moh717ReportHeaderForm, NvipReportHeaderForm
from .models import (
    Moh705bColumnDefinition,
    Moh705bLineDefinition,
    Moh705bMonthlyReport,
    Moh705bReportLine,
    Moh717LineDefinition,
    Moh717MonthlyReport,
    Moh717ReportLine,
    NvipLineDefinition,
    NvipMonthlyReport,
    NvipReportLine,
)
from .moh717_lines import MOH717_FORM_NOTE
from .services import apply_immunization_counts_to_report


def _can_access_reports(user):
    return user.is_authenticated and (
        user.is_superuser
        or getattr(user, 'role', None) in ('Admin', 'Nurse', 'Doctor', 'Accountant', 'SHA Manager', 'SHA')
    )


@login_required
def reports_hub(request):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')
    return render(request, 'reports/hub.html', {
        'title': 'Reports',
    })


@login_required
def nvip_report_list(request):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')

    year = request.GET.get('year')
    if year:
        try:
            year = int(year)
        except ValueError:
            year = None
    if not year:
        year = timezone.localdate().year

    reports = NvipMonthlyReport.objects.filter(year=year).order_by('-month')
    return render(request, 'reports/nvip_list.html', {
        'reports': reports,
        'year': year,
        'years': range(timezone.localdate().year, timezone.localdate().year - 5, -1),
        'title': 'NVIP Reports (MOH 710)',
    })


@login_required
def nvip_report_create(request):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')

    if request.method == 'POST':
        form = NvipReportHeaderForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.created_by = request.user
            report.save()
            _ensure_report_lines(report)
            messages.success(request, 'NVIP report created. Enter daily tallies below.')
            return redirect('reports:nvip_edit', pk=report.pk)
    else:
        today = timezone.localdate()
        form = NvipReportHeaderForm(initial={
            'month': today.month,
            'year': today.year,
            'facility_name': 'Facility Name',
        })

    return render(request, 'reports/nvip_create.html', {
        'form': form,
        'title': 'New NVIP Report (MOH 710)',
    })


def _ensure_report_lines(report):
    for line_def in NvipLineDefinition.objects.filter(is_active=True):
        NvipReportLine.objects.get_or_create(
            report=report,
            line_definition=line_def,
            defaults={'daily_data': {}},
        )


@login_required
def nvip_report_edit(request, pk):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')

    report = get_object_or_404(NvipMonthlyReport, pk=pk)
    _ensure_report_lines(report)

    header_form = NvipReportHeaderForm(instance=report)
    lines = report.lines.select_related('line_definition').order_by('line_definition__sort_order')
    days_in_month = calendar.monthrange(report.year, report.month)[1]
    day_range = range(1, days_in_month + 1)

    grid = []
    for line in lines:
        row = {
            'line': line,
            'def': line.line_definition,
            'days': [line.day_count(d) for d in day_range],
            'grand': line.grand_total,
        }
        grid.append(row)

    return render(request, 'reports/nvip_edit.html', {
        'report': report,
        'header_form': header_form,
        'grid': grid,
        'day_range': day_range,
        'days_in_month': days_in_month,
        'title': f'NVIP MOH 710 — {report.month_name} {report.year}',
    })


@login_required
@require_POST
def nvip_report_save(request, pk):
    if not _can_access_reports(request.user):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    report = get_object_or_404(NvipMonthlyReport, pk=pk)
    if report.status == 'submitted':
        return JsonResponse({'success': False, 'error': 'Report is submitted and locked.'})

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'})

    lines_data = payload.get('lines', {})
    for line_id, cells in lines_data.items():
        try:
            line = NvipReportLine.objects.get(pk=int(line_id), report=report)
        except (ValueError, NvipReportLine.DoesNotExist):
            continue
        daily = {}
        for day_str, val in (cells.get('daily') or {}).items():
            try:
                day = int(day_str)
                if 1 <= day <= 31:
                    daily[str(day)] = {'d': max(0, int(val or 0))}
            except (TypeError, ValueError):
                pass
        line.daily_data = daily
        line.total_static = max(0, int(cells.get('total_static') or 0))
        line.total_outreach = max(0, int(cells.get('total_outreach') or 0))
        if line.total_static == 0 and daily:
            line.total_static = sum(v.get('d', 0) for v in daily.values())
        line.save()

    if payload.get('submit'):
        report.status = 'submitted'
        report.save()

    return JsonResponse({'success': True, 'status': report.status})


@login_required
@require_POST
def nvip_sync_immunization(request, pk):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')

    report = get_object_or_404(NvipMonthlyReport, pk=pk)
    if report.status == 'submitted':
        messages.error(request, 'Cannot sync a submitted report.')
        return redirect('reports:nvip_edit', pk=pk)

    updated = apply_immunization_counts_to_report(report)
    messages.success(
        request,
        f'Updated {updated} row(s) from immunization records for {report.month_name} {report.year}.',
    )
    return redirect('reports:nvip_edit', pk=pk)


@login_required
def nvip_report_print(request, pk):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')

    report = get_object_or_404(NvipMonthlyReport, pk=pk)
    lines = report.lines.select_related('line_definition').order_by('line_definition__sort_order')
    days_in_month = calendar.monthrange(report.year, report.month)[1]
    day_range = range(1, days_in_month + 1)

    grid = []
    for line in lines:
        grid.append({
            'def': line.line_definition,
            'days': [line.day_count(d) for d in day_range],
            'total_static': line.total_static or line.computed_daily_sum,
            'total_outreach': line.total_outreach,
            'grand': line.grand_total,
        })

    return render(request, 'reports/nvip_print.html', {
        'report': report,
        'grid': grid,
        'day_range': day_range,
        'days_in_month': days_in_month,
    })


def _ensure_moh705b_lines(report):
    for line_def in Moh705bLineDefinition.objects.filter(is_active=True):
        Moh705bReportLine.objects.get_or_create(
            report=report,
            line_definition=line_def,
            defaults={'column_data': {}},
        )


@login_required
def moh705b_report_list(request):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')

    year = request.GET.get('year')
    try:
        year = int(year) if year else timezone.localdate().year
    except ValueError:
        year = timezone.localdate().year

    reports = Moh705bMonthlyReport.objects.filter(year=year).order_by('-month')
    return render(request, 'reports/moh705b_list.html', {
        'reports': reports,
        'year': year,
        'years': range(timezone.localdate().year, timezone.localdate().year - 5, -1),
        'title': 'MOH 705B — Outpatient Over 5',
    })


@login_required
def moh705b_report_create(request):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')

    if request.method == 'POST':
        form = Moh705bReportHeaderForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.created_by = request.user
            report.save()
            _ensure_moh705b_lines(report)
            messages.success(request, 'MOH 705B report created.')
            return redirect('reports:moh705b_edit', pk=report.pk)
    else:
        today = timezone.localdate()
        form = Moh705bReportHeaderForm(initial={
            'month': today.month,
            'year': today.year,
            'facility_name': 'Facility Name',
            'compiled_date': today,
        })

    return render(request, 'reports/moh705b_create.html', {
        'form': form,
        'title': 'New MOH 705B Report',
    })


@login_required
def moh705b_report_edit(request, pk):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')

    report = get_object_or_404(Moh705bMonthlyReport, pk=pk)
    _ensure_moh705b_lines(report)

    columns = list(Moh705bColumnDefinition.objects.filter(is_active=True).order_by('col_number'))
    lines = list(
        report.lines.select_related('line_definition').order_by('line_definition__sort_order')
    )

    grid = []
    for line in lines:
        grid.append({
            'line': line,
            'def': line.line_definition,
            'cols': [line.col_count(c.col_number) for c in columns],
            'total': line.row_total,
        })

    col_totals = []
    for col in columns:
        col_totals.append(sum(line.col_count(col.col_number) for line in lines))

    return render(request, 'reports/moh705b_edit.html', {
        'report': report,
        'columns': columns,
        'grid': grid,
        'col_totals': col_totals,
        'grand_total': sum(col_totals),
        'title': f'MOH 705B — {report.month_name} {report.year}',
    })


@login_required
@require_POST
def moh705b_report_save(request, pk):
    if not _can_access_reports(request.user):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    report = get_object_or_404(Moh705bMonthlyReport, pk=pk)
    if report.status == 'submitted':
        return JsonResponse({'success': False, 'error': 'Report is submitted and locked.'})

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'})

    for line_id, cells in (payload.get('lines') or {}).items():
        try:
            line = Moh705bReportLine.objects.get(pk=int(line_id), report=report)
        except (ValueError, Moh705bReportLine.DoesNotExist):
            continue
        col_data = {}
        for col_str, val in (cells.get('columns') or {}).items():
            try:
                cn = int(col_str)
                if 1 <= cn <= 16:
                    col_data[str(cn)] = max(0, int(val or 0))
            except (TypeError, ValueError):
                pass
        line.column_data = col_data
        line.save()

    if payload.get('compiled_by') is not None:
        report.compiled_by = payload.get('compiled_by', '')[:200]
    if payload.get('compiled_designation') is not None:
        report.compiled_designation = payload.get('compiled_designation', '')[:120]
    if payload.get('compiled_date'):
        report.compiled_date = payload.get('compiled_date') or None

    if payload.get('submit'):
        report.status = 'submitted'
    report.save()

    return JsonResponse({'success': True, 'status': report.status})


@login_required
def moh705b_report_print(request, pk):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')

    report = get_object_or_404(Moh705bMonthlyReport, pk=pk)
    columns = list(Moh705bColumnDefinition.objects.filter(is_active=True).order_by('col_number'))
    lines = report.lines.select_related('line_definition').order_by('line_definition__sort_order')

    grid = []
    for line in lines:
        grid.append({
            'def': line.line_definition,
            'cols': [line.col_count(c.col_number) for c in columns],
            'total': line.row_total,
        })

    col_totals = [sum(line.col_count(c.col_number) for line in lines) for c in columns]

    return render(request, 'reports/moh705b_print.html', {
        'report': report,
        'columns': columns,
        'grid': grid,
        'col_totals': col_totals,
        'grand_total': sum(col_totals),
    })


def _ensure_moh717_lines(report):
    for line_def in Moh717LineDefinition.objects.filter(is_active=True):
        Moh717ReportLine.objects.get_or_create(
            report=report,
            line_definition=line_def,
            defaults={'new_count': 0, 're_att_count': 0},
        )


def _moh717_grid(report):
    lines = list(
        report.lines.select_related('line_definition').order_by('line_definition__sort_order')
    )
    grid = []
    sum_new = sum_re = 0
    for line in lines:
        cat = line.line_definition.category
        entry = {
            'line': line,
            'def': line.line_definition,
            'new': line.new_count,
            're_att': line.re_att_count,
            'total': line.total_count,
        }
        grid.append(entry)
        if cat in ('data', 'total', 'summary'):
            sum_new += line.new_count
            sum_re += line.re_att_count
    return grid, {'new': sum_new, 're_att': sum_re, 'total': sum_new + sum_re}


@login_required
def moh717_report_list(request):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')
    year = request.GET.get('year')
    try:
        year = int(year) if year else timezone.localdate().year
    except ValueError:
        year = timezone.localdate().year
    reports = Moh717MonthlyReport.objects.filter(year=year).order_by('-month')
    return render(request, 'reports/moh717_list.html', {
        'reports': reports,
        'year': year,
        'years': range(timezone.localdate().year, timezone.localdate().year - 5, -1),
        'title': 'MOH 717 — Service Workload',
    })


@login_required
def moh717_report_create(request):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')
    if request.method == 'POST':
        form = Moh717ReportHeaderForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.created_by = request.user
            report.save()
            _ensure_moh717_lines(report)
            messages.success(request, 'MOH 717 report created.')
            return redirect('reports:moh717_edit', pk=report.pk)
    else:
        today = timezone.localdate()
        form = Moh717ReportHeaderForm(initial={
            'month': today.month,
            'year': today.year,
            'facility_name': 'Health Facility',
            'compiled_date': today,
        })
    return render(request, 'reports/moh717_create.html', {
        'form': form,
        'title': 'New MOH 717 Report',
    })


@login_required
def moh717_report_edit(request, pk):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')
    report = get_object_or_404(Moh717MonthlyReport, pk=pk)
    _ensure_moh717_lines(report)
    grid, col_totals = _moh717_grid(report)
    return render(request, 'reports/moh717_edit.html', {
        'report': report,
        'grid': grid,
        'col_totals': col_totals,
        'form_note': MOH717_FORM_NOTE,
        'title': f'MOH 717 — {report.month_name} {report.year}',
    })


@login_required
@require_POST
def moh717_report_save(request, pk):
    if not _can_access_reports(request.user):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
    report = get_object_or_404(Moh717MonthlyReport, pk=pk)
    if report.status == 'submitted':
        return JsonResponse({'success': False, 'error': 'Report is submitted and locked.'})
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'})
    for line_id, cells in (payload.get('lines') or {}).items():
        try:
            line = Moh717ReportLine.objects.get(pk=int(line_id), report=report)
        except (ValueError, Moh717ReportLine.DoesNotExist):
            continue
        if line.line_definition.category == 'section':
            continue
        line.new_count = max(0, int(cells.get('new') or 0))
        line.re_att_count = max(0, int(cells.get('re_att') or 0))
        line.save()
    if payload.get('compiled_by') is not None:
        report.compiled_by = str(payload.get('compiled_by', ''))[:200]
    if payload.get('compiled_designation') is not None:
        report.compiled_designation = str(payload.get('compiled_designation', ''))[:120]
    if payload.get('compiled_date'):
        report.compiled_date = payload.get('compiled_date') or None
    if payload.get('submit'):
        report.status = 'submitted'
    report.save()
    return JsonResponse({'success': True, 'status': report.status})


@login_required
def moh717_report_print(request, pk):
    if not _can_access_reports(request.user):
        return HttpResponseForbidden('Access denied.')
    report = get_object_or_404(Moh717MonthlyReport, pk=pk)
    grid, col_totals = _moh717_grid(report)
    return render(request, 'reports/moh717_print.html', {
        'report': report,
        'grid': grid,
        'col_totals': col_totals,
        'form_note': MOH717_FORM_NOTE,
    })
