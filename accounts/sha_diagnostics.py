from __future__ import annotations

import platform
import socket
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from django.conf import settings


DHA_SUPPORT_EMAIL = "afyaconnect.dha@gmail.com"


def _mask(value: str | None, *, show_last: int = 4) -> str:
    raw = (value or "").strip()
    if not raw:
        return "(not set)"
    if len(raw) <= show_last:
        return "*" * len(raw)
    return "*" * (len(raw) - show_last) + raw[-show_last:]


def _probe(
    name: str,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    auth: tuple[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    result: dict[str, Any] = {
        "name": name,
        "method": method,
        "url": url,
        "params": params or {},
        "status_code": None,
        "ok": False,
        "elapsed_ms": None,
        "response_preview": "",
        "error": None,
        "cf_ray": None,
        "server": None,
    }
    try:
        response = httpx.request(
            method,
            url,
            params=params,
            json=json_body,
            data=data,
            auth=auth,
            headers=headers,
            timeout=timeout or settings.SHA_HIE_TIMEOUT_SECONDS,
            verify=settings.SHA_HIE_VERIFY_SSL,
            follow_redirects=True,
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        result["status_code"] = response.status_code
        result["elapsed_ms"] = elapsed
        result["cf_ray"] = response.headers.get("cf-ray")
        result["server"] = response.headers.get("server")
        result["response_preview"] = (response.text or "")[:400]
        result["ok"] = 200 <= response.status_code < 300
        return result
    except httpx.HTTPError as exc:
        result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        result["error"] = str(exc)
        return result


def run_sha_connectivity_diagnostics(
    *,
    sample_id: str = "2897398",
    identification_type: str = "National ID",
) -> dict[str, Any]:
    """
    Run AfyaConnect / HIE connectivity probes for auth, patient search,
    eligibility, and sub-benefits on the ILM middleware.
    """
    base = settings.SHA_HIE_BASE_URL.rstrip("/")
    auth_mode = (getattr(settings, "SHA_HIE_AUTH_MODE", "oauth") or "oauth").lower()
    auth_base = (
        getattr(settings, "SHA_HIE_AUTH_BASE_URL", "") or ""
        or getattr(settings, "SHA_HIE_TERMINOLOGY_BASE_URL", "") or ""
        or base
    ).rstrip("/")
    eclaims_base = (
        getattr(settings, "SHA_HIE_ECLAIMS_BASE_URL", "") or ""
        or auth_base
    ).rstrip("/")
    username = settings.SHA_HIE_USERNAME
    password = settings.SHA_HIE_PASSWORD
    client_id = (
        getattr(settings, "SHA_HIE_CLIENT_ID", "") or settings.SHA_HIE_CONSUMER_KEY or ""
    ).strip()
    client_secret = (
        getattr(settings, "SHA_HIE_CLIENT_SECRET", "") or settings.SHA_HIE_CONSUMER_SECRET or ""
    ).strip()
    consumer_key = client_id
    agent_id = getattr(settings, "SHA_HIE_AGENT_ID", "") or ""
    token_path = settings.SHA_HIE_TOKEN_PATH
    patient_path = getattr(settings, "SHA_HIE_PATIENT_SEARCH_PATH", "/patients") or "/patients"
    eligibility_path = getattr(
        settings, "SHA_HIE_ELIGIBILITY_PATH", "/patients/eligibility"
    ) or "/patients/eligibility"
    if eligibility_path in ("/v2/eligibility", "/v1/eligibility"):
        eligibility_path = "/patients/eligibility"
    sub_benefits_path = getattr(
        settings, "SHA_HIE_SUB_BENEFITS_PATH", "/patients/sub-benefits"
    ) or "/patients/sub-benefits"
    facility_fr = getattr(settings, "SHA_HIE_FACILITY_FR_CODE", "") or ""
    facility_id_type = getattr(settings, "SHA_HIE_FACILITY_ID_TYPE", "fr-code") or "fr-code"
    timeout = settings.SHA_HIE_TIMEOUT_SECONDS

    checks: list[dict[str, Any]] = []

    if auth_mode in ("oauth", "afyaconnect", "tenants"):
        if (
            not token_path
            or token_path.rstrip("/").endswith("hie-auth")
            or token_path.startswith("/v1/")
        ):
            token_path = "/tenants/token"
        auth_url = f"{auth_base}{token_path if token_path.startswith('/') else '/' + token_path}"
        auth_check = _probe(
            "Authentication (POST /tenants/token)",
            "POST",
            auth_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
    else:
        auth_url = f"{base}{token_path}"
        auth_check = _probe(
            "Authentication (hie-auth)",
            "GET",
            auth_url,
            params={"key": consumer_key},
            auth=(username, password),
            timeout=timeout,
        )
    checks.append(auth_check)

    def _fresh_bearer_headers(*, with_facility: bool = False) -> dict[str, str] | None:
        if auth_mode in ("oauth", "afyaconnect", "tenants"):
            refresh = _probe(
                "Authentication (POST /tenants/token)",
                "POST",
                auth_url,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
                timeout=timeout,
            )
        else:
            refresh = _probe(
                "Authentication (hie-auth)",
                "GET",
                auth_url,
                params={"key": consumer_key},
                auth=(username, password),
                timeout=timeout,
            )
        if not refresh.get("ok"):
            return None
        raw = (refresh.get("response_preview") or "").strip()
        if raw.startswith("{"):
            try:
                import json

                payload = json.loads(raw)
                jwt = str(payload.get("token") or payload.get("access_token") or "").strip()
            except ValueError:
                jwt = ""
        else:
            jwt = raw
        if not jwt:
            return None
        headers = {"Authorization": f"Bearer {jwt}", "Accept": "application/json"}
        if with_facility and facility_fr:
            headers["X-Facility-Id"] = facility_fr
            headers["X-Facility-Id-Type"] = facility_id_type
        return headers

    id_params = {
        "identification_type": identification_type,
        "identification_number": sample_id,
    }

    patients_url = f"{eclaims_base}{patient_path if patient_path.startswith('/') else '/' + patient_path}"
    patients_check = _probe(
        "Patient Search (GET /patients)",
        "GET",
        patients_url,
        params=id_params,
        headers=_fresh_bearer_headers(with_facility=True),
        timeout=timeout,
    )
    checks.append(patients_check)

    elig_url = (
        f"{eclaims_base}"
        f"{eligibility_path if eligibility_path.startswith('/') else '/' + eligibility_path}"
    )
    elig_check = _probe(
        "Eligibility (GET /patients/eligibility)",
        "GET",
        elig_url,
        params=id_params,
        headers=_fresh_bearer_headers(with_facility=True),
        timeout=max(timeout, 60),
    )
    checks.append(elig_check)

    # Try to extract CR ID from patient search for sub-benefits
    cr_id = ""
    if patients_check.get("ok"):
        preview = patients_check.get("response_preview") or ""
        if preview.startswith("{"):
            try:
                import json

                pdata = json.loads(preview)
                if isinstance(pdata, dict):
                    cr_id = str(
                        pdata.get("id")
                        or pdata.get("memberCrNumber")
                        or (pdata.get("results") or [{}])[0].get("id")
                        if isinstance(pdata.get("results"), list) and pdata.get("results")
                        else pdata.get("id")
                        or ""
                    ).strip()
            except Exception:
                cr_id = ""

    sub_url = (
        f"{eclaims_base}"
        f"{sub_benefits_path if sub_benefits_path.startswith('/') else '/' + sub_benefits_path}"
    )
    sub_check = _probe(
        "Sub-benefits (GET /patients/sub-benefits)",
        "GET",
        sub_url,
        params={"patient_id": cr_id or sample_id},
        headers=_fresh_bearer_headers(with_facility=True),
        timeout=timeout,
    )
    checks.append(sub_check)

    pract_path = getattr(
        settings, "SHA_HIE_PRACTITIONER_SEARCH_PATH", "/professionals"
    ) or "/professionals"
    pract_url = (
        f"{eclaims_base}"
        f"{pract_path if pract_path.startswith('/') else '/' + pract_path}"
    )
    pract_check = _probe(
        "Health Worker Registry (GET /professionals)",
        "GET",
        pract_url,
        params={
            "identification_number": "123456",
            "identification_type": "registration_number",
            "regulator": "KMPDC",
        },
        headers=_fresh_bearer_headers(with_facility=True),
        timeout=timeout,
    )
    checks.append(pract_check)


    auth_ok = bool(auth_check.get("ok"))
    elig_ok = bool(elig_check.get("ok"))
    patients_ok = bool(patients_check.get("ok"))
    sub_ok = bool(sub_check.get("ok"))
    elig_522 = elig_check.get("status_code") == 522
    elig_403 = elig_check.get("status_code") in (401, 403)

    if auth_ok and patients_ok and not elig_ok and elig_522:
        summary = (
            "Auth and Patient Search respond, but /patients/eligibility "
            "returns HTTP 522 (upstream timeout)."
        )
        recommendation = (
            f"Email {DHA_SUPPORT_EMAIL} with this report. "
            "Ask them to restore GET /patients/eligibility on UAT middleware."
        )
    elif auth_ok and elig_403:
        summary = (
            "Eligibility returned 401/403 — usually missing/wrong facility FR code "
            "or facility not contracted for eClaims."
        )
        recommendation = (
            f"Set SHA_HIE_FACILITY_FR_CODE correctly (current: {facility_fr or 'not set'}). "
            f"If still failing, escalate to {DHA_SUPPORT_EMAIL}."
        )
    elif auth_ok and elig_ok:
        summary = "Auth, Patient Search, and Eligibility responded successfully."
        recommendation = (
            "No connectivity issue detected. If lookups still fail, check the sample ID "
            "and facility contract in UAT."
        )
    elif not auth_ok:
        summary = "Authentication failed. Check OAuth client_id/secret."
        recommendation = (
            "Verify SHA_HIE_CLIENT_ID / SHA_HIE_CLIENT_SECRET and SHA_HIE_AUTH_BASE_URL."
        )
    else:
        summary = "Mixed HIE connectivity results — see individual checks below."
        recommendation = f"Share this report with DHA at {DHA_SUPPORT_EMAIL}."

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "python": platform.python_version(),
        "base_url": base,
        "auth_mode": auth_mode,
        "auth_base_url": auth_base,
        "eclaims_base_url": eclaims_base,
        "facility_fr": facility_fr or None,
        "agent_id": agent_id or None,
        "consumer_key_masked": _mask(consumer_key),
        "username_masked": _mask(username),
        "sample_id": sample_id,
        "identification_type": identification_type,
        "summary": summary,
        "recommendation": recommendation,
        "dha_support_email": DHA_SUPPORT_EMAIL,
        "checks": checks,
        "auth_ok": auth_ok,
        "eligibility_ok": elig_ok,
        "client_registry_ok": patients_ok,
        "patient_search_ok": patients_ok,
        "sub_benefits_ok": sub_ok,
    }


def format_sha_diagnostics_report(data: dict[str, Any]) -> str:
    lines = [
        "SHA / AfyaConnect Connectivity Diagnostic Report",
        "=" * 55,
        f"Generated (UTC): {data.get('generated_at')}",
        f"Host: {data.get('hostname')}",
        f"Python: {data.get('python')}",
        "",
        "Configuration (masked)",
        f"  Base URL: {data.get('base_url')}",
        f"  Auth base: {data.get('auth_base_url')}",
        f"  eClaims base: {data.get('eclaims_base_url')}",
        f"  Facility FR: {data.get('facility_fr') or '(not set)'}",
        f"  Username: {data.get('username_masked')}",
        f"  Client id: {data.get('consumer_key_masked')}",
        f"  Agent ID: {data.get('agent_id') or '(not set)'}",
        f"  Sample ID: {data.get('identification_type')} {data.get('sample_id')}",
        "",
        "Summary",
        f"  {data.get('summary')}",
        "",
        "Recommendation",
        f"  {data.get('recommendation')}",
        "",
        "Endpoint checks",
    ]
    for check in data.get("checks") or []:
        lines.append("-" * 55)
        lines.append(f"  {check.get('name')}")
        lines.append(f"  {check.get('method')} {check.get('url')}")
        if check.get("params"):
            lines.append(f"  Params: {check.get('params')}")
        status = check.get("status_code")
        elapsed = check.get("elapsed_ms")
        lines.append(f"  Status: {status if status is not None else 'N/A'}  Time: {elapsed}ms")
        if check.get("cf_ray"):
            lines.append(f"  CF-Ray: {check.get('cf_ray')}")
        if check.get("error"):
            lines.append(f"  Error: {check.get('error')}")
        preview = (check.get("response_preview") or "").replace("\n", " ").strip()
        if preview:
            lines.append(f"  Response: {preview[:300]}")
    lines.extend([
        "",
        "HMIS integration notes (AfyaConnect Eligibility Process)",
        "  - Auth: POST /tenants/token (client_id + client_secret)",
        "  - Patient Search: GET /patients?identification_type=&identification_number=",
        "  - Eligibility: GET /patients/eligibility (+ X-Facility-Id / X-Facility-Id-Type)",
        "  - Sub-benefits: GET /patients/sub-benefits?patient_id={CR}",
        "  - Interventions: GET /patients/benefits/interventions?patient_id={CR}",
        "",
        f"Please forward to: {data.get('dha_support_email')}",
        "",
    ])
    return "\n".join(lines)
