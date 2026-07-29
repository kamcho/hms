"""Align local Medication records with DHA HPT (MOH-PPB) concepts."""
from __future__ import annotations

import re
from typing import Any

import httpx
from django.utils import timezone


OCL_HPT_CONCEPT_URL = (
    "https://ilm-hie.dha.go.ke/ocl/orgs/MOH-PPB/sources/HPT/concepts/{code}/"
)


def fetch_hpt_concept_detail(code: str, *, timeout: float = 15.0) -> dict[str, Any] | None:
    """Fetch a single HPT concept from public OCL (enrichment for extras)."""
    clean = (code or "").strip()
    if not clean:
        return None
    try:
        response = httpx.get(
            OCL_HPT_CONCEPT_URL.format(code=clean),
            headers={"Accept": "application/json"},
            timeout=timeout,
            verify=False,
            follow_redirects=True,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        return data if isinstance(data, dict) else None
    except (httpx.HTTPError, ValueError):
        return None


def _formulation_from_title(title: str) -> str | None:
    t = (title or "").lower()
    mapping = [
        ("oral tablet", "Tablet"),
        ("tablet", "Tablet"),
        ("oral capsule", "Capsule"),
        ("capsule", "Capsule"),
        ("syrup", "Syrup"),
        ("oral suspension", "Suspension"),
        ("suspension", "Suspension"),
        ("oral solution", "Solution"),
        ("solution", "Solution"),
        ("injection", "Injection"),
        ("infusion", "Infusion"),
        ("ointment", "Ointment"),
        ("cream", "Cream"),
        ("drops", "Drops"),
        ("inhaler", "Inhaler"),
        ("suppository", "Suppository"),
    ]
    for needle, value in mapping:
        if needle in t:
            return value
    return None


def _ingredient_from_title(title: str) -> str:
    """Best-effort INN from 'Paracetamol 500 mg Oral Tablet'."""
    text = (title or "").strip()
    if not text:
        return ""
    m = re.match(
        r"^(.+?)\s+\d+(?:\.\d+)?\s*(?:mg|g|ml|mcg|µg|iu)\b",
        text,
        flags=re.I,
    )
    if m:
        return m.group(1).strip()
    # Drop trailing form words
    return re.sub(
        r"\b(oral|tablet|capsule|syrup|injection|infusion|ointment|cream|drops|inhaler|suppository|solution|suspension)\b",
        "",
        text,
        flags=re.I,
    ).strip(" ,/-")


def apply_dha_generic_product(
    medication,
    *,
    code: str,
    title: str = "",
    extras: dict[str, Any] | None = None,
    enrich: bool = True,
    sync_item_name: bool = True,
) -> None:
    """
    Write DHA GE* product fields onto a local Medication (and optionally item name).

    Does not save — caller saves.
    """
    clean_code = (code or "").strip().upper()
    display = (title or "").strip()
    detail_extras = dict(extras or {})

    if enrich and clean_code:
        detail = fetch_hpt_concept_detail(clean_code)
        if detail:
            if not display:
                display = (
                    detail.get("display_name")
                    or next(
                        (
                            n.get("name")
                            for n in (detail.get("names") or [])
                            if isinstance(n, dict)
                            and (n.get("name_type") or "").lower().startswith("fully")
                        ),
                        None,
                    )
                    or ""
                )
            for key, value in (detail.get("extras") or {}).items():
                detail_extras.setdefault(key, value)

    medication.generic_concept_code = clean_code
    medication.generic_concept_display = display
    medication.dha_mapped_at = timezone.now()

    strength_amount = str(detail_extras.get("strength_amount") or "").strip()
    strength_unit = str(detail_extras.get("strength_unit") or "").strip()
    if not strength_amount or not strength_unit:
        m = re.search(
            r"(\d+(?:\.\d+)?)\s*(mg|g|ml|mcg|µg|iu)\b",
            display,
            flags=re.I,
        )
        if m:
            strength_amount = strength_amount or m.group(1)
            strength_unit = strength_unit or m.group(2)

    if strength_amount:
        medication.strength_amount = strength_amount
    if strength_unit:
        unit = strength_unit.lower().replace("µg", "mcg")
        if unit == "iu":
            unit = "IU"
        allowed = {c[0] for c in medication.STRENGTH_UNIT_CHOICES}
        medication.strength_unit = unit if unit in allowed else "other"

    atc = str(detail_extras.get("atc_code") or "").strip()
    if atc:
        medication.atc_code = atc

    form_id = str(detail_extras.get("form_id") or "").strip()
    route_id = str(detail_extras.get("admin_route_id") or "").strip()
    if form_id:
        medication.dha_form_id = form_id
    if route_id:
        medication.dha_route_id = route_id

    ac = str(detail_extras.get("active_component_id") or "").strip()
    if ac:
        # OCL extras often store numeric id; prefer AC* if already a code
        if ac.upper().startswith("AC"):
            medication.active_component_code = ac.upper()
        else:
            medication.active_component_code = f"AC{ac}" if ac.isdigit() else ac

    ingredient = _ingredient_from_title(display)
    if ingredient:
        medication.generic_name = ingredient

    form_choice = _formulation_from_title(display)
    if form_choice:
        medication.formulation = form_choice

    if sync_item_name and display and getattr(medication, "item", None):
        medication.item.name = display
