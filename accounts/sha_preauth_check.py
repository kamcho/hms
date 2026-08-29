"""
SHA preauth advisory checks for clinical ordering (labs / prescriptions).

Looks up intervention coverage flags (needsPreauth / elective) so clinicians
can inform patients before ordering. Does not block care by default.
"""
from __future__ import annotations

from typing import Any, Iterable

from django.db.models import QuerySet


def visit_is_sha_billed(visit) -> bool:
    if visit is None:
        return False
    method = (getattr(visit, "payment_method", None) or "").strip().upper()
    if method in ("SHA", "INSURANCE", "SHIF", "UHC"):
        return True
    session = getattr(visit, "sha_claim_session", None)
    return bool(session and (session.consent_token or session.eligible or session.patient_cr_id))


def get_sha_session(visit):
    if visit is None:
        return None
    return getattr(visit, "sha_claim_session", None)


def _index_interventions(interventions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in interventions or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip().upper()
        if code:
            indexed[code] = item
    return indexed


def interventions_from_session(session) -> list[dict[str, Any]]:
    if session is None:
        return []
    snap = session.coverage_snapshot or {}
    items = snap.get("interventions") or []
    if isinstance(items, list) and items:
        return [i for i in items if isinstance(i, dict)]
    meta = session.intervention_meta or {}
    codes = session.intervention_codes or []
    if codes and meta:
        return [{
            "code": str(codes[0]),
            "name": meta.get("name") or str(codes[0]),
            "needs_preauth": bool(meta.get("needs_preauth")),
            "needs_manual_preauth_approval": bool(
                meta.get("needs_manual_preauth_approval")
            ),
            "payment_mechanism": meta.get("payment_mechanism") or "",
            "access_point": meta.get("access_point") or "",
            "fund": meta.get("fund") or "",
        }]
    return []


def refresh_interventions_for_codes(
    session,
    codes: Iterable[str],
) -> list[dict[str, Any]]:
    """
    Prefer cached coverage_snapshot; for missing codes try live DHA lookup
    when patient_cr_id + sub_benefit_code are available.
    """
    local = interventions_from_session(session)
    indexed = _index_interventions(local)
    missing = [
        c.strip().upper()
        for c in codes
        if c and str(c).strip().upper() not in indexed
    ]
    if not missing or session is None:
        return local

    cr_id = (session.patient_cr_id or "").strip()
    sub = (session.sub_benefit_code or "").strip()
    if not cr_id:
        return local

    try:
        from accounts.sha_hie_service import ShaHieClient, normalize_interventions

        client = ShaHieClient()
        fetched: list[dict[str, Any]] = []
        # One call with search per missing code (bounded)
        for code in missing[:8]:
            try:
                raw = client.get_patient_interventions(
                    cr_id,
                    sub_benefit_code=sub or None,
                    search=code,
                )
                fetched.extend(normalize_interventions(raw))
            except Exception:
                continue
        if fetched:
            # Merge into snapshot
            merged = {**indexed}
            for item in fetched:
                c = str(item.get("code") or "").strip().upper()
                if c:
                    merged[c] = item
            new_list = list(merged.values())
            snap = dict(session.coverage_snapshot or {})
            snap["interventions"] = new_list
            session.coverage_snapshot = snap
            session.save(update_fields=["coverage_snapshot", "updated_at"])
            return new_list
    except Exception:
        pass
    return local


def _preauth_row(
    *,
    label: str,
    intervention_code: str,
    coverage: dict[str, Any] | None,
    source: str,
) -> dict[str, Any] | None:
    code = (intervention_code or "").strip()
    if not code:
        return {
            "label": label,
            "intervention_code": "",
            "intervention_name": "",
            "needs_preauth": False,
            "needs_manual_preauth_approval": False,
            "mapped": False,
            "source": source,
            "message": (
                f'"{label}" has no SHA intervention code mapped. '
                "Map it in the service/inventory catalog to check preauth."
            ),
        }

    if not coverage:
        return {
            "label": label,
            "intervention_code": code,
            "intervention_name": "",
            "needs_preauth": None,
            "needs_manual_preauth_approval": None,
            "mapped": True,
            "source": source,
            "message": (
                f'"{label}" maps to {code}, but coverage flags were not found '
                "in the patient's SHA benefits snapshot. Refresh eligibility / coverage."
            ),
        }

    needs = bool(coverage.get("needs_preauth"))
    elective = bool(coverage.get("needs_manual_preauth_approval"))
    name = coverage.get("name") or code
    if not needs:
        return None  # no advisory needed

    kind = "elective (approve before visit day)" if elective else "same-day (SHA approval during visit)"
    return {
        "label": label,
        "intervention_code": code,
        "intervention_name": name,
        "needs_preauth": True,
        "needs_manual_preauth_approval": elective,
        "mapped": True,
        "source": source,
        "message": (
            f'"{label}" requires SHA pre-authorization ({kind}). '
            f"Intervention {code} — {name}. Inform the patient before proceeding."
        ),
    }


def check_services_preauth(visit, services: QuerySet | list) -> dict[str, Any]:
    """
    Check lab/procedure Service rows for SHA preauth requirements.
    """
    if not visit_is_sha_billed(visit):
        return {
            "sha_visit": False,
            "requires_attention": False,
            "items": [],
            "inform_patient": [],
            "unmapped": [],
            "message": "Visit is not SHA-billed — preauth check skipped.",
        }

    session = get_sha_session(visit)
    service_list = list(services)
    codes = [
        (getattr(s, "sha_intervention_code", None) or "").strip()
        for s in service_list
        if (getattr(s, "sha_intervention_code", None) or "").strip()
    ]
    interventions = refresh_interventions_for_codes(session, codes)
    indexed = _index_interventions(interventions)

    items: list[dict[str, Any]] = []
    for svc in service_list:
        code = (getattr(svc, "sha_intervention_code", None) or "").strip()
        cov = indexed.get(code.upper()) if code else None
        row = _preauth_row(
            label=svc.name,
            intervention_code=code,
            coverage=cov,
            source="service",
        )
        if row:
            items.append(row)

    # Visit-level fallback when nothing mapped but session says preauth needed
    if not any(i.get("needs_preauth") for i in items) and session:
        meta = session.intervention_meta or {}
        if meta.get("needs_preauth") and session.status not in (
            "preauth_approved",
            "submitted",
            "closed",
        ):
            codes_sess = session.intervention_codes or []
            code0 = codes_sess[0] if codes_sess else ""
            items.append({
                "label": "Visit SHA intervention",
                "intervention_code": code0,
                "intervention_name": meta.get("name") or code0,
                "needs_preauth": True,
                "needs_manual_preauth_approval": bool(
                    meta.get("needs_manual_preauth_approval")
                ),
                "mapped": bool(code0),
                "source": "visit",
                "message": (
                    "This SHA visit's primary intervention requires pre-authorization. "
                    "Inform the patient; complete preauth on the SHA claims desk before "
                    "expecting SHA payment for restricted services."
                ),
            })

    needing = [i for i in items if i.get("needs_preauth")]
    unmapped = [i for i in items if i.get("mapped") is False]
    unknown = [
        i for i in items
        if i.get("mapped") and i.get("needs_preauth") is None
    ]

    return {
        "sha_visit": True,
        "session_status": getattr(session, "status", None) if session else None,
        "claims_desk_url": (
            f"/accounts/sha/claims/{visit.pk}/" if visit and visit.pk else None
        ),
        "requires_attention": bool(needing or unmapped or unknown),
        "items": items,
        "inform_patient": needing,
        "unmapped": unmapped,
        "unknown_coverage": unknown,
        "message": (
            f"{len(needing)} ordered item(s) need SHA pre-authorization — inform the patient."
            if needing
            else (
                "Some items are missing SHA intervention mapping or coverage data."
                if (unmapped or unknown)
                else "No SHA pre-authorization required for the selected items."
            )
        ),
    }


def check_inventory_preauth(visit, inventory_items: QuerySet | list) -> dict[str, Any]:
    """Check prescribed InventoryItem / Medication stock rows for SHA preauth."""
    if not visit_is_sha_billed(visit):
        return {
            "sha_visit": False,
            "requires_attention": False,
            "items": [],
            "inform_patient": [],
            "unmapped": [],
            "message": "Visit is not SHA-billed — preauth check skipped.",
        }

    session = get_sha_session(visit)
    item_list = list(inventory_items)
    codes = []
    for inv in item_list:
        code = (getattr(inv, "sha_intervention_code", None) or "").strip()
        if not code:
            med = getattr(inv, "medication", None)
            code = (getattr(med, "sha_intervention_code", None) or "").strip() if med else ""
        if code:
            codes.append(code)

    interventions = refresh_interventions_for_codes(session, codes)
    indexed = _index_interventions(interventions)

    items: list[dict[str, Any]] = []
    for inv in item_list:
        code = (getattr(inv, "sha_intervention_code", None) or "").strip()
        if not code:
            med = getattr(inv, "medication", None)
            code = (getattr(med, "sha_intervention_code", None) or "").strip() if med else ""
        cov = indexed.get(code.upper()) if code else None
        row = _preauth_row(
            label=inv.name,
            intervention_code=code,
            coverage=cov,
            source="medication",
        )
        if row:
            items.append(row)

    if not any(i.get("needs_preauth") for i in items) and session:
        meta = session.intervention_meta or {}
        if meta.get("needs_preauth") and session.status not in (
            "preauth_approved",
            "submitted",
            "closed",
        ):
            codes_sess = session.intervention_codes or []
            code0 = codes_sess[0] if codes_sess else ""
            items.append({
                "label": "Visit SHA intervention",
                "intervention_code": code0,
                "intervention_name": meta.get("name") or code0,
                "needs_preauth": True,
                "needs_manual_preauth_approval": bool(
                    meta.get("needs_manual_preauth_approval")
                ),
                "mapped": bool(code0),
                "source": "visit",
                "message": (
                    "This SHA visit's primary intervention requires pre-authorization. "
                    "Inform the patient that SHA may require approval before paying "
                    "for restricted pharmacy benefits."
                ),
            })

    needing = [i for i in items if i.get("needs_preauth")]
    unmapped = [i for i in items if i.get("mapped") is False]
    unknown = [
        i for i in items
        if i.get("mapped") and i.get("needs_preauth") is None
    ]

    return {
        "sha_visit": True,
        "session_status": getattr(session, "status", None) if session else None,
        "claims_desk_url": (
            f"/accounts/sha/claims/{visit.pk}/" if visit and visit.pk else None
        ),
        "requires_attention": bool(needing or unmapped or unknown),
        "items": items,
        "inform_patient": needing,
        "unmapped": unmapped,
        "unknown_coverage": unknown,
        "message": (
            f"{len(needing)} prescribed item(s) need SHA pre-authorization — inform the patient."
            if needing
            else (
                "Some medications are missing SHA intervention mapping or coverage data."
                if (unmapped or unknown)
                else "No SHA pre-authorization required for the selected medications."
            )
        ),
    }
