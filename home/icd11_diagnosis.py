from __future__ import annotations

import re
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError

from .models import Icd11Code

DISPLAY_RE = re.compile(r'^([A-Z0-9][A-Z0-9.]*) — (.+)$', re.UNICODE)
_TITLE_NOISE_RE = re.compile(r'^[\s\-–—]+')


def format_diagnosis_display(code: str, title: str) -> str:
    return f'{code.strip().upper()} — {title.strip()}'


def parse_diagnosis_display(text: str) -> tuple[str, str] | None:
    match = DISPLAY_RE.match((text or '').strip())
    if not match:
        return None
    return match.group(1).upper(), match.group(2).strip()


def normalize_title(title: str | None) -> str:
    value = _TITLE_NOISE_RE.sub('', (title or '').strip().lower())
    value = re.sub(r'\s+', ' ', value)
    return value


def resolve_icd11_entry(
    code: str,
    *,
    release: str | None = None,
    linearization: str | None = None,
) -> Icd11Code | None:
    clean_code = (code or '').strip().upper()
    if not clean_code:
        return None
    return (
        Icd11Code.objects.filter(
            release=release or settings.ICD11_RELEASE,
            linearization=linearization or settings.ICD11_LINEARIZATION,
            code__iexact=clean_code,
        )
        .order_by('-is_primary_tabulation', 'is_leaf')
        .first()
    )


def _pick_dha_match(
    results: list[dict[str, Any]],
    code: str,
) -> dict[str, Any] | None:
    upper = code.strip().upper()
    exact = [
        r for r in results
        if str(r.get('code') or '').strip().upper() == upper
    ]
    if exact:
        return exact[0]
    # Some TS payloads put the code in id
    for r in results:
        if str(r.get('id') or '').strip().upper() == upper:
            return r
    return None


def cross_check_icd11_with_dha(
    code: str,
    *,
    local_title: str | None = None,
) -> dict[str, Any]:
    """
    Cross-reference a local ICD-11 selection against DHA Terminology Service.

    Returns a structured validation payload for the prescription picker / API.
    """
    clean_code = (code or '').strip().upper()
    if not clean_code:
        raise ValueError('code is required.')

    local = resolve_icd11_entry(clean_code)
    local_display_title = (
        (local.title_plain or local.title) if local else (local_title or '')
    ).strip()

    payload: dict[str, Any] = {
        'success': True,
        'code': clean_code,
        'local': {
            'found': bool(local),
            'code': local.code if local else clean_code,
            'title': local_display_title or None,
            'entity_id': local.entity_id if local else None,
            'release': (local.release if local else settings.ICD11_RELEASE),
            'is_leaf': local.is_leaf if local else None,
        },
        'dha': {
            'checked': False,
            'supported': False,
            'unchanged': False,
            'code': None,
            'title': None,
            'match': None,
            'error': None,
        },
        'status': 'local_only',
        'message': '',
        'display': format_diagnosis_display(clean_code, local_display_title)
        if local_display_title else clean_code,
    }

    if not local:
        payload['success'] = False
        payload['status'] = 'not_in_local_db'
        payload['message'] = (
            f'ICD-11 code "{clean_code}" is not in the local repository. '
            'Run sync_icd11 or choose another code.'
        )
        return payload

    if not getattr(settings, 'ICD11_DHA_VALIDATE_ON_SELECT', True):
        payload['status'] = 'local_ok'
        payload['message'] = 'Validated against local ICD-11 repository (DHA check disabled).'
        return payload

    try:
        from accounts.sha_hie_service import ShaHieClient

        dha = ShaHieClient().search_icd11(clean_code, limit=25)
        results = dha.get('results') or []
        match = _pick_dha_match(results, clean_code)
        payload['dha']['checked'] = True
        payload['dha']['raw_count'] = len(results)

        if not match:
            payload['success'] = False
            payload['status'] = 'not_supported_by_dha'
            payload['dha']['supported'] = False
            payload['message'] = (
                f'ICD-11 code "{clean_code}" was found locally but is not returned '
                'by the DHA terminology service. Choose another code or refresh terminology.'
            )
            return payload

        dha_code = str(match.get('code') or clean_code).strip().upper()
        dha_title = (match.get('title') or '').strip()
        payload['dha']['supported'] = True
        payload['dha']['code'] = dha_code
        payload['dha']['title'] = dha_title or None
        payload['dha']['match'] = match

        local_norm = normalize_title(local_display_title)
        dha_norm = normalize_title(dha_title)
        unchanged = bool(dha_norm) and (local_norm == dha_norm or local_norm in dha_norm or dha_norm in local_norm)
        # If DHA returns code-only without title, treat as supported but title unchecked
        if not dha_norm:
            unchanged = True

        payload['dha']['unchanged'] = unchanged
        if unchanged:
            # Prefer DHA title when present (canonical for SHA)
            title = dha_title or local_display_title
            payload['display'] = format_diagnosis_display(dha_code or clean_code, title)
            payload['status'] = 'validated'
            payload['message'] = 'ICD-11 code confirmed with DHA terminology (supported and unchanged).'
            return payload

        payload['success'] = False
        payload['status'] = 'title_changed'
        payload['message'] = (
            f'ICD-11 code "{clean_code}" is supported by DHA, but the title differs. '
            f'Local: "{local_display_title}" · DHA: "{dha_title}". '
            'Re-sync local codes or use the DHA title.'
        )
        payload['suggested_display'] = format_diagnosis_display(
            dha_code or clean_code,
            dha_title or local_display_title,
        )
        return payload

    except Exception as exc:  # noqa: BLE001 — surface upstream issues to UI
        payload['dha']['checked'] = True
        payload['dha']['error'] = str(exc)
        strict = getattr(settings, 'ICD11_DHA_VALIDATE_STRICT', False)
        if strict:
            payload['success'] = False
            payload['status'] = 'dha_unavailable'
            payload['message'] = (
                f'DHA terminology check failed: {exc}. '
                'Selection blocked (strict mode). Retry later.'
            )
        else:
            payload['status'] = 'local_ok_dha_unavailable'
            payload['message'] = (
                f'Local ICD-11 OK. DHA terminology check unavailable ({exc}). '
                'Allowed for now — re-validate before SHA claim submission.'
            )
        return payload


def validate_and_resolve_diagnosis(
    text: str,
    *,
    required: bool = True,
    release: str | None = None,
    linearization: str | None = None,
    cross_check_dha: bool | None = None,
) -> tuple[str, str, Icd11Code | None]:
    raw = (text or '').strip()
    if not raw:
        if required:
            raise ValidationError(
                'ICD-11 diagnosis is required. Search and select a code from the list.'
            )
        return '', '', None

    parsed = parse_diagnosis_display(raw)
    if not parsed:
        raise ValidationError(
            'Select a valid ICD-11 code from search results (format: CODE — Title).'
        )

    code, _title = parsed
    entry = resolve_icd11_entry(code, release=release, linearization=linearization)
    if not entry:
        raise ValidationError(
            f'ICD-11 code "{code}" is not valid for release '
            f'{release or settings.ICD11_RELEASE}. Run sync_icd11 or choose another code.'
        )

    title = entry.title_plain or entry.title
    display = format_diagnosis_display(code, title)

    do_check = (
        settings.ICD11_DHA_VALIDATE_ON_SELECT
        if cross_check_dha is None
        else cross_check_dha
    )
    if do_check:
        check = cross_check_icd11_with_dha(code, local_title=title)
        if not check.get('success'):
            # Allow soft-fail statuses only when not strict and DHA was down
            if check.get('status') == 'local_ok_dha_unavailable':
                return code, display, entry
            if check.get('status') == 'title_changed' and check.get('suggested_display'):
                # Auto-adopt DHA title so claim coding stays current
                suggested = check['suggested_display']
                return code, suggested, entry
            raise ValidationError(check.get('message') or 'ICD-11 DHA validation failed.')
        display = check.get('display') or display

    return code, display, entry


def apply_icd11_diagnosis(
    instance,
    *,
    text: str,
    text_attr: str,
    code_attr: str = 'icd11_code',
    entry_attr: str = 'icd11_entry',
    required: bool = True,
) -> None:
    code, display, entry = validate_and_resolve_diagnosis(text, required=required)
    setattr(instance, text_attr, display)
    setattr(instance, code_attr, code)
    setattr(instance, entry_attr, entry)
