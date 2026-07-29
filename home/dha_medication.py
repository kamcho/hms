"""DHA HPT (Health Products & Technologies) helpers for prescription coding."""
from __future__ import annotations

import re
from typing import Any


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def normalize_strength_spacing(text: str | None) -> str:
    """Turn '500mg' / '500MG' into '500 mg' — DHA GE search needs the space."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    return re.sub(
        r"(\d+(?:\.\d+)?)\s*(mg|g|ml|mcg|µg|iu)\b",
        r"\1 \2",
        raw,
        flags=re.I,
    )


def _tokens(text: str | None) -> list[str]:
    raw = _norm(normalize_strength_spacing(text))
    return [t for t in re.split(r"[^a-z0-9]+", raw) if t]


_FORM_HINTS = {
    "tablet": "Oral Tablet",
    "tabs": "Oral Tablet",
    "tab": "Oral Tablet",
    "capsule": "Oral Capsule",
    "caps": "Oral Capsule",
    "cap": "Oral Capsule",
    "syrup": "Oral Solution",
    "suspension": "Oral Suspension",
    "injection": "Injection",
    "infusion": "Infusion",
    "ointment": "Ointment",
    "cream": "Cream",
    "drops": "Drops",
    "inhaler": "Inhaler",
    "suppository": "Rectal Suppository",
}


def _form_hint(formulation: str = "") -> str:
    key = _norm(formulation).split()[0] if formulation else ""
    return _FORM_HINTS.get(key, "")


def rank_hpt_results(
    results: list[dict[str, Any]],
    *,
    query: str = "",
    prefer_generic: bool = True,
) -> list[dict[str, Any]]:
    """
    Rank HPT concepts for prescribing.

    Prefer GE* generic products (eRx ``generic_concept_code``), then closer
    title matches to the local drug search string. Prefer simple products over
    multi-ingredient combos when the query names a single drug.
    """
    q = _norm(normalize_strength_spacing(query))
    q_tokens = _tokens(query)

    def score(item: dict[str, Any]) -> tuple:
        code = str(item.get("code") or "").upper()
        title = _norm(item.get("title"))
        title_tokens = _tokens(title)
        kind = item.get("kind") or ""
        kind_rank = 0 if (prefer_generic and kind == "generic_product") else (
            1 if kind == "product" else 2 if kind == "active_component" else 3
        )
        exact = 0 if title and title == q else 1
        starts = 0 if title and q and title.startswith(q.split()[0] if q else "") else 1
        matched = sum(1 for t in q_tokens if t in title_tokens) if q_tokens else 0
        coverage = -matched
        first = q_tokens[0] if q_tokens else ""
        starts_drug = 0 if first and title_tokens and title_tokens[0] == first else 1
        slash_penalty = title.count("/") + title.count("+")
        length_penalty = len(title_tokens)
        ge_bonus = 0 if code.startswith("GE") else 1
        return (
            kind_rank if prefer_generic else ge_bonus,
            coverage,
            starts_drug,
            exact,
            starts,
            slash_penalty,
            length_penalty,
            title,
        )

    return sorted(list(results), key=score)


def build_local_search_query(
    *,
    name: str = "",
    generic_name: str = "",
    formulation: str = "",
) -> str:
    """Build a DHA search string from local inventory metadata."""
    parts: list[str] = []
    generic = (generic_name or "").strip()
    brand = (name or "").strip()
    form = (formulation or "").strip()
    if generic:
        parts.append(generic)
        strength = re.search(
            r"(\d+(?:\.\d+)?\s*(?:mg|g|ml|mcg|µg|iu)\b)",
            brand,
            flags=re.I,
        )
        if strength:
            parts.append(normalize_strength_spacing(strength.group(1)))
        elif form:
            parts.append(form)
    elif brand:
        parts.append(brand)
    return normalize_strength_spacing(" ".join(parts).strip() or brand or generic)


def _candidate_queries(
    *,
    query: str,
    name: str = "",
    generic_name: str = "",
    formulation: str = "",
) -> list[str]:
    """
    DHA search is sensitive to spacing ('500mg' vs '500 mg').

    Try several phrasings so GE* generic products surface instead of PH* packs.
    """
    primary = normalize_strength_spacing(query)
    candidates: list[str] = []

    def add(q: str) -> None:
        q = normalize_strength_spacing(q).strip()
        if q and q.lower() not in {c.lower() for c in candidates}:
            candidates.append(q)

    add(primary)

    # Drop units glued forms already handled; also try name + strength only
    tokens = _tokens(primary)
    drug = (generic_name or "").strip() or (tokens[0].title() if tokens else "")
    nums = [t for t in tokens if t.isdigit() or re.match(r"^\d+\.\d+$", t)]
    units = [t for t in tokens if t in {"mg", "g", "ml", "mcg", "iu"}]
    strength = ""
    if nums and units:
        strength = f"{nums[0]} {units[0]}"
    elif nums:
        strength = nums[0]

    form_hint = _form_hint(formulation)
    if drug and strength:
        add(f"{drug} {strength}")
        if form_hint:
            add(f"{drug} {strength} {form_hint}")
    if drug and form_hint and not strength:
        add(f"{drug} {form_hint}")

    # Last resort: brand name with spaced strength
    if name:
        add(normalize_strength_spacing(name))

    return candidates


def _dedupe_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        code = str(item.get("code") or "").upper()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(item)
    return out


def search_dha_medications(
    query: str,
    *,
    limit: int = 25,
    prefer_generic: bool = True,
    name: str = "",
    generic_name: str = "",
    formulation: str = "",
) -> dict[str, Any]:
    """Search DHA HPT terminology; returns ranked results for the picker API."""
    clean = normalize_strength_spacing(query)
    if not clean:
        raise ValueError("query is required.")

    from accounts.sha_hie_service import ShaHieClient, ShaHieError

    client = ShaHieClient()
    merged: list[dict[str, Any]] = []
    last_payload: dict[str, Any] = {}
    queries = _candidate_queries(
        query=clean,
        name=name,
        generic_name=generic_name,
        formulation=formulation,
    )

    try:
        for q in queries:
            payload = client.search_hpt(q, limit=max(limit, 40))
            last_payload = payload
            merged.extend(payload.get("results") or [])
            if prefer_generic:
                ge_hits = [
                    r for r in (payload.get("results") or [])
                    if r.get("kind") == "generic_product"
                ]
                # Stop early once we have solid GE matches
                if len(ge_hits) >= 3:
                    break
    except ShaHieError as exc:
        return {
            "success": False,
            "query": clean,
            "results": [],
            "error": str(exc),
            "message": "DHA medication terminology is temporarily unavailable.",
        }

    ranked = rank_hpt_results(
        _dedupe_results(merged),
        query=clean,
        prefer_generic=prefer_generic,
    )
    if prefer_generic:
        generics = [r for r in ranked if r.get("kind") == "generic_product"]
        # Keep only GE* whose title includes the drug name token(s).
        # Avoid "Aspirin 75 mg" → "Ciclosporin 75 mg Oral Tablet" false hits.
        name_tokens = [
            t for t in _tokens(generic_name or clean)
            if t not in {"mg", "g", "ml", "mcg", "iu", "oral", "tablet", "capsule"}
            and not re.match(r"^\d+(\.\d+)?$", t)
        ]
        if name_tokens:
            drug = name_tokens[0]
            named = [
                r for r in generics
                if drug in _tokens(r.get("title"))
            ]
            # If multi-word INN (acetylsalicylic acid), require first two when present
            if len(name_tokens) >= 2 and not named:
                named = [
                    r for r in generics
                    if name_tokens[0] in _tokens(r.get("title"))
                    and name_tokens[1] in _tokens(r.get("title"))
                ]
            generics = named
        ranked = generics

    ranked = ranked[:limit]
    return {
        "success": True,
        "query": clean,
        "queries_tried": queries,
        "owner": last_payload.get("owner"),
        "source": last_payload.get("source"),
        "results": ranked,
        "count": len(ranked),
        "message": (
            f"Found {len(ranked)} DHA generic product(s)."
            if ranked
            else "No DHA generic product (GE*) matched this medicine name. "
                 "You can still prescribe from local stock, or search DHA manually "
                 "(e.g. acetylsalicylic acid for aspirin)."
        ),
    }


def suggest_dha_for_local_drug(
    *,
    name: str = "",
    generic_name: str = "",
    formulation: str = "",
    limit: int = 15,
) -> dict[str, Any]:
    """Suggest a DHA generic product after a local inventory drug is selected."""
    query = build_local_search_query(
        name=name,
        generic_name=generic_name,
        formulation=formulation,
    )
    if not query:
        return {
            "success": False,
            "query": "",
            "results": [],
            "suggested": None,
            "message": "No drug name available for DHA lookup.",
        }

    payload = search_dha_medications(
        query,
        limit=limit,
        prefer_generic=True,
        name=name,
        generic_name=generic_name,
        formulation=formulation,
    )
    results = payload.get("results") or []
    suggested = results[0] if results else None

    auto = False
    if suggested and suggested.get("kind") == "generic_product":
        q_tokens = _tokens(query)
        t_tokens = _tokens(suggested.get("title"))
        if len(results) == 1:
            auto = True
        elif q_tokens and t_tokens and all(t in t_tokens for t in q_tokens):
            if suggested.get("title", "").count("/") == 0:
                auto = True
            elif q_tokens[0] == t_tokens[0]:
                auto = True

    payload["suggested"] = suggested
    payload["auto_selected"] = bool(auto and suggested)
    payload["local"] = {
        "name": name or None,
        "generic_name": generic_name or None,
        "formulation": formulation or None,
    }
    if not payload.get("success"):
        return payload
    if not results:
        payload["message"] = (
            f'No DHA generic product found for "{query}". '
            "Use Search DHA and pick a GE* product (strength + form), "
            "not a PH* pack code."
        )
    elif auto:
        payload["message"] = (
            f'DHA match: {suggested.get("code")} — {suggested.get("title")}'
        )
    else:
        payload["message"] = (
            f'Choose the DHA generic product for "{query}" '
            f"({len(results)} match(es)). "
            "Pick strength + form (GE*), not brand packs (PH*)."
        )
    return payload
