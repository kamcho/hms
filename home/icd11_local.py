from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import Any, Iterable
from urllib.request import urlopen

from django.conf import settings
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When

from .models import Icd11Code

_TITLE_PREFIX_RE = re.compile(r'^[\s\-]+')


def plain_title(title: str) -> str:
    return _TITLE_PREFIX_RE.sub('', (title or '').strip())


def entity_id_from_uri(uri: str | None) -> str:
    if not uri:
        return ''
    return uri.rstrip('/').split('/')[-1] or ''


def tabulation_zip_url(
    *,
    release: str | None = None,
    language: str | None = None,
) -> str:
    template = getattr(
        settings,
        'ICD11_TABULATION_URL',
        'https://icdcdn.who.int/static/releasefiles/{release}/SimpleTabulation-ICD-11-MMS-{language}.zip',
    )
    return template.format(
        release=release or settings.ICD11_RELEASE,
        language=language or settings.ICD11_LANGUAGE,
    )


def download_tabulation_bytes(
    *,
    release: str | None = None,
    language: str | None = None,
    url: str | None = None,
) -> bytes:
    fetch_url = url or tabulation_zip_url(release=release, language=language)
    with urlopen(fetch_url, timeout=120) as response:
        return response.read()


def iter_tabulation_rows_from_bytes(data: bytes) -> Iterable[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        txt_name = next(
            (name for name in archive.namelist() if name.endswith('.txt') and 'SimpleTabulation' in name),
            None,
        )
        if not txt_name:
            raise ValueError('Simple Tabulation .txt file not found in ICD-11 archive.')

        with archive.open(txt_name) as raw_file:
            text = io.TextIOWrapper(raw_file, encoding='utf-8-sig', newline='')
            reader = csv.DictReader(text, delimiter='\t')
            for row in reader:
                if not row:
                    continue
                yield {str(key).strip(): (value or '').strip() for key, value in row.items() if key}


def row_to_icd11_code(
    row: dict[str, str],
    *,
    release: str,
    linearization: str,
) -> Icd11Code | None:
    linearization_uri = row.get('Linearization URI') or row.get('Linearization (release) URI') or ''
    if not linearization_uri:
        return None

    title = row.get('Title', '').strip('"')
    if not title:
        return None

    foundation_uri = row.get('Foundation URI', '').strip()
    code = row.get('Code', '').strip()
    block_id = row.get('BlockId', '').strip()
    class_kind = row.get('ClassKind', '').strip().lower()
    depth_raw = row.get('DepthInKind', '').strip()
    chapter_no = row.get('ChapterNo', '').strip()
    is_residual = row.get('IsResidual', '').strip().lower() == 'true'
    is_leaf = (row.get('isLeaf') or row.get('IsLeaf') or '').strip().lower() == 'true'
    is_primary = (row.get('Primary tabulation') or '').strip().lower() == 'true'

    depth_in_kind = int(depth_raw) if depth_raw.isdigit() else None
    entity_id = entity_id_from_uri(foundation_uri) or entity_id_from_uri(linearization_uri)

    return Icd11Code(
        release=release,
        linearization=linearization,
        foundation_uri=foundation_uri,
        linearization_uri=linearization_uri,
        entity_id=entity_id,
        code=code,
        block_id=block_id,
        title=title,
        title_plain=plain_title(title),
        class_kind=class_kind if class_kind in dict(Icd11Code.CLASS_KIND_CHOICES) else '',
        depth_in_kind=depth_in_kind,
        is_residual=is_residual,
        chapter_no=chapter_no,
        is_leaf=is_leaf,
        is_primary_tabulation=is_primary,
    )


def import_tabulation_rows(
    rows: Iterable[dict[str, str]],
    *,
    release: str | None = None,
    linearization: str | None = None,
    clear_existing: bool = True,
    batch_size: int = 1000,
) -> tuple[int, int]:
    rel = release or settings.ICD11_RELEASE
    lin = linearization or settings.ICD11_LINEARIZATION

    objects: list[Icd11Code] = []
    seen_uris: set[tuple[str, str, str]] = set()
    skipped = 0
    for row in rows:
        obj = row_to_icd11_code(row, release=rel, linearization=lin)
        if obj is None:
            skipped += 1
            continue
        key = (obj.release, obj.linearization, obj.linearization_uri)
        if key in seen_uris:
            skipped += 1
            continue
        seen_uris.add(key)
        objects.append(obj)

    with transaction.atomic():
        if clear_existing:
            Icd11Code.objects.filter(release=rel, linearization=lin).delete()
        Icd11Code.objects.bulk_create(objects, batch_size=batch_size)

    return len(objects), skipped


def import_tabulation_from_bytes(
    data: bytes,
    *,
    release: str | None = None,
    linearization: str | None = None,
    clear_existing: bool = True,
) -> tuple[int, int]:
    rows = iter_tabulation_rows_from_bytes(data)
    return import_tabulation_rows(
        rows,
        release=release,
        linearization=linearization,
        clear_existing=clear_existing,
    )


def local_icd11_count(
    *,
    release: str | None = None,
    linearization: str | None = None,
) -> int:
    return Icd11Code.objects.filter(
        release=release or settings.ICD11_RELEASE,
        linearization=linearization or settings.ICD11_LINEARIZATION,
    ).count()


def _searchable_queryset(
    *,
    release: str | None = None,
    linearization: str | None = None,
    coded_only: bool = True,
):
    qs = Icd11Code.objects.filter(
        release=release or settings.ICD11_RELEASE,
        linearization=linearization or settings.ICD11_LINEARIZATION,
    )
    if coded_only:
        qs = qs.exclude(code='')
    return qs


def search_icd11_local(
    query: str,
    *,
    release: str | None = None,
    linearization: str | None = None,
    limit: int = 25,
    coded_only: bool = True,
) -> dict[str, Any]:
    clean_query = (query or '').strip()
    if not clean_query:
        raise ValueError('query is required.')

    rel = release or settings.ICD11_RELEASE
    lin = linearization or settings.ICD11_LINEARIZATION
    qs = _searchable_queryset(release=rel, linearization=lin, coded_only=coded_only)

    upper_query = clean_query.upper()
    filters = (
        Q(code__iexact=upper_query)
        | Q(code__istartswith=upper_query)
        | Q(title_plain__icontains=clean_query)
        | Q(title__icontains=clean_query)
    )
    if clean_query.isdigit():
        filters |= Q(entity_id=clean_query)

    ranked = qs.filter(filters).annotate(
        rank=Case(
            When(code__iexact=upper_query, then=Value(0)),
            When(code__istartswith=upper_query, then=Value(1)),
            When(title_plain__istartswith=clean_query, then=Value(2)),
            When(title_plain__icontains=clean_query, then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        )
    ).order_by('rank', 'code', 'title_plain')[:limit]

    results = [entry.to_search_result() for entry in ranked]
    return {
        'query': clean_query,
        'release': rel,
        'linearization': lin,
        'results': results,
        'source': 'local',
    }


def get_icd11_entity_local(
    entity_ref: str,
    *,
    release: str | None = None,
    linearization: str | None = None,
) -> dict[str, Any] | None:
    ref = (entity_ref or '').strip()
    if not ref:
        raise ValueError('entity_ref is required.')

    rel = release or settings.ICD11_RELEASE
    lin = linearization or settings.ICD11_LINEARIZATION
    qs = Icd11Code.objects.filter(release=rel, linearization=lin)

    if ref.startswith('http://') or ref.startswith('https://'):
        entry = qs.filter(Q(foundation_uri=ref) | Q(linearization_uri=ref)).first()
    else:
        entity_id = ref.rstrip('/').split('/')[-1]
        entry = qs.filter(
            Q(entity_id=entity_id)
            | Q(foundation_uri__endswith=f'/{entity_id}')
            | Q(linearization_uri__endswith=f'/{entity_id}')
        ).first()

    if not entry:
        return None
    return {
        'entity': entry.to_entity_dict(),
        'source': 'local',
    }


def get_icd11_code_info_local(
    code: str,
    *,
    release: str | None = None,
    linearization: str | None = None,
) -> dict[str, Any] | None:
    clean_code = (code or '').strip().upper()
    if not clean_code:
        raise ValueError('code is required.')

    rel = release or settings.ICD11_RELEASE
    lin = linearization or settings.ICD11_LINEARIZATION
    entry = (
        Icd11Code.objects.filter(release=rel, linearization=lin, code__iexact=clean_code)
        .order_by('-is_primary_tabulation', 'is_leaf')
        .first()
    )
    if not entry:
        return None
    return {
        'code': clean_code,
        'release': rel,
        'linearization': lin,
        'entity': entry.to_entity_dict(),
        'source': 'local',
    }
