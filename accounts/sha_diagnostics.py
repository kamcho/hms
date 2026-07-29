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
    Run AfyaLink connectivity probes for auth, eligibility, and client registry.
    Safe to share output with DHA (credentials are masked).
    """
    base = settings.SHA_HIE_BASE_URL.rstrip("/")
    username = settings.SHA_HIE_USERNAME
    password = settings.SHA_HIE_PASSWORD
    consumer_key = settings.SHA_HIE_CONSUMER_KEY
    agent_id = getattr(settings, "SHA_HIE_AGENT_ID", "") or ""
    token_path = settings.SHA_HIE_TOKEN_PATH
    eligibility_path = settings.SHA_HIE_ELIGIBILITY_PATH
    client_path = settings.SHA_HIE_CLIENT_VERIFY_PATH
    timeout = settings.SHA_HIE_TIMEOUT_SECONDS

    checks: list[dict[str, Any]] = []

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

    token = ""
    if auth_check.get("ok"):
        preview = auth_check.get("response_preview") or ""
        token = preview.strip()
        if token.startswith("{"):
            try:
                import json

                payload = json.loads(preview)
                token = str(
                    payload.get("token")
                    or payload.get("access_token")
                    or ""
                ).strip()
            except ValueError:
                token = ""

    def _fresh_bearer_headers() -> dict[str, str] | None:
        """AfyaLink JWTs are single-use — fetch a new token per API call."""
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
        return {"Authorization": f"Bearer {jwt}", "Accept": "application/json"}

    elig_url = f"{base}{eligibility_path}"
    elig_check = _probe(
        "Eligibility (v2)",
        "GET",
        elig_url,
        params={
            "identification_type": identification_type,
            "identification_number": sample_id,
        },
        headers=_fresh_bearer_headers(),
        timeout=max(timeout, 60),
    )
    checks.append(elig_check)

    cr_url = f"{base}{client_path}"
    cr_check = _probe(
        "Client Registry (fetch-client)",
        "GET",
        cr_url,
        params={
            "identification_type": identification_type,
            "identification_number": sample_id,
            "agent": agent_id or consumer_key,
        },
        headers=_fresh_bearer_headers(),
        timeout=timeout,
    )
    checks.append(cr_check)

    auth_ok = bool(auth_check.get("ok"))
    elig_ok = bool(elig_check.get("ok"))
    cr_ok = bool(cr_check.get("ok"))
    elig_522 = elig_check.get("status_code") == 522

    if auth_ok and cr_ok and not elig_ok and elig_522:
        summary = (
            "UAT authentication and Client Registry respond, but /v2/eligibility "
            "returns HTTP 522 (Cloudflare origin timeout). This indicates an "
            "upstream AfyaLink eligibility service outage, not HMIS misconfiguration."
        )
        recommendation = (
            f"Email {DHA_SUPPORT_EMAIL} with this report (portal ticket not required). "
            "Ask them to restore GET /v2/eligibility on UAT."
        )
    elif auth_ok and elig_ok:
        summary = "All probed AfyaLink endpoints responded successfully."
        recommendation = "No connectivity issue detected. If lookups still fail, check the specific ID in UAT data."
    elif not auth_ok:
        summary = "Authentication to AfyaLink failed. Check credentials in .env and AfyaLink portal."
        recommendation = "Verify SHA_HIE_USERNAME, SHA_HIE_PASSWORD, and SHA_HIE_CONSUMER_KEY match UAT credentials."
    else:
        summary = "Mixed AfyaLink connectivity results — see individual checks below."
        recommendation = f"Share this report with DHA at {DHA_SUPPORT_EMAIL}."

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "python": platform.python_version(),
        "base_url": base,
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
        "client_registry_ok": cr_ok,
    }


def format_sha_diagnostics_report(data: dict[str, Any]) -> str:
    lines = [
        "SHA / AfyaLink UAT Connectivity Diagnostic Report",
        "=" * 55,
        f"Generated (UTC): {data.get('generated_at')}",
        f"Host: {data.get('hostname')}",
        f"Python: {data.get('python')}",
        "",
        "Configuration (masked)",
        f"  Base URL: {data.get('base_url')}",
        f"  Username: {data.get('username_masked')}",
        f"  Consumer key: {data.get('consumer_key_masked')}",
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
        "HMIS integration notes",
        "  - Auth: GET /v1/hie-auth?key={consumer_key} + Basic Auth (per AfyaLink docs)",
        "  - Eligibility: GET /v2/eligibility?identification_type=&identification_number=",
        "  - Client Registry: GET /v3/client-registry/fetch-client + agent param",
        "",
        f"Please forward to: {data.get('dha_support_email')}",
        "",
    ])
    return "\n".join(lines)
