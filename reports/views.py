import calendar
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms import NvipReportHeaderForm
from .models import NvipLineDefinition, NvipMonthlyReport, NvipReportLine
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
