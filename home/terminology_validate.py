"""Cross-check local terminology selections against DHA / SHA Terminology Service."""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils import timezone

from .models import TerminologyConcept
from .terminology_local import (
    normalize_title,
    resolve_terminology_entry,
    upsert_terminology_results,
)


def _pick_dha_match(results: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
    upper = (code or '').strip().upper()
    exact = [
        r for r in results
        if str(r.get('code') or '').strip().upper() == upper
    ]
    if exact:
        return exact[0]
    for r in results:
        if str(r.get('id') or '').strip().upper() == upper:
            return r
    return None


def cross_check_terminology_with_dha(
    system: str,
    code: str,
    *,
    local_title: str | None = None,
) -> dict[str, Any]:
    """
    Local DB first, then confirm via SHA/DHA that the concept is still supported
    and the display title has not changed.
    """
    system = (system or '').strip().lower()
    if system not in (TerminologyConcept.SYSTEM_LOINC, TerminologyConcept.SYSTEM_ICHI):
        raise ValueError('system must be loinc or ichi.')

    clean_code = (code or '').strip()
    if not clean_code:
        raise ValueError('code is required.')

    label = system.upper()
    local = resolve_terminology_entry(system, clean_code)
    local_display = (
        (local.title if local else None) or (local_title or '')
    ).strip()

    payload: dict[str, Any] = {
        'success': True,
        'system': system,
        'code': clean_code,
        'local': {
            'found': bool(local),
            'code': local.code if local else clean_code,
            'title': local_display or None,
            'owner': local.owner if local else None,
            'source': local.source if local else None,
            'last_verified_at': local.last_verified_at.isoformat() if local and local.last_verified_at else None,
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
        'display': f'{clean_code} — {local_display}' if local_display else clean_code,
        'title': local_display or None,
    }

    if not local:
        payload['success'] = False
        payload['status'] = 'not_in_local_db'
        payload['message'] = (
            f'{label} code "{clean_code}" is not in the local terminology cache. '
            'Search again to seed from DHA, or pick another code.'
        )
        return payload

    if not getattr(settings, 'TERMINOLOGY_DHA_VALIDATE_ON_SELECT', True):
        payload['status'] = 'local_ok'
        payload['message'] = f'Validated against local {label} cache (DHA check disabled).'
        return payload

    try:
        from accounts.sha_hie_service import ShaHieClient

        client = ShaHieClient()
        if system == TerminologyConcept.SYSTEM_LOINC:
            dha = client.search_loinc(clean_code, limit=25)
            owner = getattr(settings, 'SHA_HIE_LOINC_OWNER', 'Regenstrief')
            source = getattr(settings, 'SHA_HIE_LOINC_SOURCE', 'LOINC')
        else:
            dha = client.search_ichi(clean_code, limit=25)
            owner = getattr(settings, 'SHA_HIE_ICHI_OWNER', 'WHO')
            source = getattr(settings, 'SHA_HIE_ICHI_SOURCE', 'ICHI')

        results = dha.get('results') or []
        match = _pick_dha_match(results, clean_code)
        payload['dha']['checked'] = True
        payload['dha']['raw_count'] = len(results)

        if not match:
            payload['success'] = False
            payload['status'] = 'not_supported_by_dha'
            payload['dha']['supported'] = False
            payload['message'] = (
                f'{label} code "{clean_code}" was found locally but is not returned '
                'by the DHA terminology service. Choose another code.'
            )
            return payload

        dha_code = str(match.get('code') or clean_code).strip()
        dha_title = (match.get('title') or '').strip()
        payload['dha']['supported'] = True
        payload['dha']['code'] = dha_code
        payload['dha']['title'] = dha_title or None
        payload['dha']['match'] = match

        local_norm = normalize_title(local_display)
        dha_norm = normalize_title(dha_title)
        unchanged = bool(dha_norm) and (
            local_norm == dha_norm
            or local_norm in dha_norm
            or dha_norm in local_norm
        )
        if not dha_norm:
            unchanged = True

        payload['dha']['unchanged'] = unchanged
        if unchanged:
            title = dha_title or local_display
            payload['title'] = title
            payload['display'] = f'{dha_code or clean_code} — {title}' if title else (dha_code or clean_code)
            payload['status'] = 'validated'
            payload['message'] = (
                f'{label} code confirmed with DHA terminology (supported and unchanged).'
            )
            upsert_terminology_results(
                system,
                [{
                    'code': dha_code or clean_code,
                    'title': title,
                    'id': match.get('id'),
                    'uri': match.get('uri') or match.get('system'),
                    'owner': match.get('owner') or owner,
                    'source': match.get('source') or source,
                }],
                owner=owner,
                source=source,
                mark_verified=True,
            )
            return payload

        payload['success'] = False
        payload['status'] = 'title_changed'
        payload['message'] = (
            f'{label} code "{clean_code}" is supported by DHA, but the title differs. '
            f'Local: "{local_display}" · DHA: "{dha_title}". '
            'Accept the DHA title or re-seed the local cache.'
        )
        payload['suggested_display'] = f'{dha_code or clean_code} — {dha_title or local_display}'
        payload['suggested_title'] = dha_title or local_display
        return payload

    except Exception as exc:  # noqa: BLE001
        payload['dha']['checked'] = True
        payload['dha']['error'] = str(exc)
        strict = getattr(settings, 'TERMINOLOGY_DHA_VALIDATE_STRICT', False)
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
                f'Local {label} OK. DHA terminology check unavailable ({exc}). '
                'Allowed for now — re-validate before SHA submission.'
            )
            # Touch local verify timestamp loosely? Skip — not confirmed.
            if local:
                local.save(update_fields=['updated_at'])
        return payload
