"""Local TerminologyConcept search + DHA seed cache for LOINC / ICHI."""
from __future__ import annotations

import re
from typing import Any

from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from .models import TerminologyConcept

_TITLE_NOISE_RE = re.compile(r'^[\s\-–—]+')


def normalize_title(title: str | None) -> str:
    value = _TITLE_NOISE_RE.sub('', (title or '').strip().lower())
    return re.sub(r'\s+', ' ', value)


def local_terminology_count(system: str) -> int:
    return TerminologyConcept.objects.filter(
        system=system,
        is_active=True,
    ).count()


def resolve_terminology_entry(system: str, code: str) -> TerminologyConcept | None:
    clean = (code or '').strip()
    if not clean:
        return None
    return (
        TerminologyConcept.objects.filter(system=system, code__iexact=clean)
        .order_by('-is_active', '-last_verified_at')
        .first()
    )


def search_terminology_local(
    system: str,
    query: str,
    *,
    limit: int = 25,
) -> dict[str, Any]:
    clean = (query or '').strip()
    if not clean:
        raise ValueError('query is required.')
    system = (system or '').strip().lower()
    if system not in (TerminologyConcept.SYSTEM_LOINC, TerminologyConcept.SYSTEM_ICHI):
        raise ValueError('system must be loinc or ichi.')

    upper = clean.upper()
    qs = TerminologyConcept.objects.filter(system=system, is_active=True)
    filters = (
        Q(code__iexact=clean)
        | Q(code__iexact=upper)
        | Q(code__istartswith=clean)
        | Q(code__istartswith=upper)
        | Q(title__icontains=clean)
        | Q(title_normalized__icontains=normalize_title(clean))
    )
    ranked = (
        qs.filter(filters)
        .annotate(
            rank=Case(
                When(code__iexact=clean, then=Value(0)),
                When(code__iexact=upper, then=Value(0)),
                When(code__istartswith=upper, then=Value(1)),
                When(title_normalized__istartswith=normalize_title(clean), then=Value(2)),
                When(title__icontains=clean, then=Value(3)),
                default=Value(4),
                output_field=IntegerField(),
            )
        )
        .order_by('rank', 'code', 'title')[:limit]
    )
    results = [row.to_search_result() for row in ranked]
    return {
        'query': clean,
        'system': system,
        'results': results,
        'source': 'local',
        'count': len(results),
    }


def upsert_terminology_results(
    system: str,
    results: list[dict[str, Any]],
    *,
    owner: str = '',
    source: str = '',
    mark_verified: bool = False,
) -> int:
    """Persist DHA (or other) concept payloads into the local cache. Returns upsert count."""
    system = (system or '').strip().lower()
    if system not in (TerminologyConcept.SYSTEM_LOINC, TerminologyConcept.SYSTEM_ICHI):
        return 0

    now = timezone.now() if mark_verified else None
    saved = 0
    for item in results or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get('code') or item.get('id') or '').strip()
        title = str(item.get('title') or item.get('display') or '').strip()
        if not code or not title:
            continue
        defaults = {
            'title': title[:512],
            'title_normalized': normalize_title(title)[:512],
            'owner': (item.get('owner') or owner or '')[:64],
            'source': (item.get('source') or source or '')[:64],
            'uri': str(item.get('uri') or item.get('system') or '')[:512],
            'concept_id': str(item.get('id') or '')[:128],
            'is_active': True,
        }
        if mark_verified and now is not None:
            defaults['last_verified_at'] = now
            defaults['last_dha_title'] = title[:512]
        _, created = TerminologyConcept.objects.update_or_create(
            system=system,
            code=code[:64],
            defaults=defaults,
        )
        if not created:
            # Keep code unique; still count as upserted for seed feedback
            pass
        saved += 1
    return saved


def seed_from_dha(system: str, query: str, *, limit: int = 25) -> dict[str, Any]:
    """
    Fetch concepts from DHA Terminology Service and cache locally.
    Used when local search returns nothing (or local table is empty).
    """
    from accounts.sha_hie_service import ShaHieClient
    from django.conf import settings

    client = ShaHieClient()
    if system == TerminologyConcept.SYSTEM_LOINC:
        payload = client.search_loinc(query, limit=limit)
        owner = getattr(settings, 'SHA_HIE_LOINC_OWNER', 'Regenstrief')
        source = getattr(settings, 'SHA_HIE_LOINC_SOURCE', 'LOINC')
    elif system == TerminologyConcept.SYSTEM_ICHI:
        payload = client.search_ichi(query, limit=limit)
        owner = getattr(settings, 'SHA_HIE_ICHI_OWNER', 'WHO')
        source = getattr(settings, 'SHA_HIE_ICHI_SOURCE', 'ICHI')
    else:
        raise ValueError('system must be loinc or ichi.')

    results = payload.get('results') or []
    upsert_terminology_results(
        system,
        results,
        owner=owner,
        source=source,
        mark_verified=False,
    )
    # Re-read from DB so callers always get local-shaped rows
    local = search_terminology_local(system, query, limit=limit)
    local['source'] = 'local_after_dha_seed'
    local['dha_path'] = payload.get('path')
    local['seeded'] = len(results)
    return local
