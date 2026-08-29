from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
import re
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import httpx
from django.conf import settings
from django.core.cache import cache


TOKEN_CACHE_KEY = "sha_hie_access_token"
TOKEN_SOURCE_CACHE_KEY = "sha_hie_access_token_source"
TOKEN_TTL_SECONDS = 50 * 60  # fallback when expires_in missing


class ShaHieError(Exception):
    """Base SHA HIE integration error."""


class ShaHieConfigError(ShaHieError):
    """Raised when SHA HIE credentials/settings are missing."""


class ShaHieRequestError(ShaHieError):
    """Raised when SHA HIE request fails."""


@dataclass
class ShaPatientLookupResult:
    id_number: str
    found: bool
    raw: dict[str, Any]


@dataclass
class ShaFacilityLookupResult:
    facility_code: str
    found: bool
    raw: dict[str, Any]


@dataclass
class ShaPractitionerLookupResult:
    identification_number: str
    found: bool
    raw: dict[str, Any]


class ShaHieClient:
    """Thin client for SHA/DHA HIE endpoints (AfyaConnect / ILM middleware)."""

    def __init__(self) -> None:
        self.base_url = settings.SHA_HIE_BASE_URL.rstrip("/")
        self.username = settings.SHA_HIE_USERNAME
        self.password = settings.SHA_HIE_PASSWORD
        self.agent_id = getattr(settings, "SHA_HIE_AGENT_ID", "") or ""
        # AfyaConnect OAuth: client_id / client_secret (portal may label these consumer key/secret)
        self.client_id = (
            getattr(settings, "SHA_HIE_CLIENT_ID", "") or ""
            or getattr(settings, "SHA_HIE_CONSUMER_KEY", "") or ""
        ).strip()
        self.client_secret = (
            getattr(settings, "SHA_HIE_CLIENT_SECRET", "") or ""
            or getattr(settings, "SHA_HIE_CONSUMER_SECRET", "") or ""
        ).strip()
        self.consumer_key = self.client_id  # backwards-compatible alias
        self.consumer_secret = self.client_secret
        self.timeout = settings.SHA_HIE_TIMEOUT_SECONDS
        self.verify_ssl = settings.SHA_HIE_VERIFY_SSL
        self.auth_mode = (
            getattr(settings, "SHA_HIE_AUTH_MODE", "oauth") or "oauth"
        ).strip().lower()
        self.auth_base_url = (
            getattr(settings, "SHA_HIE_AUTH_BASE_URL", "") or ""
            or getattr(settings, "SHA_HIE_TERMINOLOGY_BASE_URL", "") or ""
            or self.base_url
        ).rstrip("/")
        configured_token_path = (
            getattr(settings, "SHA_HIE_TOKEN_PATH", "") or ""
        ).strip() or "/tenants/token"
        # OAuth must never use legacy /v1/hie-auth (causes .../api/v1/v1/hie-auth 404)
        if self.auth_mode in ("oauth", "afyaconnect", "tenants"):
            if (
                not configured_token_path
                or configured_token_path.rstrip("/").endswith("hie-auth")
                or configured_token_path.startswith("/v1/")
            ):
                self.token_path = "/tenants/token"
            else:
                self.token_path = configured_token_path
        else:
            self.token_path = configured_token_path
        self.client_verify_path = settings.SHA_HIE_CLIENT_VERIFY_PATH
        # AfyaConnect Patient Search (middleware)
        configured_patient_path = (
            getattr(settings, "SHA_HIE_PATIENT_SEARCH_PATH", "") or ""
        ).strip() or "/patients"
        if "client-registry" in configured_patient_path or configured_patient_path.startswith(
            "/v3/"
        ):
            self.patient_search_path = "/patients"
        else:
            self.patient_search_path = configured_patient_path
        # AfyaConnect eligibility — remap legacy /v2/eligibility
        configured_eligibility = (
            getattr(settings, "SHA_HIE_ELIGIBILITY_PATH", "") or ""
        ).strip() or "/patients/eligibility"
        if (
            configured_eligibility.rstrip("/").endswith("/eligibility")
            and configured_eligibility.startswith("/v")
        ) or configured_eligibility in ("/v2/eligibility", "/v1/eligibility"):
            self.eligibility_path = "/patients/eligibility"
        else:
            self.eligibility_path = configured_eligibility
        self.sub_benefits_path = (
            getattr(settings, "SHA_HIE_SUB_BENEFITS_PATH", "") or ""
        ).strip() or "/patients/sub-benefits"
        self.interventions_path = (
            getattr(settings, "SHA_HIE_INTERVENTIONS_PATH", "") or ""
        ).strip() or "/patients/benefits/interventions"
        self.utilization_path = (
            getattr(settings, "SHA_HIE_UTILIZATION_PATH", "") or ""
        ).strip() or "/patients/benefits/utilization"
        self.pomsf_balances_path = (
            getattr(settings, "SHA_HIE_POMSF_BALANCES_PATH", "") or ""
        ).strip() or "/patients/pomsf-balances"
        self.eclaims_base_url = (
            (
                getattr(settings, "SHA_HIE_ECLAIMS_BASE_URL", "")
                or getattr(settings, "SHA_HIE_AUTH_BASE_URL", "")
                or getattr(settings, "SHA_HIE_TERMINOLOGY_BASE_URL", "")
                or self.base_url
            )
            or self.base_url
        ).rstrip("/")
        configured_facility_path = (
            getattr(settings, "SHA_HIE_FACILITY_SEARCH_PATH", "") or ""
        ).strip() or "/facilities/search"
        # AfyaConnect registry is /facilities/search — ignore legacy /vN/facility-search on middleware
        if (
            "facility-search" in configured_facility_path
            or configured_facility_path.startswith("/v1/")
            or configured_facility_path.startswith("/v2/")
        ):
            self.facility_search_path = "/facilities/search"
        else:
            self.facility_search_path = configured_facility_path
        self.facility_registry_base_url = (
            (
                getattr(settings, "SHA_HIE_FACILITY_REGISTRY_BASE_URL", "")
                or getattr(settings, "SHA_HIE_AUTH_BASE_URL", "")
                or getattr(settings, "SHA_HIE_TERMINOLOGY_BASE_URL", "")
                or self.base_url
            )
            or self.base_url
        ).rstrip("/")
        self.facility_id_type_default = (
            getattr(settings, "SHA_HIE_FACILITY_ID_TYPE", "fr-code") or "fr-code"
        )
        self.practitioner_search_path = getattr(
            settings, "SHA_HIE_PRACTITIONER_SEARCH_PATH", "/professionals"
        ) or "/professionals"
        self.icd11_search_path = getattr(
            settings,
            "SHA_HIE_ICD11_SEARCH_PATH",
            "/clinical/concepts",
        )
        self.terminology_base_url = getattr(
            settings,
            "SHA_HIE_TERMINOLOGY_BASE_URL",
            "https://ilm-dev.dha.go.ke/uat-middleware/api/v1",
        ).rstrip("/")
        self.icd11_owner = getattr(settings, "SHA_HIE_ICD11_OWNER", "WHO") or "WHO"
        self.icd11_source = getattr(settings, "SHA_HIE_ICD11_SOURCE", "ICD-11") or "ICD-11"
        self.hpt_owner = getattr(settings, "SHA_HIE_HPT_OWNER", "MOH-PPB") or "MOH-PPB"
        self.hpt_source = getattr(settings, "SHA_HIE_HPT_SOURCE", "HPT") or "HPT"
        self.loinc_owner = getattr(settings, "SHA_HIE_LOINC_OWNER", "Regenstrief") or "Regenstrief"
        self.loinc_source = getattr(settings, "SHA_HIE_LOINC_SOURCE", "LOINC") or "LOINC"
        self.loinc_search_path = getattr(
            settings, "SHA_HIE_LOINC_SEARCH_PATH", "/clinical/loinc/search"
        ) or "/clinical/loinc/search"
        self.ichi_owner = getattr(settings, "SHA_HIE_ICHI_OWNER", "WHO") or "WHO"
        self.ichi_source = getattr(settings, "SHA_HIE_ICHI_SOURCE", "ICHI") or "ICHI"
        self.ichi_search_path = getattr(
            settings, "SHA_HIE_ICHI_SEARCH_PATH", "/clinical/concepts"
        ) or "/clinical/concepts"

    def _validate_config(self) -> None:
        if self.auth_mode in ("oauth", "afyaconnect", "tenants"):
            if not self.client_id or not self.client_secret:
                raise ShaHieConfigError(
                    "SHA_HIE_CLIENT_ID / SHA_HIE_CLIENT_SECRET "
                    "(or SHA_HIE_CONSUMER_KEY / SHA_HIE_CONSUMER_SECRET) are required "
                    "for AfyaConnect OAuth token (POST /tenants/token)."
                )
            return
        # Legacy AfyaLink Basic → /v1/hie-auth
        if not self.username or not self.password:
            raise ShaHieConfigError(
                "SHA_HIE_USERNAME and SHA_HIE_PASSWORD are required for basic auth mode."
            )
        if not self.client_id:
            raise ShaHieConfigError(
                "SHA_HIE_CONSUMER_KEY (Token Authentication Key) is required."
            )

    def _extract_token(self, payload: dict[str, Any]) -> tuple[str, int]:
        token = (
            payload.get("token")
            or payload.get("access_token")
            or payload.get("bearer_token")
            or payload.get("jwt")
        )
        expires_in = int(payload.get("expires_in") or TOKEN_TTL_SECONDS)
        if not token:
            raise ShaHieRequestError("Token response did not include access token.")
        return str(token), expires_in

    def _get_access_token(self, *, force_refresh: bool = False) -> str:
        """
        AfyaConnect / HIE auth (current DHA standard):

          POST {auth_base}/tenants/token
          Content-Type: application/x-www-form-urlencoded
          Body: client_id=…&client_secret=…

          → { access_token, expires_in, token_type }

        Docs: https://afyaconnect.dha.go.ke/hie-api/auth/authentication
              https://hie-docs.dha.go.ke/auth/authentication

        If OAuth credentials are rejected (invalid_client) and Basic Auth
        credentials exist, falls back to legacy GET /v1/hie-auth so lookups
        keep working while AfyaConnect client credentials are provisioned.

        Set SHA_HIE_AUTH_MODE=basic to skip OAuth entirely.
        """
        if not force_refresh:
            cached = cache.get(TOKEN_CACHE_KEY)
            if cached:
                return str(cached)

        if self.auth_mode in ("basic", "afyalink", "hie-auth"):
            token = self._get_access_token_basic(force_refresh=force_refresh)
            cache.set(TOKEN_CACHE_KEY, token, timeout=TOKEN_TTL_SECONDS)
            cache.set(TOKEN_SOURCE_CACHE_KEY, "basic", timeout=TOKEN_TTL_SECONDS)
            return token

        try:
            token = self._get_access_token_oauth(force_refresh=force_refresh)
            cache.set(TOKEN_SOURCE_CACHE_KEY, "oauth", timeout=TOKEN_TTL_SECONDS)
            return token
        except ShaHieRequestError as oauth_exc:
            can_fallback = bool(self.username and self.password and self.client_id)
            msg = str(oauth_exc).lower()
            looks_like_bad_client = (
                "invalid_client" in msg
                or "401" in msg
                or "400" in msg
                or "500" in msg
                or "unauthorized" in msg
            )
            if can_fallback and looks_like_bad_client:
                print(
                    "[SHA DEBUG] oauth failed; falling back to legacy /v1/hie-auth. "
                    f"oauth_error={oauth_exc}"
                )
                cache.delete(TOKEN_CACHE_KEY)
                token = self._get_access_token_basic(force_refresh=True)
                cache.set(TOKEN_CACHE_KEY, token, timeout=TOKEN_TTL_SECONDS)
                cache.set(TOKEN_SOURCE_CACHE_KEY, "basic", timeout=TOKEN_TTL_SECONDS)
                return token
            raise

    def _token_source(self) -> str:
        """'oauth' (AfyaConnect) or 'basic' (AfyaLink). Middleware needs oauth."""
        return str(cache.get(TOKEN_SOURCE_CACHE_KEY) or "").strip().lower() or "unknown"

    def _middleware_usable(self) -> bool:
        """ILM middleware APIs reject AfyaLink JWTs — only call them with OAuth tokens."""
        try:
            self._get_access_token()
        except ShaHieRequestError:
            return False
        return self._token_source() == "oauth"

    def _require_middleware_oauth(self, action: str) -> None:
        """
        Consent / eClaims middleware (contacts, OTP, start visit, etc.) only
        accepts AfyaConnect OAuth tokens from POST /tenants/token.

        AfyaLink CONSUMER_KEY/SECRET produce invalid_client on that endpoint;
        the fallback AfyaLink JWT then fails middleware with
        \"Invalid or expired token: token is not active\".
        """
        if self._middleware_usable():
            return
        source = self._token_source()
        raise ShaHieConfigError(
            f"{action} requires AfyaConnect OAuth credentials "
            "(SHA_HIE_CLIENT_ID / SHA_HIE_CLIENT_SECRET from DHA AfyaConnect), "
            "not AfyaLink CONSUMER_KEY/SECRET. "
            f"Current token source is '{source or 'none'}' (legacy AfyaLink). "
            "Ask DHA to provision AfyaConnect client credentials for "
            f"{self.auth_base_url}/tenants/token, then set them in .env and "
            "restart the server. Patient search can still use AfyaLink; "
            "consent, OTP, and visit start cannot."
        )

    def _get_access_token_oauth(self, *, force_refresh: bool = False) -> str:
        self._validate_config()
        if force_refresh:
            cache.delete(TOKEN_CACHE_KEY)
        else:
            cached = cache.get(TOKEN_CACHE_KEY)
            if cached:
                return str(cached)

        path = self.token_path if self.token_path.startswith("/") else f"/{self.token_path}"
        # Guard against leftover /v1/hie-auth in env while on oauth mode
        if path.rstrip("/").endswith("hie-auth") or path.startswith("/v1/"):
            path = "/tenants/token"
        url = f"{self.auth_base_url.rstrip('/')}{path}"

        print(
            f"[SHA DEBUG] oauth auth POST {url} "
            f"client_id={self.client_id[:6]}… (form-urlencoded)"
        )
        try:
            # Middleware binds LoginInput from form fields, not JSON body.
            response = httpx.post(
                url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Accept": "application/json"},
                timeout=self.timeout,
                verify=self.verify_ssl,
                follow_redirects=True,
            )
            print(
                f"[SHA DEBUG] oauth auth status={response.status_code} "
                f"body={response.text[:220]!r}"
            )
            if response.status_code >= 400:
                raise ShaHieRequestError(
                    f"Failed to authenticate with AfyaConnect (POST {url}): "
                    f"HTTP {response.status_code} {response.text[:300]}"
                )
            data = response.json() if response.content else {}
            if not isinstance(data, dict):
                raise ShaHieRequestError(
                    f"Unexpected token response type from {url}: {type(data)}"
                )
            token, expires_in = self._extract_token(data)
            cache.set(TOKEN_CACHE_KEY, token, timeout=max(int(expires_in) - 60, 60))
            cache.set(TOKEN_SOURCE_CACHE_KEY, "oauth", timeout=max(int(expires_in) - 60, 60))
            print(
                f"[SHA DEBUG] oauth auth success token_len={len(token)} "
                f"expires_in={expires_in}"
            )
            return token
        except httpx.HTTPError as exc:
            print(f"[SHA DEBUG] oauth auth HTTP error: {exc}")
            raise ShaHieRequestError(
                f"Failed to authenticate with AfyaConnect (POST {url}): {exc}"
            ) from exc

    def _get_access_token_basic(self, *, force_refresh: bool = False) -> str:
        """
        Legacy AfyaLink Basic Authentication flow:
        GET /v1/hie-auth?key={consumer_key}
        Authorization: Basic base64(username:password)
        """
        self._validate_config()
        print(
            f"[SHA DEBUG] basic auth start base={self.base_url} "
            f"token_path={self.token_path} key={self.client_id} agent={self.agent_id}"
        )
        attempts = [
            {
                "base": self.base_url,
                "path": self.token_path if self.token_path.startswith("/v1/") else "/v1/hie-auth",
                "auth": (self.username, self.password),
                "params": {"key": self.client_id},
            },
        ]
        if "api.dha.go.ke" not in self.base_url:
            attempts.append({
                "base": "https://api.dha.go.ke",
                "path": "/v1/hie-auth",
                "auth": (self.username, self.password),
                "params": {"key": self.client_id},
            })

        errors: list[str] = []
        for attempt in attempts:
            url = f"{attempt['base'].rstrip('/')}{attempt['path']}"
            print(f"[SHA DEBUG] basic auth attempt GET {url}?key={attempt['params'].get('key')}")
            try:
                response = httpx.get(
                    url,
                    params=attempt["params"],
                    auth=attempt["auth"],
                    timeout=self.timeout,
                    verify=self.verify_ssl,
                    follow_redirects=True,
                )
                print(f"[SHA DEBUG] basic auth status={response.status_code} body={response.text[:120]!r}")
                if response.status_code == 404:
                    errors.append(f"{url} -> 404")
                    continue
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").lower()
                text = (response.text or "").strip()
                if "application/json" in content_type or text.startswith("{"):
                    data = response.json() if response.content else {}
                    if isinstance(data, str):
                        token = data
                    else:
                        token, _ = self._extract_token(data)
                else:
                    if not text or text.count(".") < 2:
                        raise ShaHieRequestError(
                            f"Unexpected token response from {url}: {text[:120]}"
                        )
                    token = text
                print(f"[SHA DEBUG] basic auth success token_len={len(token)}")
                return token
            except httpx.HTTPError as exc:
                print(f"[SHA DEBUG] basic auth HTTP error: {exc}")
                errors.append(f"{url} -> {exc}")
                continue

        raise ShaHieRequestError(
            "Failed to authenticate with SHA HIE (basic). Tried: " + "; ".join(errors)
        )

    def _authorized_get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        include_facility: bool = False,
    ) -> httpx.Response:

        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if include_facility:
            headers.update(self._facility_headers())
        response = httpx.get(
            url,
            params=params,
            headers=headers,
            timeout=self.timeout,
            verify=self.verify_ssl,
            follow_redirects=True,
        )
        if response.status_code == 401:
            token = self._get_access_token(force_refresh=True)
            headers["Authorization"] = f"Bearer {token}"
            response = httpx.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
                follow_redirects=True,
            )
        return response

    def _eclaims_get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        """GET on ILM middleware with facility headers (eligibility / benefits)."""
        clean = path if path.startswith("/") else f"/{path}"
        url = f"{self.eclaims_base_url.rstrip('/')}{clean}"
        return self._authorized_get(url, params, include_facility=True)

    def search_icd11(self, query: str, *, limit: int = 25) -> dict[str, Any]:
        """
        DHA Terminology Service ICD-11 search.

        Docs (ILM middleware):
          GET {terminology_base}/clinical/concepts?owner=WHO&source=ICD-11&search=...
          GET {terminology_base}/clinical/ocl/orgs/WHO/sources/ICD-11/concepts?q=...
        Auth: Bearer JWT from /v1/hie-auth on SHA_HIE_BASE_URL.
        """
        clean = (query or "").strip()
        if not clean:
            raise ValueError("query is required.")

        term_base = self.terminology_base_url
        owner = self.icd11_owner
        source = self.icd11_source
        primary = self.icd11_search_path or "/clinical/concepts"

        # (path, params) attempts — prefer working ILM middleware routes first.
        attempts: list[tuple[str, str, dict[str, Any]]] = []

        def add_attempt(base: str, path: str, params: dict[str, Any]) -> None:
            key = (base, path, tuple(sorted(params.items())))
            if any(
                (a[0], a[1], tuple(sorted(a[2].items()))) == key for a in attempts
            ):
                return
            attempts.append((base, path, params))

        # Primary: hierarchical concepts (documented terminology API)
        if "concepts" in primary and "ocl" not in primary:
            add_attempt(
                term_base,
                primary,
                {
                    "owner": owner,
                    "source": source,
                    "search": clean,
                    "limit": limit,
                },
            )
        else:
            add_attempt(term_base, primary, {"q": clean, "limit": limit})
            add_attempt(term_base, primary, {"search": clean, "limit": limit})

        add_attempt(
            term_base,
            "/clinical/concepts",
            {
                "owner": owner,
                "source": source,
                "search": clean,
                "limit": limit,
            },
        )
        add_attempt(
            term_base,
            f"/clinical/ocl/orgs/{owner}/sources/{source}/concepts",
            {"q": clean},
        )
        add_attempt(
            term_base,
            "/clinical/icd11/search",
            {"q": clean, "limit": limit},
        )
        # Legacy hosts (often 404 on uat.dha.go.ke — kept as last resort)
        for legacy_base in (self.base_url,):
            add_attempt(
                legacy_base,
                "/clinical/concepts",
                {
                    "owner": owner,
                    "source": source,
                    "search": clean,
                    "limit": limit,
                },
            )
            add_attempt(
                legacy_base,
                "/clinical/icd11/search",
                {"q": clean, "limit": limit},
            )

        last_error: Exception | None = None
        last_raw: Any = None
        for base, path, params in attempts:
            url = f"{base.rstrip('/')}{path}"
            try:
                print(f"[SHA DEBUG] icd11-search GET {url} params={params}")
                response = self._authorized_get(url, params)
                print(
                    f"[SHA DEBUG] icd11-search status={response.status_code} "
                    f"body={response.text[:300]!r}"
                )
                if response.status_code in (502, 522, 526):
                    last_error = ShaHieRequestError(
                        f"{url} -> {response.status_code}"
                    )
                    continue
                if response.status_code == 404:
                    last_error = ShaHieRequestError(f"{url} -> 404")
                    continue
                response.raise_for_status()
                raw = _safe_json(response)
                last_raw = raw
                results = _normalize_dha_icd11_results(raw)
                # Empty list from a live endpoint is valid — try next only if
                # we got nothing and more specific routes remain.
                if not results and path.endswith("/icd11/search"):
                    last_error = ShaHieRequestError(
                        f"{url} returned no ICD-11 matches"
                    )
                    continue
                return {
                    "query": clean,
                    "path": path,
                    "base": base,
                    "results": results,
                    "raw": raw if isinstance(raw, dict) else {"value": raw},
                }
            except (httpx.HTTPError, ShaHieRequestError, ValueError) as exc:
                last_error = exc
                continue

        raise ShaHieRequestError(
            f"DHA ICD-11 search failed: {last_error}"
            + (f" last={last_raw!r}" if last_raw is not None else "")
        )

    def search_hpt(self, query: str, *, limit: int = 25) -> dict[str, Any]:
        """
        DHA Terminology search for Health Products & Technologies (medications).

        GET {terminology_base}/clinical/concepts?owner=MOH-PPB&source=HPT&search=...

        Prefer GE* codes (generic products, e.g. GE10002 Metformin 500 mg Oral Tablet)
        for ePrescription ``generic_concept_code``. PH* are registered packs; AC* are
        active components.
        """
        clean = (query or "").strip()
        if not clean:
            raise ValueError("query is required.")

        term_base = self.terminology_base_url
        owner = self.hpt_owner
        source = self.hpt_source
        attempts: list[tuple[str, str, dict[str, Any]]] = [
            (
                term_base,
                "/clinical/concepts",
                {
                    "owner": owner,
                    "source": source,
                    "search": clean,
                    "limit": limit,
                },
            ),
            (
                term_base,
                f"/clinical/ocl/orgs/{owner}/sources/{source}/concepts",
                {"q": clean},
            ),
        ]

        last_error: Exception | None = None
        last_raw: Any = None
        for base, path, params in attempts:
            url = f"{base.rstrip('/')}{path}"
            try:
                print(f"[SHA DEBUG] hpt-search GET {url} params={params}")
                response = self._authorized_get(url, params)
                print(
                    f"[SHA DEBUG] hpt-search status={response.status_code} "
                    f"body={response.text[:300]!r}"
                )
                if response.status_code in (404, 502, 522, 526):
                    last_error = ShaHieRequestError(
                        f"{url} -> {response.status_code}"
                    )
                    continue
                response.raise_for_status()
                raw = _safe_json(response)
                last_raw = raw
                results = _normalize_dha_hpt_results(raw)
                return {
                    "query": clean,
                    "path": path,
                    "base": base,
                    "owner": owner,
                    "source": source,
                    "results": results,
                    "raw": raw if isinstance(raw, dict) else {"value": raw},
                }
            except (httpx.HTTPError, ShaHieRequestError, ValueError) as exc:
                last_error = exc
                continue

        raise ShaHieRequestError(
            f"DHA HPT search failed: {last_error}"
            + (f" last={last_raw!r}" if last_raw is not None else "")
        )

    def search_concepts(
        self,
        query: str,
        *,
        owner: str,
        source: str,
        limit: int = 25,
        dedicated_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Generic AfyaConnect Terminology Service concept search (OCL-backed).

        Docs: https://afyaconnect.dha.go.ke/docs/terminologyService/gettingStarted/intro
              https://hie-docs.dha.go.ke/docs/terminologyService/gettingStarted/intro

          GET /clinical/concepts?owner=…&source=…&search=…&limit=…
          GET /clinical/ocl/orgs/{owner}/sources/{source}/concepts?q=…
        """
        clean = (query or "").strip()
        if not clean:
            raise ValueError("query is required.")
        owner = (owner or "").strip()
        source = (source or "").strip()
        if not owner or not source:
            raise ValueError("owner and source are required.")

        term_base = self.terminology_base_url
        attempts: list[tuple[str, str, dict[str, Any]]] = []
        if dedicated_path:
            path = dedicated_path if dedicated_path.startswith("/") else f"/{dedicated_path}"
            attempts.append((term_base, path, {"q": clean, "limit": limit}))
            attempts.append((term_base, path, {"search": clean, "limit": limit}))
        attempts.extend([
            (
                term_base,
                "/clinical/concepts",
                {
                    "owner": owner,
                    "source": source,
                    "search": clean,
                    "limit": limit,
                },
            ),
            (
                term_base,
                f"/clinical/ocl/orgs/{owner}/sources/{source}/concepts",
                {"q": clean, "limit": limit},
            ),
        ])

        last_error: Exception | None = None
        last_raw: Any = None
        for base, path, params in attempts:
            url = f"{base.rstrip('/')}{path}"
            try:
                print(
                    f"[SHA DEBUG] concepts-search GET {url} "
                    f"owner={owner} source={source} params={params}"
                )
                response = self._authorized_get(url, params)
                print(
                    f"[SHA DEBUG] concepts-search status={response.status_code} "
                    f"body={response.text[:300]!r}"
                )
                if response.status_code in (404, 502, 522, 526):
                    last_error = ShaHieRequestError(
                        f"{url} -> {response.status_code}"
                    )
                    continue
                response.raise_for_status()
                raw = _safe_json(response)
                last_raw = raw
                results = _normalize_dha_concept_results(
                    raw, system_hint=f"{owner}/{source}"
                )
                return {
                    "query": clean,
                    "path": path,
                    "base": base,
                    "owner": owner,
                    "source": source,
                    "results": results,
                    "raw": raw if isinstance(raw, dict) else {"value": raw},
                }
            except (httpx.HTTPError, ShaHieRequestError, ValueError) as exc:
                last_error = exc
                continue

        raise ShaHieRequestError(
            f"DHA terminology search failed ({owner}/{source}): {last_error}"
            + (f" last={last_raw!r}" if last_raw is not None else "")
        )

    def search_loinc(self, query: str, *, limit: int = 25) -> dict[str, Any]:
        """
        LOINC lab / clinical observation codes via Terminology Service.

          GET /clinical/loinc/search?q=…
          GET /clinical/concepts?owner=Regenstrief&source=LOINC&search=…
        """
        return self.search_concepts(
            query,
            owner=self.loinc_owner,
            source=self.loinc_source,
            limit=limit,
            dedicated_path=self.loinc_search_path,
        )

    def search_ichi(self, query: str, *, limit: int = 25) -> dict[str, Any]:
        """
        ICHI procedure / intervention codes via Terminology Service.

          GET /clinical/concepts?owner=WHO&source=ICHI&search=…
          GET /terminology/v1/ichi?search=…  (legacy AfyaLink)
        """
        clean = (query or "").strip()
        if not clean:
            raise ValueError("query is required.")

        dedicated = self.ichi_search_path
        use_dedicated = dedicated and dedicated.rstrip("/") not in (
            "/clinical/concepts",
            "clinical/concepts",
        )
        try:
            return self.search_concepts(
                clean,
                owner=self.ichi_owner,
                source=self.ichi_source,
                limit=limit,
                dedicated_path=dedicated if use_dedicated else None,
            )
        except ShaHieRequestError:
            # Legacy ICHI search used by older AfyaLink / Client Portal docs
            last_error: Exception | None = None
            for base in (self.terminology_base_url, self.base_url):
                for path in ("/terminology/v1/ichi", "/clinical/ichi/search"):
                    url = f"{base.rstrip('/')}{path}"
                    try:
                        print(f"[SHA DEBUG] ichi-legacy GET {url} search={clean!r}")
                        response = self._authorized_get(
                            url, {"search": clean, "limit": limit}
                        )
                        print(
                            f"[SHA DEBUG] ichi-legacy status={response.status_code} "
                            f"body={response.text[:300]!r}"
                        )
                        if response.status_code in (404, 502, 522, 526):
                            last_error = ShaHieRequestError(
                                f"{url} -> {response.status_code}"
                            )
                            continue
                        response.raise_for_status()
                        raw = _safe_json(response)
                        results = _normalize_dha_concept_results(
                            raw, system_hint="WHO/ICHI"
                        )
                        return {
                            "query": clean,
                            "path": path,
                            "base": base,
                            "owner": self.ichi_owner,
                            "source": self.ichi_source,
                            "results": results,
                            "raw": raw if isinstance(raw, dict) else {"value": raw},
                        }
                    except (httpx.HTTPError, ShaHieRequestError, ValueError) as exc:
                        last_error = exc
                        continue
            raise ShaHieRequestError(f"DHA ICHI search failed: {last_error}")

    def search_facility_by_code(
        self,
        facility_code: str,
        *,
        identifier_type: str | None = None,
    ) -> ShaFacilityLookupResult:
        """
        AfyaConnect Facility Registry search.

        Docs: https://afyaconnect.dha.go.ke/hie-api/hieRegistry/facility-registry
              https://hie-docs.dha.go.ke/registries/facility-registry

          GET {middleware}/facilities/search
              ?identifier={code}&identifier-type={fr-code|mfl|…}

        Falls back to legacy AfyaLink /v2/facility-search if the new route is missing.
        """
        clean_code = (facility_code or "").strip()
        if not clean_code:
            raise ValueError("facility_code is required.")

        id_type = (identifier_type or self.facility_id_type_default or "fr-code").strip()
        path = self.facility_search_path or "/facilities/search"
        if not path.startswith("/"):
            path = f"/{path}"

        # Prefer AfyaConnect registry on middleware host
        attempts: list[tuple[str, dict[str, str]]] = [
            (
                f"{self.facility_registry_base_url.rstrip('/')}{path}",
                {"identifier": clean_code, "identifier-type": id_type},
            ),
        ]
        # Legacy AfyaLink paths (uat.dha.go.ke)
        for legacy_path in ("/v2/facility-search", "/v1/facility-search"):
            attempts.append(
                (
                    f"{self.base_url.rstrip('/')}{legacy_path}",
                    {"facility_code": clean_code},
                )
            )

        last_error: Exception | None = None
        last_raw: dict[str, Any] | None = None

        for url, params in attempts:
            print(f"[SHA DEBUG] facility-search GET {url} params={params}")
            try:
                response = self._authorized_get(url, params)
                print(
                    f"[SHA DEBUG] facility-search status={response.status_code} "
                    f"body={response.text[:400]!r}"
                )
                if response.status_code in (502, 522, 526):
                    last_error = ShaHieRequestError(
                        f"{url} -> {response.status_code}"
                    )
                    continue

                raw = _safe_json(response)
                last_raw = raw if isinstance(raw, dict) else {"value": raw}

                if response.status_code == 404 and _is_route_not_found(raw, response.text):
                    last_error = ShaHieRequestError(f"{url} -> 404 Route Not Found")
                    continue

                if response.status_code == 404:
                    return ShaFacilityLookupResult(
                        facility_code=clean_code,
                        found=False,
                        raw=last_raw,
                    )

                response.raise_for_status()
                data = last_raw if isinstance(last_raw, dict) else {"value": last_raw}
                return ShaFacilityLookupResult(
                    facility_code=clean_code,
                    found=_response_has_facility(data),
                    raw=data,
                )
            except httpx.HTTPError as exc:
                last_error = ShaHieRequestError(
                    f"SHA facility-search request failed: {exc}"
                )
                continue

        if last_raw is not None:
            return ShaFacilityLookupResult(
                facility_code=clean_code,
                found=False,
                raw=last_raw,
            )
        raise ShaHieRequestError(
            f"SHA facility-search request failed: {last_error}"
        )

    def search_practitioners(
        self,
        identification_number: str,
        *,
        identification_type: str = "registration_number",
        regulator: str | None = None,
    ) -> ShaPractitionerLookupResult:
        """
        AfyaConnect Health Worker Registry practitioner search.

        Docs: https://hie-docs.dha.go.ke/registries/health-worker-registry#get-practitioners-record

          GET {middleware}/professionals
              ?identification_number=…&identification_type=…[&regulator=…]
        """
        clean_id = (identification_number or "").strip()
        if not clean_id:
            raise ValueError("identification_number is required.")
        id_type = (identification_type or "registration_number").strip() or "registration_number"
        params: dict[str, Any] = {
            "identification_number": clean_id,
            "identification_type": id_type,
        }
        if regulator:
            params["regulator"] = str(regulator).strip()

        path = self.practitioner_search_path or "/professionals"
        if not path.startswith("/"):
            path = f"/{path}"

        url = f"{self.eclaims_base_url.rstrip('/')}{path}"
        print(f"[SHA DEBUG] practitioner-search GET {url} params={params}")
        try:
            response = self._authorized_get(url, params, include_facility=True)
            print(
                f"[SHA DEBUG] practitioner-search status={response.status_code} "
                f"body={response.text[:400]!r}"
            )
            raw = _safe_json(response)
            last_raw = raw if isinstance(raw, dict) else {"value": raw}
            if response.status_code == 404:
                return ShaPractitionerLookupResult(
                    identification_number=clean_id, found=False, raw=last_raw
                )
            response.raise_for_status()
            data = last_raw if isinstance(last_raw, dict) else {"value": last_raw}
            return ShaPractitionerLookupResult(
                identification_number=clean_id,
                found=_response_has_practitioner(data),
                raw=data,
            )
        except httpx.HTTPError as exc:
            raise ShaHieRequestError(
                f"SHA practitioner-search request failed: {exc}"
            ) from exc

    def get_facility_bed_occupancy(
        self, facility_code: str | None = None
    ) -> dict[str, Any]:
        """
        AfyaConnect Get facility bed occupancy (GET /facilities/{facilityCode}/beds/occupancy).
        https://hie-docs.dha.go.ke/eclaims/eligibility#get-facility-bed-occupancy
        """
        code = (
            facility_code
            or getattr(settings, "SHA_HIE_FACILITY_FR_CODE", "")
            or getattr(settings, "SHA_HIE_FACILITY_CODE", "")
        )
        code = str(code).strip()
        if not code:
            code = "15627"


        url = f"{self.eclaims_base_url.rstrip('/')}/facilities/{code}/beds/occupancy"
        print(f"[SHA DEBUG] bed-occupancy GET {url}")
        try:
            response = self._authorized_get(url, params=None, include_facility=True)

            print(
                f"[SHA DEBUG] bed-occupancy status={response.status_code} "
                f"body={response.text[:400]!r}"
            )
            response.raise_for_status()
            data = _safe_json(response)
            return data if isinstance(data, dict) else {"value": data}
        except httpx.HTTPError as exc:
            print(f"[SHA WARNING] SHA bed-occupancy request failed: {exc}")
            return {}


    # ------------------------------------------------------------------
    # eClaims / eRx (ILM middleware) + legacy FHIR preauth on UAT host
    # ------------------------------------------------------------------

    def _facility_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        facility_id = (
            getattr(settings, "SHA_HIE_FACILITY_FR_CODE", "") or ""
        ).strip()
        if facility_id:
            headers["X-Facility-Id"] = facility_id
            headers["X-Facility-Id-Type"] = getattr(
                settings, "SHA_HIE_FACILITY_ID_TYPE", "fr-code"
            ) or "fr-code"
        return headers

    def _authorized_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        files: Any = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            **self._facility_headers(),
            **(extra_headers or {}),
        }
        if json_body is not None and files is None and data is None:
            headers.setdefault("Content-Type", "application/json")

        def _do(auth_token: str) -> httpx.Response:
            headers["Authorization"] = f"Bearer {auth_token}"
            return httpx.request(
                method.upper(),
                url,
                params=params,
                json=json_body,
                data=data,
                files=files,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
                follow_redirects=True,
            )

        response = _do(token)
        if response.status_code == 401:
            response = _do(self._get_access_token(force_refresh=True))
        return response

    def _eclaims_url(self, path: str) -> str:
        return f"{self.eclaims_base_url.rstrip('/')}/{path.lstrip('/')}"

    def search_patients(
        self,
        id_number: str,
        *,
        identification_type: str = "National ID",
    ) -> ShaPatientLookupResult:
        """
        AfyaConnect Patient Search (Client Registry).

        GET {middleware}/patients
            ?identification_number=…&identification_type=…
        """
        clean_id = (id_number or "").strip()
        if not clean_id:
            raise ValueError("id_number is required.")
        id_type = (identification_type or "National ID").strip() or "National ID"
        params = {
            "identification_number": clean_id,
            "identification_type": id_type,
        }
        path = self.patient_search_path or "/patients"
        if not path.startswith("/"):
            path = f"/{path}"

        attempts: list[tuple[str, dict[str, str], bool]] = []
        if self._middleware_usable():
            attempts.append(
                (f"{self.eclaims_base_url.rstrip('/')}{path}", params, True)
            )
        else:
            print(
                "[SHA DEBUG] patient-search: skipping middleware "
                f"(token_source={self._token_source()}; need AfyaConnect OAuth). "
                "Using legacy Client Registry."
            )
        # Legacy AfyaLink client registry
        agent = self.agent_id or self.consumer_key
        if agent:
            attempts.append(
                (
                    f"{self.base_url.rstrip('/')}{self.client_verify_path}",
                    {
                        "identification_type": id_type,
                        "identification_number": clean_id,
                        "agent": agent,
                    },
                    False,
                )
            )
        if not attempts:
            raise ShaHieConfigError(
                "No patient-search endpoint available. Set AfyaConnect "
                "SHA_HIE_CLIENT_ID/SECRET or legacy SHA_HIE_AGENT_ID."
            )

        last_error: Exception | None = None
        last_raw: dict[str, Any] | None = None
        for url, req_params, with_facility in attempts:
            print(f"[SHA DEBUG] patient-search GET {url} params={req_params}")
            try:
                response = self._authorized_get(
                    url, req_params, include_facility=with_facility
                )
                print(
                    f"[SHA DEBUG] patient-search status={response.status_code} "
                    f"body={response.text[:400]!r}"
                )
                if response.status_code in (502, 522, 526):
                    last_error = ShaHieRequestError(
                        f"{url} -> {response.status_code}"
                    )
                    continue
                raw = _safe_json(response)
                if with_facility is False:
                    raw = decrypt_response_pii(raw) if isinstance(raw, dict) else raw
                last_raw = raw if isinstance(raw, dict) else {"value": raw}
                if response.status_code == 404 and _is_route_not_found(
                    raw, response.text
                ):
                    last_error = ShaHieRequestError(f"{url} -> 404 Route Not Found")
                    continue
                if response.status_code == 404:
                    return ShaPatientLookupResult(
                        id_number=clean_id, found=False, raw=last_raw
                    )
                if response.status_code in (401, 403):
                    # Middleware often rejects AfyaLink tokens / wrong FR — try next host
                    last_error = ShaHieRequestError(
                        f"Patient search unauthorized ({response.status_code}) at {url}. "
                        "Middleware needs AfyaConnect OAuth client credentials "
                        "(SHA_HIE_CLIENT_ID/SECRET). Falling back to legacy registry if available."
                    )
                    print(f"[SHA DEBUG] {last_error}")
                    continue
                response.raise_for_status()
                data = last_raw if isinstance(last_raw, dict) else {"value": last_raw}
                return ShaPatientLookupResult(
                    id_number=clean_id,
                    found=_response_has_patient(data),
                    raw=data,
                )
            except httpx.HTTPError as exc:
                last_error = ShaHieRequestError(f"Patient search failed: {exc}")
                continue
        if last_raw is not None and last_error is None:
            return ShaPatientLookupResult(
                id_number=clean_id, found=False, raw=last_raw
            )
        # Prefer surfacing auth guidance when every attempt was 401/403
        raise ShaHieRequestError(f"Patient search failed: {last_error}")

    def get_patient_by_id_number(
        self,
        id_number: str,
        *,
        identification_type: str = "National ID",
    ) -> ShaPatientLookupResult:
        """
        AfyaConnect SHA eligibility check.

        Docs: https://hie-docs.dha.go.ke/eclaims/eligibility
              https://hie-docs.dha.go.ke/docs/claims/process/eligibility/eligibilityCheck

          GET {middleware}/patients/eligibility
              ?identification_number=…&identification_type=…
          Headers: X-Facility-Id, X-Facility-Id-Type

        Prefer identification_type=ClientRegistry ID when CR ID is known.
        """
        clean_id = (id_number or "").strip()
        if not clean_id:
            raise ValueError("id_number is required.")
        id_type = (identification_type or "National ID").strip() or "National ID"
        params = {
            "identification_type": id_type,
            "identification_number": clean_id,
        }
        path = self.eligibility_path or "/patients/eligibility"
        if not path.startswith("/"):
            path = f"/{path}"

        attempts: list[tuple[str, dict[str, str], bool]] = []
        if self._middleware_usable():
            attempts.append(
                (f"{self.eclaims_base_url.rstrip('/')}{path}", params, True)
            )
        else:
            print(
                "[SHA DEBUG] eligibility: skipping middleware "
                f"(token_source={self._token_source()}; need AfyaConnect OAuth). "
                "Using legacy /v2/eligibility."
            )
        # Legacy AfyaLink
        for legacy in ("/v2/eligibility", "/v1/eligibility"):
            attempts.append(
                (
                    f"{self.base_url.rstrip('/')}{legacy}",
                    params,
                    False,
                )
            )

        print(
            f"[SHA DEBUG] eligibility lookup id={clean_id} type={id_type}"
        )
        last_error: Exception | None = None
        last_raw: dict[str, Any] | None = None
        for url, req_params, with_facility in attempts:
            try:
                print(f"[SHA DEBUG] eligibility GET {url}")
                response = self._authorized_get(
                    url, req_params, include_facility=with_facility
                )
                print(
                    f"[SHA DEBUG] eligibility status={response.status_code} "
                    f"body={response.text[:300]!r}"
                )
                if response.status_code == 522:
                    raise ShaHieRequestError(
                        f"{url} returned HTTP 522 (Cloudflare: origin timed out). "
                        "Authentication succeeded but the eligibility service did not respond. "
                        "Contact DHA support or retry later."
                    )
                if response.status_code in (502, 526):
                    last_error = ShaHieRequestError(
                        f"{url} -> {response.status_code}"
                    )
                    continue
                raw = _safe_json(response)
                last_raw = raw if isinstance(raw, dict) else {"value": raw}
                if response.status_code == 404 and _is_route_not_found(
                    raw, response.text
                ):
                    last_error = ShaHieRequestError(f"{url} -> 404 Route Not Found")
                    continue
                if response.status_code == 404:
                    return ShaPatientLookupResult(
                        id_number=clean_id, found=False, raw=last_raw
                    )
                if response.status_code in (401, 403):
                    last_error = ShaHieRequestError(
                        f"Eligibility unauthorized ({response.status_code}) at {url}. "
                        "Middleware needs AfyaConnect OAuth (SHA_HIE_CLIENT_ID/SECRET) "
                        "and a valid SHA_HIE_FACILITY_FR_CODE. Trying legacy eligibility…"
                    )
                    print(f"[SHA DEBUG] {last_error}")
                    continue
                response.raise_for_status()
                data = last_raw if isinstance(last_raw, dict) else {"value": last_raw}
                found = _response_has_patient(data) or _eligibility_payload_present(data)
                print(f"[SHA DEBUG] eligibility parsed found={found}")
                return ShaPatientLookupResult(
                    id_number=clean_id,
                    found=found,
                    raw=data,
                )
            except ShaHieRequestError as exc:
                # Only abort hard failures (e.g. 522); auth errors already continued
                if "522" in str(exc):
                    raise
                last_error = exc
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"[SHA DEBUG] eligibility error: {exc}")
                last_error = exc
                continue
        if last_raw is not None and not last_error:
            return ShaPatientLookupResult(
                id_number=clean_id, found=False, raw=last_raw
            )
        raise ShaHieRequestError(f"SHA eligibility request failed: {last_error}")

    def fetch_client_registry(
        self,
        id_number: str,
        *,
        identification_type: str = "National ID",
    ) -> ShaPatientLookupResult:
        """Patient Search wrapper (middleware /patients, legacy CR fallback)."""
        return self.search_patients(
            id_number, identification_type=identification_type
        )

    def get_patient_sub_benefits(
        self,
        patient_id: str,
        *,
        parent_benefit_code: str | None = None,
    ) -> dict[str, Any]:
        """GET /patients/sub-benefits?patient_id=…"""
        cr = (patient_id or "").strip()
        if not cr:
            raise ValueError("patient_id (CR ID) is required.")
        params: dict[str, Any] = {"patient_id": cr}
        if parent_benefit_code:
            params["parent_benefit_code"] = parent_benefit_code
        path = self.sub_benefits_path or "/patients/sub-benefits"
        url = f"{self.eclaims_base_url.rstrip('/')}{path if path.startswith('/') else '/' + path}"
        print(f"[SHA DEBUG] sub-benefits GET {url} params={params}")
        response = self._authorized_get(url, params, include_facility=True)
        if response.status_code in (401, 403):
            raise ShaHieRequestError(
                f"Sub-benefits forbidden ({response.status_code}). Check facility contract."
            )
        if response.status_code >= 400:
            raise ShaHieRequestError(
                f"Sub-benefits failed ({response.status_code}): {response.text[:300]}"
            )
        raw = _safe_json(response)
        return raw if isinstance(raw, dict) else {"results": raw}

    def get_patient_interventions(
        self,
        patient_id: str,
        *,
        sub_benefit_code: str | None = None,
        access_point: str | None = "OP",
        search: str | None = None,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """GET /patients/benefits/interventions"""
        cr = (patient_id or "").strip()
        if not cr:
            raise ValueError("patient_id (CR ID) is required.")
        params: dict[str, Any] = {"patient_id": cr, "page_size": page_size}
        if sub_benefit_code:
            params["sub_benefit_code"] = sub_benefit_code
        if access_point:
            params["access_point"] = access_point
        if search:
            params["search"] = search
        path = self.interventions_path or "/patients/benefits/interventions"
        url = f"{self.eclaims_base_url.rstrip('/')}{path if path.startswith('/') else '/' + path}"
        print(f"[SHA DEBUG] interventions GET {url} params={params}")
        response = self._authorized_get(url, params, include_facility=True)
        if response.status_code in (401, 403):
            raise ShaHieRequestError(
                f"Interventions forbidden ({response.status_code}). Check facility contract."
            )
        if response.status_code >= 400:
            raise ShaHieRequestError(
                f"Interventions failed ({response.status_code}): {response.text[:300]}"
            )
        raw = _safe_json(response)
        return raw if isinstance(raw, dict) else {"results": raw}

    def get_patient_utilization(
        self,
        patient_id: str,
        *,
        intervention_code: str,
    ) -> Any:
        """GET /patients/benefits/utilization"""
        cr = (patient_id or "").strip()
        code = (intervention_code or "").strip()
        if not cr or not code:
            raise ValueError("patient_id and intervention_code are required.")
        params = {"patient_id": cr, "intervention_code": code}
        path = self.utilization_path or "/patients/benefits/utilization"
        url = f"{self.eclaims_base_url.rstrip('/')}{path if path.startswith('/') else '/' + path}"
        response = self._authorized_get(url, params, include_facility=True)
        if response.status_code >= 400:
            raise ShaHieRequestError(
                f"Utilization failed ({response.status_code}): {response.text[:300]}"
            )
        return _safe_json(response)

    def get_pomsf_balances(
        self,
        patient_id: str,
        *,
        policy_year: str | None = None,
        principal_member_number: str | None = None,
    ) -> dict[str, Any]:
        """GET /patients/pomsf-balances"""
        cr = (patient_id or "").strip()
        if not cr:
            raise ValueError("patient_id is required.")
        params: dict[str, Any] = {"patient_id": cr}
        if policy_year:
            params["policy_year"] = policy_year
        if principal_member_number:
            params["principal_member_number"] = principal_member_number
        path = self.pomsf_balances_path or "/patients/pomsf-balances"
        url = f"{self.eclaims_base_url.rstrip('/')}{path if path.startswith('/') else '/' + path}"
        response = self._authorized_get(url, params, include_facility=True)
        if response.status_code >= 400:
            raise ShaHieRequestError(
                f"POMSF balances failed ({response.status_code}): {response.text[:300]}"
            )
        raw = _safe_json(response)
        return raw if isinstance(raw, dict) else {"value": raw}

    def get_patient_contacts(self, patient_id: str) -> dict[str, Any]:
        """GET /patients/contacts — masked phones for OTP targeting."""
        self._require_middleware_oauth("patients/contacts")
        cr = (patient_id or "").strip()
        if not cr:
            raise ValueError("patient_id (CR ID) is required.")
        url = self._eclaims_url("/patients/contacts")
        response = self._authorized_request(
            "GET", url, params={"patient_id": cr}
        )
        # Some deployments use identification query shape
        if response.status_code == 404:
            response = self._authorized_request(
                "GET",
                url,
                params={
                    "identification_number": cr,
                    "identification_type": "ClientRegistry ID",
                },
            )
        return self._raise_for_eclaims(response, "patients/contacts")

    def create_biometric_authorization(
        self,
        *,
        patient_id: str,
        agent_national_id: str | None = None,
        work_station_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        POST /claims/authorize — biometrics consent path.

        agent_national_id: Kenyan National ID of the staff operating the
        scanner (Health ID \"biometrics agent\"), typically the logged-in user.
        """
        self._require_middleware_oauth("claims/authorize")
        agent = (agent_national_id or "").strip()
        body: dict[str, Any] = {"patient_id": (patient_id or "").strip()}
        if agent:
            # DHA authorize schema uses agent_id for the biometric agent National ID
            body["agent_id"] = agent
            body["agent_national_id"] = agent
            body["national_id"] = agent
        workstation = (
            (work_station_id or "").strip()
            or (getattr(settings, "SHA_HIE_BIOMETRICS_WORKSTATION_ID", "") or "").strip()
        )
        if workstation:
            body["workStationId"] = workstation
            body["work_station_id"] = workstation
            body["workstationID"] = workstation
        if extra:
            for key, value in extra.items():
                if value in (None, ""):
                    continue
                # Do not let empty client overrides wipe the logged-in agent
                if key in ("agent_id", "agent_national_id", "national_id") and agent:
                    continue
                body[key] = value
        if not body.get("agent_id"):
            raise ValueError(
                "Biometrics agent National ID is required "
                "(logged-in user id_number)."
            )
        url = self._eclaims_url("/claims/authorize")
        response = self._authorized_request("POST", url, json_body=body)
        return self._raise_for_eclaims(response, "claims/authorize")

    def _raise_for_eclaims(self, response: httpx.Response, action: str) -> Any:
        raw = _safe_json(response)
        print(
            f"[SHA DEBUG] {action} status={response.status_code} "
            f"body={str(raw)[:400]!r}"
        )
        if response.status_code >= 400:
            detail = raw
            if isinstance(raw, dict):
                detail = raw.get("message") or raw.get("error") or raw
            detail_s = str(detail)
            if response.status_code == 401 and (
                "not active" in detail_s.lower()
                or "invalid or expired" in detail_s.lower()
                or self._token_source() != "oauth"
            ):
                raise ShaHieConfigError(
                    f"{action} failed (401): middleware rejected the token "
                    f"({detail_s}). This usually means AfyaLink credentials "
                    "are in use. Set SHA_HIE_CLIENT_ID / SHA_HIE_CLIENT_SECRET "
                    "from AfyaConnect (POST /tenants/token), not AfyaLink "
                    "CONSUMER_KEY/SECRET."
                )
            raise ShaHieRequestError(
                f"{action} failed ({response.status_code}): {detail}"
            )
        return raw

    def send_claim_otp(
        self,
        *,
        patient_id: str,
        phone: str | None = None,
        contact_id: str | int | None = None,
        intervention_codes: list[str] | None = None,
    ) -> dict[str, Any]:
        """POST /claims/otp — request OTP for visit consent (before start visit)."""
        self._require_middleware_oauth("claims/otp")
        body: dict[str, Any] = {"patient_id": (patient_id or "").strip()}
        if phone:
            body["phone"] = phone
        if contact_id not in (None, ""):
            body["contact_id"] = contact_id
            body["beneficiary_contact_id"] = contact_id
        if intervention_codes:
            body["intervention_codes"] = list(intervention_codes)
        url = self._eclaims_url("/claims/otp")
        response = self._authorized_request("POST", url, json_body=body)
        return self._raise_for_eclaims(response, "claims/otp")

    def create_virtual_claim(
        self,
        *,
        patient_id: str,
        service_type: str,
        intervention_codes: list[str],
        otp: str | None = None,
        auth_guid: str | None = None,
        practitioner_identification_type: str | None = None,
        practitioner_identification_number: str | None = None,
        practitioner_regulation_body: str | None = None,
    ) -> dict[str, Any]:
        """POST /claims/visit — start visit / create virtual claim (OTP or biometrics)."""
        self._require_middleware_oauth("claims/visit")
        body: dict[str, Any] = {
            "patient_id": (patient_id or "").strip(),
            "service_type": (service_type or "OUTPATIENT").strip().upper(),
            "intervention_codes": list(intervention_codes or []),
        }
        if auth_guid:
            body["auth_guid"] = (auth_guid or "").strip()
        elif otp:
            body["otp"] = (otp or "").strip()
        if (
            practitioner_identification_number
            and practitioner_identification_type
            and practitioner_regulation_body
        ):
            body["practitioner_identification_type"] = practitioner_identification_type
            body["practitioner_identification_number"] = practitioner_identification_number
            body["practitioner_regulation_body"] = practitioner_regulation_body
        url = self._eclaims_url("/claims/visit")
        response = self._authorized_request("POST", url, json_body=body)
        return self._raise_for_eclaims(response, "claims/visit")

    def submit_virtual_claim(
        self,
        *,
        consent_token: str,
        otp: str | None = None,
        invoice_number: str | None = None,
        notes: str | None = None,
        discharge_reason: str | None = None,
    ) -> dict[str, Any]:
        """POST /claims/submit — dispatch virtual claim to SHA."""
        body: dict[str, Any] = {"consent_token": (consent_token or "").strip()}
        if otp:
            body["otp"] = otp.strip()
        if invoice_number:
            body["invoice_number"] = invoice_number
        if notes:
            body["notes"] = notes
        if discharge_reason:
            body["discharge_reason"] = discharge_reason
        url = self._eclaims_url("/claims/submit")
        response = self._authorized_request("POST", url, json_body=body)
        return self._raise_for_eclaims(response, "claims/submit")

    def close_virtual_claim(
        self,
        *,
        consent_token: str,
        cancel_reason_type: str,
        cancel_reason_text: str,
    ) -> dict[str, Any]:
        """POST /claims/close"""
        body = {
            "consent_token": (consent_token or "").strip(),
            "cancel_reason_type": cancel_reason_type,
            "cancel_reason_text": cancel_reason_text,
        }
        url = self._eclaims_url("/claims/close")
        response = self._authorized_request("POST", url, json_body=body)
        return self._raise_for_eclaims(response, "claims/close")

    def get_claim_status(self, claim_id: str) -> dict[str, Any]:
        """GET /v1/shr-med/claim-status?claim_id=… (legacy SHR host)."""
        url = f"{self.base_url.rstrip('/')}/v1/shr-med/claim-status"
        response = self._authorized_request(
            "GET", url, params={"claim_id": str(claim_id)}
        )
        return self._raise_for_eclaims(response, "shr-med/claim-status")

    def submit_fhir_preauth_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
        """POST /v1/shr-med/bundle — FHIR R4 preauthorization bundle."""
        url = f"{self.base_url.rstrip('/')}/v1/shr-med/bundle"
        response = self._authorized_request("POST", url, json_body=bundle)
        return self._raise_for_eclaims(response, "shr-med/bundle")

    def create_erx_prescription(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /prescriptions — national eRx create."""
        url = self._eclaims_url("/prescriptions")
        response = self._authorized_request("POST", url, json_body=payload)
        return self._raise_for_eclaims(response, "prescriptions")

    def create_erx_dispense(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /prescriptions/dispense"""
        url = self._eclaims_url("/prescriptions/dispense")
        response = self._authorized_request("POST", url, json_body=payload)
        return self._raise_for_eclaims(response, "prescriptions/dispense")

    def create_preauth(self, form_fields: dict[str, Any]) -> dict[str, Any]:
        """POST /preauths — multipart preauthorization (normal / surgical / …)."""
        url = self._eclaims_url("/preauths")
        # httpx multipart: pass strings in data=
        data = {k: ("" if v is None else str(v)) for k, v in form_fields.items()}
        response = self._authorized_request("POST", url, data=data)
        return self._raise_for_eclaims(response, "preauths")

    def submit_clinical_fhir_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
        """
        POST clinical FHIR document Bundle (Composition) to Kenya HIE.

        Tries configurable path then known AfyaLink/HIE alternatives:
        POST /clinical/fhir/bundle (changelog) and legacy SHR hosts.
        """
        path = (
            getattr(settings, "SHA_HIE_CLINICAL_FHIR_BUNDLE_PATH", "")
            or "/clinical/fhir/bundle"
        )
        errors: list[str] = []
        candidates = [
            path,
            "/clinical/fhir/bundle",
            "/api/v1/clinical/fhir/bundle",
            "/v1/shr/bundle",
            "/v1/shr-med/clinical-bundle",
        ]
        seen: set[str] = set()
        for candidate in candidates:
            candidate = (candidate or "").strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            if candidate.startswith("http"):
                url = candidate
            elif candidate.startswith("/"):
                # Prefer terminology/middleware host for /clinical/* routes
                if candidate.startswith("/clinical"):
                    base = self.terminology_base_url or self.base_url
                else:
                    base = self.base_url
                url = f"{base.rstrip('/')}{candidate}"
            else:
                url = f"{self.base_url.rstrip('/')}/{candidate}"
            try:
                response = self._authorized_request("POST", url, json_body=bundle)
                if response.status_code < 400:
                    try:
                        return response.json() if response.content else {"ok": True}
                    except Exception:
                        return {"ok": True, "status_code": response.status_code}
                errors.append(f"{candidate} → HTTP {response.status_code}")
            except ShaHieRequestError as exc:
                errors.append(f"{candidate}: {exc}")
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
        raise ShaHieRequestError(
            "Clinical FHIR bundle submit failed. " + "; ".join(errors[:4])
        )

    def sync_shared_encounter(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        POST shared encounter / clinical summary sync to SHR.

        Board illustrative path: POST /api/v1/encounter/sync
        Also tries FHIR clinical bundle-adjacent paths used in AfyaLink docs.
        """
        path = (
            getattr(settings, "SHA_HIE_ENCOUNTER_SYNC_PATH", "")
            or "/api/v1/encounter/sync"
        )
        errors: list[str] = []
        candidates = [
            path,
            "/api/v1/encounter/sync",
            "/v1/encounter/sync",
            "/encounter/sync",
            "/clinical/encounter/sync",
        ]
        seen: set[str] = set()
        for candidate in candidates:
            candidate = (candidate or "").strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            if candidate.startswith("http"):
                url = candidate
            else:
                base = self.base_url
                if candidate.startswith("/clinical"):
                    base = self.terminology_base_url or self.base_url
                url = f"{base.rstrip('/')}{candidate if candidate.startswith('/') else '/' + candidate}"
            try:
                response = self._authorized_request("POST", url, json_body=payload)
                if response.status_code < 400:
                    try:
                        return response.json() if response.content else {"ok": True}
                    except Exception:
                        return {"ok": True, "status_code": response.status_code}
                errors.append(f"{candidate} → HTTP {response.status_code}")
            except ShaHieRequestError as exc:
                errors.append(f"{candidate}: {exc}")
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
        raise ShaHieRequestError(
            "Shared encounter sync failed. " + "; ".join(errors[:4])
        )


def decrypt_sha_pii_string(pii_str: str) -> dict[str, Any]:
    """
    Decrypts DHA/AfyaLink Client Registry _pii payload using SHA_HIE_PRIVATE_KEY.
    """
    if not pii_str or not isinstance(pii_str, str):
        return {}

    private_key_b64 = getattr(settings, "SHA_HIE_PRIVATE_KEY", "") or os.getenv("SHA_HIE_PRIVATE_KEY", "")
    private_key_b64 = (private_key_b64 or "").strip()

    if not private_key_b64 or len(private_key_b64) < 500:
        # Try to read directly from .env file inside BASE_DIR
        try:
            env_path = os.path.join(settings.BASE_DIR, ".env")
            if os.path.exists(env_path):
                key_lines = []
                capture = False
                with open(env_path, "r") as f:
                    for raw_line in f:
                        line = raw_line.rstrip("\n").rstrip("\r")
                        if line.startswith("SHA_HIE_PRIVATE_KEY="):
                            capture = True
                            val = line.split("=", 1)[1]
                            if val.startswith('"'):
                                val = val[1:]
                            key_lines.append(val)
                            continue
                        if capture:
                            stripped = line.strip()
                            if not stripped:
                                break
                            if "=" in stripped and not stripped.endswith("=="):
                                break
                            if stripped.endswith('"'):
                                stripped = stripped[:-1]
                            key_lines.append(stripped)
                if key_lines:
                    private_key_b64 = "".join(key_lines)
                    print("[SHA DEBUG] Successfully loaded multiline private key directly from .env")
        except Exception as e:
            print(f"[SHA DEBUG] Direct .env read failed: {e}")

    private_key_b64 = (private_key_b64 or "").strip()
    if not private_key_b64:
        print("[SHA DEBUG] SHA_HIE_PRIVATE_KEY is not set or empty. Skipping decryption.")
        return {}

    try:
        # 1. Load the private key
        clean_key = re.sub(r'\s+', '', private_key_b64)
        pem_lines = [clean_key[i:i+64] for i in range(0, len(clean_key), 64)]
        pem_str = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(pem_lines) + "\n-----END PRIVATE KEY-----"
        private_key = serialization.load_pem_private_key(pem_str.encode(), password=None)

        # 2. Base64 decode to get colon-separated ASCII string
        raw_bytes = base64.b64decode(pii_str)
        decoded_ascii = raw_bytes.decode('utf-8')
        parts = decoded_ascii.split(":")
        if len(parts) < 3:
            print(f"[SHA DEBUG] Invalid _pii structure: {len(parts)} parts found.")
            return {}

        # 3. RSA decrypt Part[0] (AES Key B64) and Part[1] (IV B64) using OAEP-SHA1
        aes_key_b64 = private_key.decrypt(
            base64.b64decode(parts[0]),
            asym_padding.OAEP(mgf=asym_padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)
        )
        iv_b64 = private_key.decrypt(
            base64.b64decode(parts[1]),
            asym_padding.OAEP(mgf=asym_padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)
        )

        # 4. Base64 decode raw key and IV bytes
        aes_key_raw = base64.b64decode(aes_key_b64)
        iv_raw = base64.b64decode(iv_b64)

        # 5. AES CBC decrypt Part[2] (ciphertext)
        ct_raw = base64.b64decode(parts[2])
        cipher = Cipher(algorithms.AES(aes_key_raw), modes.CBC(iv_raw))
        dec = cipher.decryptor()
        plaintext_padded = dec.update(ct_raw) + dec.finalize()

        # 6. Unpad PKCS7
        pad_len = plaintext_padded[-1]
        if 1 <= pad_len <= 16 and plaintext_padded[-pad_len:] == bytes([pad_len]) * pad_len:
            plaintext = plaintext_padded[:-pad_len]
        else:
            plaintext = plaintext_padded

        return json.loads(plaintext.decode('utf-8'))
    except Exception as exc:
        print(f"[SHA DEBUG] Decryption of _pii failed: {exc}")
        return {}


def decrypt_response_pii(data: Any) -> Any:
    """
    Recursively scans response dict/list structures to find and decrypt '_pii' keys.
    When a '_pii' key is found, it is decrypted and its contents are merged into the dict.
    """
    if isinstance(data, dict):
        if "_pii" in data and isinstance(data["_pii"], str):
            decrypted = decrypt_sha_pii_string(data["_pii"])
            if decrypted:
                # Merge decrypted keys into this dict, keep existing keys
                for k, v in decrypted.items():
                    if k not in data or data[k] in (None, "", [], {}):
                        data[k] = v
        # Process other keys/nested structures in the dict
        for k, v in data.items():
            if k != "_pii":
                data[k] = decrypt_response_pii(v)
    elif isinstance(data, list):
        for i in range(len(data)):
            data[i] = decrypt_response_pii(data[i])
    return data


def _response_has_patient(data: Any) -> bool:
    if not isinstance(data, dict):
        return bool(data)
    message = data.get("message")
    if isinstance(message, dict):
        if message.get("id") or message.get("full_name") or "eligible" in message:
            return True
        results = message.get("result") or message.get("results")
        if isinstance(results, list):
            return len(results) > 0
        total = message.get("total")
        if total is not None:
            try:
                return int(total) > 0
            except (TypeError, ValueError):
                pass
    return bool(
        data.get("found")
        or data.get("exists")
        or data.get("verified")
        or data.get("data")
        or data.get("patient")
    )


def _eligibility_payload_present(data: Any) -> bool:
    """True when middleware eligibility response has identity / scheme payload."""
    if not isinstance(data, dict):
        return False
    if data.get("memberCrNumber") or data.get("fullName") or data.get("schemes"):
        return True
    if data.get("requestIdNumber") or data.get("statusCode") is not None:
        return True
    return False


def _extract_schemes(raw: dict[str, Any]) -> list[dict[str, Any]]:
    schemes = raw.get("schemes")
    if isinstance(schemes, list):
        out = []
        for item in schemes:
            if isinstance(item, dict):
                out.append(item)
            elif isinstance(item, str) and item.strip():
                out.append({"schemeName": item.strip()})
        return out
    for nest in ("data", "result", "message", "patient"):
        node = raw.get(nest)
        if isinstance(node, dict):
            nested = _extract_schemes(node)
            if nested:
                return nested
    return []


def is_pomsf_scheme_name(name: str | None) -> bool:
    """POMSF / TSC / USALAMA — match POMSF as prefix (docs)."""
    n = (name or "").strip().upper()
    if not n:
        return False
    return (
        n.startswith("POMSF")
        or n == "TSC"
        or n.startswith("TSC-")
        or n == "USALAMA"
        or n.startswith("USALAMA")
    )


def consent_method_for_flags(
    *,
    facility_biometrics_enforced: bool | None,
    whitelisted_for_otp: bool | None,
) -> str:
    """Return 'biometrics' or 'otp' based on eligibility flags."""
    if facility_biometrics_enforced and not whitelisted_for_otp:
        return "biometrics"
    return "otp"


def evaluate_eligibility(profile: dict[str, Any], raw: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Derive gate outcome from AfyaConnect eligibility payload.

    Outcomes: not_found | deceased | not_eligible | eligible
    """
    raw = raw if isinstance(raw, dict) else {}
    schemes = profile.get("schemes")
    if not isinstance(schemes, list):
        schemes = _extract_schemes(raw)
    is_alive = profile.get("is_alive")
    if is_alive is None:
        is_alive = raw.get("isAlive")
    if is_alive is False or is_alive in (0, "0", "false", "False"):
        return {
            "outcome": "deceased",
            "eligible": False,
            "schemes": schemes,
            "message": "Patient is recorded as deceased. SHA transactions are blocked.",
        }

    status_desc = str(
        profile.get("eligibility_message")
        or profile.get("status_desc")
        or raw.get("statusDesc")
        or ""
    ).strip()
    status_code = str(
        profile.get("status_code") or raw.get("statusCode") or ""
    ).strip()
    status_l = status_desc.lower()

    has_schemes = bool(schemes)
    explicit_eligible = profile.get("eligible")
    if explicit_eligible in (1, "1", True, "true", "True"):
        return {
            "outcome": "eligible",
            "eligible": True,
            "schemes": schemes,
            "message": status_desc or "Active SHA coverage.",
        }
    if explicit_eligible in (0, "0", False, "false", "False"):
        return {
            "outcome": "not_eligible",
            "eligible": False,
            "schemes": schemes,
            "message": status_desc or "Patient is not currently eligible.",
        }

    if has_schemes:
        return {
            "outcome": "eligible",
            "eligible": True,
            "schemes": schemes,
            "message": status_desc or "Active SHA scheme coverage.",
        }

    if any(
        x in status_l
        for x in ("not eligible", "ineligible", "inactive", "lapsed", "not active")
    ):
        return {
            "outcome": "not_eligible",
            "eligible": False,
            "schemes": schemes,
            "message": status_desc or "Patient is not currently eligible.",
        }

    if status_l in ("eligible", "active", "ok") or status_code in ("00", "0", "200"):
        return {
            "outcome": "eligible",
            "eligible": True,
            "schemes": schemes,
            "message": status_desc or "Eligible.",
        }

    # Found demographics but no clear coverage → treat as not eligible gate
    if profile.get("cr_id") or profile.get("full_name") or profile.get("id_number"):
        return {
            "outcome": "not_eligible",
            "eligible": False,
            "schemes": schemes,
            "message": status_desc
            or "Patient identified but no active SHA scheme returned.",
        }

    return {
        "outcome": "not_found",
        "eligible": False,
        "schemes": [],
        "message": "No matching patient found.",
    }


def normalize_interventions(raw: dict[str, Any] | list | None) -> list[dict[str, Any]]:
    """Flatten interventions list from coverage API."""
    if not raw:
        return []
    results: list[Any] = []
    if isinstance(raw, list):
        results = raw
    elif isinstance(raw, dict):
        results = raw.get("results") or raw.get("data") or raw.get("interventions") or []
        if isinstance(results, dict):
            results = [results]
    out: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        code = (
            item.get("code")
            or item.get("intervention_code")
            or item.get("interventionCode")
            or ""
        )
        out.append(
            {
                "code": str(code).strip(),
                "name": item.get("name")
                or item.get("intervention_name")
                or item.get("description")
                or str(code),
                "sub_benefit_code": item.get("sub_benefit_code")
                or item.get("subBenefitCode")
                or "",
                "payment_mechanism": item.get("paymentMechanism")
                or item.get("payment_mechanism")
                or "",
                "needs_preauth": bool(
                    item.get("needsPreauth") or item.get("needs_preauth")
                ),
                "needs_manual_preauth_approval": bool(
                    item.get("needsManualPreauthApproval")
                    or item.get("needs_manual_preauth_approval")
                ),
                "access_point": item.get("accessPoint") or item.get("access_point") or "",
                "fund": item.get("fund") or "",
                "raw": item,
            }
        )
    return [x for x in out if x.get("code")]


def normalize_sub_benefits(raw: dict[str, Any] | list | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    results: list[Any] = []
    if isinstance(raw, list):
        results = raw
    elif isinstance(raw, dict):
        results = raw.get("results") or raw.get("data") or []
    out: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        code = item.get("code") or item.get("sub_benefit_code") or ""
        if not code:
            continue
        out.append(
            {
                "code": str(code).strip(),
                "name": item.get("name") or item.get("description") or str(code),
                "tariff": item.get("tariff"),
                "raw": item,
            }
        )
    return out


def normalize_patient_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Map eligibility / CR response shapes into HMIS-friendly fields."""
    if not raw:
        return {}

    source: dict[str, Any] = raw
    message = raw.get("message")
    if isinstance(message, dict):
        results = message.get("result") or message.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            source = results[0]
        else:
            source = message

    for key in ("data", "patient", "client", "result", "member"):
        nested = source.get(key) if isinstance(source, dict) else None
        if isinstance(nested, dict):
            source = nested
            break
        if isinstance(nested, list) and nested and isinstance(nested[0], dict):
            source = nested[0]
            break

    if not isinstance(source, dict):
        return {}

    def pick(*keys: str) -> Any:
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
            # Also peek top-level raw for AfyaConnect flat eligibility payloads
            top = raw.get(key) if isinstance(raw, dict) else None
            if top not in (None, ""):
                return top
        return None

    schemes = _extract_schemes(raw) or _extract_schemes(source)
    scheme_names = []
    for s in schemes:
        name = s.get("schemeName") or s.get("scheme_name") or s.get("name") or ""
        if name:
            scheme_names.append(str(name))

    full_name = pick("full_name", "fullName", "patient_name", "patientName")
    # FHIR HumanName may arrive as list/dict under "name" — do not treat as a string label
    name_node = pick("name")
    first_name = pick(
        "first_name",
        "firstName",
        "given_name",
        "givenName",
        "other_names",
        "otherNames",
    )
    middle_name = pick("middle_name", "middleName", "second_name", "secondName")
    last_name = pick(
        "last_name",
        "lastName",
        "family_name",
        "familyName",
        "surname",
    )

    if isinstance(name_node, list) and name_node:
        name_node = name_node[0]
    if isinstance(name_node, dict):
        if not full_name:
            full_name = name_node.get("text") or name_node.get("full_name")
        if not last_name:
            last_name = name_node.get("family") or name_node.get("family_name")
        given = name_node.get("given") or name_node.get("given_name")
        if isinstance(given, list) and given:
            if not first_name:
                first_name = given[0]
            if not middle_name and len(given) > 1:
                middle_name = " ".join(str(x) for x in given[1:] if x)
        elif given and not first_name:
            first_name = given

    if isinstance(full_name, (dict, list)):
        full_name = None

    if full_name and (not first_name or not last_name):
        parts = str(full_name).strip().split()
        if parts and not first_name:
            first_name = parts[0]
        if len(parts) > 1 and not last_name:
            last_name = " ".join(parts[1:])

    if not full_name:
        full_name = " ".join(
            str(x).strip()
            for x in (first_name, middle_name, last_name)
            if x not in (None, "")
        ).strip() or None

    is_alive = pick("isAlive", "is_alive")
    if isinstance(is_alive, str):
        is_alive = is_alive.lower() in ("1", "true", "yes")

    whitelisted = pick("whitelistedForOTP", "whitelisted_for_otp")
    if isinstance(whitelisted, str):
        whitelisted = whitelisted.lower() in ("1", "true", "yes")

    bio_enforced = pick(
        "facilityBiometricsEnforced", "facility_biometrics_enforced"
    )
    if isinstance(bio_enforced, str):
        bio_enforced = bio_enforced.lower() in ("1", "true", "yes")

    eligible_flag = pick("eligible")
    return {
        "cr_id": pick(
            "memberCrNumber",
            "cr_id",
            "clientRegistryId",
            "client_registry_id",
            "id",
        ),
        "id_number": pick(
            "requestIdNumber",
            "id_number",
            "national_id",
            "request_id_number",
            "identification_number",
            "identificationNumber",
        ),
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "full_name": full_name,
        "gender": pick("gender", "sex"),
        "date_of_birth": pick("date_of_birth", "dateOfBirth", "dob", "birthDate"),
        "age": pick("age"),
        "phone": pick("phone", "phone_number", "phoneNumber", "mobile"),
        "email": pick("email"),
        "county": pick("county"),
        "sub_county": pick("sub_county", "subCounty"),
        "identification_type": pick(
            "requestIdType",
            "identification_type",
            "identificationType",
        ),
        "eligible": eligible_flag,
        "eligibility_status": (
            "eligible" if eligible_flag in (1, "1", True) else
            "not_eligible" if eligible_flag in (0, "0", False) else
            pick(
                "statusDesc",
                "eligibility_status",
                "eligibilityStatus",
                "coverage_status",
                "status",
                "message",
            )
        ),
        "eligibility_message": pick("statusDesc", "message", "reason"),
        "status_code": pick("statusCode", "status_code"),
        "status_desc": pick("statusDesc", "status_desc"),
        "possible_solution": pick("possible_solution", "possibleSolution"),
        "coverage_end_date": pick("coverageEndDate", "coverage_end_date"),
        "scheme": scheme_names[0] if scheme_names else pick(
            "scheme", "coverage_scheme", "coverageScheme"
        ),
        "schemes": schemes,
        "scheme_names": scheme_names,
        "is_alive": is_alive if is_alive is not None else True,
        "whitelisted_for_otp": bool(whitelisted) if whitelisted is not None else False,
        "facility_biometrics_enforced": bool(bio_enforced)
        if bio_enforced is not None
        else False,
        "is_pomsf": any(is_pomsf_scheme_name(n) for n in scheme_names),
        "consent_method": consent_method_for_flags(
            facility_biometrics_enforced=bool(bio_enforced) if bio_enforced is not None else False,
            whitelisted_for_otp=bool(whitelisted) if whitelisted is not None else False,
        ),
    }


def extract_dependents_from_raw(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Pull dependants / dependents arrays from CR or eligibility payloads."""
    if not isinstance(raw, dict):
        return []

    pools: list[Any] = []
    message = raw.get("message")
    candidates: list[Any] = [raw, message]
    if isinstance(message, dict):
        results = message.get("result") or message.get("results")
        if isinstance(results, list):
            candidates.extend(results)
        elif isinstance(results, dict):
            candidates.append(results)
    for key in ("data", "patient", "client", "result"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
        elif isinstance(nested, list):
            candidates.extend(x for x in nested if isinstance(x, dict))

    for node in candidates:
        if not isinstance(node, dict):
            continue
        for key in (
            "dependants",
            "dependents",
            "unconfirmed_dependants",
            "unconfirmed_dependents",
            "family_members",
            "household_members",
        ):
            value = node.get(key)
            if isinstance(value, list) and value:
                pools.extend(value)

    dependents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in pools:
        if not isinstance(item, dict):
            continue
        profile = normalize_patient_profile(item)
        # normalize_patient_profile expects wrapped shapes; also accept flat dependent objects
        if not profile.get("full_name") and not profile.get("first_name"):
            profile = normalize_patient_profile({"message": item}) or profile
        if not any(profile.get(k) for k in ("cr_id", "id_number", "full_name", "first_name")):
            # Flat dependent object without nesting
            def pick(*keys: str) -> Any:
                for key in keys:
                    value = item.get(key)
                    if value not in (None, ""):
                        return value
                return None

            profile = {
                "cr_id": pick("cr_id", "id", "clientRegistryId", "client_registry_id"),
                "id_number": pick(
                    "id_number",
                    "identification_number",
                    "identificationNumber",
                    "national_id",
                ),
                "identification_type": pick(
                    "identification_type",
                    "identificationType",
                    "id_type",
                ),
                "first_name": pick("first_name", "firstName", "given_name"),
                "last_name": pick("last_name", "lastName", "family_name"),
                "full_name": pick("full_name", "fullName", "name"),
                "gender": pick("gender", "sex"),
                "date_of_birth": pick("date_of_birth", "dateOfBirth", "dob", "birthDate"),
                "phone": pick("phone", "phone_number", "phoneNumber"),
                "county": pick("county"),
                "sub_county": pick("sub_county", "subCounty"),
                "relationship": pick(
                    "relationship",
                    "relation",
                    "relationship_type",
                    "relationshipType",
                ),
            }
        else:
            profile["relationship"] = (
                item.get("relationship")
                or item.get("relation")
                or item.get("relationship_type")
                or profile.get("relationship")
            )

        if not profile.get("full_name"):
            names = [profile.get("first_name"), profile.get("last_name")]
            profile["full_name"] = " ".join(str(x) for x in names if x).strip() or None

        key = str(
            profile.get("cr_id")
            or profile.get("id_number")
            or profile.get("full_name")
            or ""
        ).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        profile["role"] = "dependent"
        profile["confirmed"] = "unconfirmed" not in str(
            item.get("_source_key", "")
        ).lower()
        dependents.append(profile)
    return dependents


def get_patient_info_by_id_number(
    id_number: str,
    *,
    identification_type: str = "National ID",
    skip_eligibility: bool = False,
    include_coverage: bool = True,
    access_point: str = "OP",
) -> dict[str, Any]:
    """
    AfyaConnect eligibility process (gate):

      1. Patient Search  GET /patients
      2. Eligibility     GET /patients/eligibility  (prefer ClientRegistry ID)
      3. If eligible + include_coverage:
           sub-benefits → interventions (OP/IP)

    Legacy AfyaLink paths remain as fallbacks inside the client.
    """
    client = ShaHieClient()
    profile: dict[str, Any] = {}
    found = False
    eligibility_raw: dict[str, Any] = {}
    cr_raw: dict[str, Any] = {}
    eligibility_error: str | None = None
    cr_error: str | None = None
    dependents: list[dict[str, Any]] = []
    id_type = (identification_type or "National ID").strip() or "National ID"
    outcome = "not_found"
    schemes: list[dict[str, Any]] = []
    sub_benefits: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []
    coverage_error: str | None = None
    pomsf_balances: dict[str, Any] | None = None
    utilization: Any = None

    # --- Step 1: Patient Search ---
    try:
        cr = client.search_patients(id_number, identification_type=id_type)
        cr_raw = cr.raw if isinstance(cr.raw, dict) else {"value": cr.raw}
        if cr.found:
            found = True
            profile = normalize_patient_profile(cr_raw)
        dependents = extract_dependents_from_raw(cr_raw)
    except Exception as exc:  # noqa: BLE001
        cr_error = str(exc)
        print(f"[SHA DEBUG] patient-search unavailable: {exc}")

    cr_id = (profile.get("cr_id") or "").strip()

    # --- Step 2: Eligibility (gate) ---
    if not skip_eligibility:
        # Prefer CR ID on middleware; legacy AfyaLink expects National ID / original type
        if client._middleware_usable() and cr_id:
            elig_id, elig_type = cr_id, "ClientRegistry ID"
        else:
            elig_id = (id_number or "").strip() or cr_id
            elig_type = id_type if id_type != "ClientRegistry ID" or not cr_id else "National ID"
            if id_type == "ClientRegistry ID" and cr_id:
                elig_id, elig_type = cr_id, "ClientRegistry ID"
        try:
            result = client.get_patient_by_id_number(
                elig_id,
                identification_type=elig_type,
            )
            eligibility_raw = (
                result.raw if isinstance(result.raw, dict) else {"value": result.raw}
            )
            if result.found or _eligibility_payload_present(eligibility_raw):
                found = True
            elig_profile = normalize_patient_profile(eligibility_raw)
            for key, value in elig_profile.items():
                if value in (None, "", [], {}):
                    continue
                if key == "cr_id" or not profile.get(key):
                    profile[key] = value
                elif key in (
                    "schemes",
                    "scheme_names",
                    "eligible",
                    "eligibility_status",
                    "eligibility_message",
                    "is_alive",
                    "whitelisted_for_otp",
                    "facility_biometrics_enforced",
                    "consent_method",
                    "is_pomsf",
                    "status_code",
                    "status_desc",
                ):
                    profile[key] = value
            if not cr_id and profile.get("cr_id"):
                cr_id = str(profile.get("cr_id")).strip()
        except Exception as exc:  # noqa: BLE001
            eligibility_error = str(exc)
            print(f"[SHA DEBUG] eligibility unavailable: {exc}")
    else:
        eligibility_error = "skipped"
        print("[SHA DEBUG] eligibility check skipped (registration-only mode)")

    if not dependents:
        dependents = extract_dependents_from_raw(eligibility_raw)

    if not profile.get("id_number"):
        profile["id_number"] = (id_number or "").strip()
    profile["role"] = "principal"

    gate = evaluate_eligibility(profile, eligibility_raw if eligibility_raw else cr_raw)
    outcome = gate["outcome"]
    schemes = gate.get("schemes") or []
    profile["eligible"] = gate["eligible"]
    profile["eligibility_status"] = outcome
    if gate.get("message"):
        profile["eligibility_message"] = gate["message"]

    # Legacy eligibility often returns Cloudflare 522 while CR still works.
    # Surface as partial (found, coverage unconfirmed) — not "not eligible".
    eligible_out: bool | None = bool(gate["eligible"]) if not skip_eligibility else None
    if (
        found
        and eligibility_error
        and not gate["eligible"]
        and (
            "522" in eligibility_error
            or "timed out" in eligibility_error.lower()
            or "eligibility service did not respond" in eligibility_error.lower()
        )
    ):
        outcome = "partial"
        eligible_out = None
        profile["eligible"] = None
        profile["eligibility_status"] = "partial"
        profile["eligibility_message"] = (
            "Patient found in Client Registry, but SHA eligibility is unavailable "
            "(HTTP 522 / upstream timeout). Coverage could not be confirmed — "
            "retry later or escalate to DHA. AfyaConnect OAuth credentials are also "
            "required for middleware /patients/eligibility."
        )
        gate = {
            "outcome": "partial",
            "eligible": False,
            "schemes": [],
            "message": profile["eligibility_message"],
        }

    profile["schemes"] = schemes
    profile["scheme_names"] = [
        str(s.get("schemeName") or s.get("scheme_name") or s.get("name") or "")
        for s in schemes
        if isinstance(s, dict)
    ]
    profile["is_pomsf"] = any(
        is_pomsf_scheme_name(n) for n in (profile.get("scheme_names") or [])
    )
    profile["consent_method"] = consent_method_for_flags(
        facility_biometrics_enforced=bool(
            profile.get("facility_biometrics_enforced")
        ),
        whitelisted_for_otp=bool(profile.get("whitelisted_for_otp")),
    )

    # If we never found the person at all
    if not found and not skip_eligibility:
        outcome = "not_found"
        profile["eligibility_status"] = "not_found"
        eligible_out = False

    # --- Step 3: Benefits / interventions only when eligible + AfyaConnect OAuth ---
    if (
        include_coverage
        and not skip_eligibility
        and gate["eligible"]
        and cr_id
        and profile.get("is_alive") is not False
    ):
        if not client._middleware_usable():
            coverage_error = (
                "Coverage APIs require AfyaConnect OAuth "
                "(SHA_HIE_CLIENT_ID / SHA_HIE_CLIENT_SECRET). "
                "Currently using AfyaLink token — interventions unavailable."
            )
        else:
            try:
                sub_raw = client.get_patient_sub_benefits(cr_id)
                sub_benefits = normalize_sub_benefits(sub_raw)
            except Exception as exc:  # noqa: BLE001
                coverage_error = f"sub-benefits: {exc}"
                print(f"[SHA DEBUG] sub-benefits error: {exc}")

            try:
                # Prefer first few sub-benefits; also try unfiltered interventions
                collected: list[dict[str, Any]] = []
                codes_to_try = [sb["code"] for sb in sub_benefits[:5]] or [None]
                for sb_code in codes_to_try:
                    inter_raw = client.get_patient_interventions(
                        cr_id,
                        sub_benefit_code=sb_code,
                        access_point=access_point or "OP",
                    )
                    collected.extend(normalize_interventions(inter_raw))
                    if len(collected) >= 40:
                        break
                # Dedupe by code
                seen_codes: set[str] = set()
                interventions = []
                for item in collected:
                    code = item.get("code") or ""
                    if code in seen_codes:
                        continue
                    seen_codes.add(code)
                    interventions.append(item)
            except Exception as exc:  # noqa: BLE001
                coverage_error = (
                    f"{coverage_error}; interventions: {exc}"
                    if coverage_error
                    else f"interventions: {exc}"
                )
                print(f"[SHA DEBUG] interventions error: {exc}")

            if profile.get("is_pomsf"):
                try:
                    pomsf_balances = client.get_pomsf_balances(cr_id)
                except Exception as exc:  # noqa: BLE001
                    print(f"[SHA DEBUG] pomsf balances error: {exc}")

            # Utilization for first intervention (preview)
            if interventions:
                try:
                    utilization = client.get_patient_utilization(
                        cr_id,
                        intervention_code=interventions[0]["code"],
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[SHA DEBUG] utilization error: {exc}")

    if not found and eligibility_error and cr_error:
        raise ShaHieRequestError(
            f"SHA lookup failed (eligibility: {eligibility_error}; "
            f"patient-search: {cr_error})"
        )
    if not found and eligibility_error and not cr_raw:
        raise ShaHieRequestError(eligibility_error)

    return {
        "id_number": (id_number or "").strip(),
        "found": found,
        "outcome": outcome,
        "eligible": eligible_out,
        "patient": profile,
        "dependents": dependents,
        "schemes": schemes,
        "sub_benefits": sub_benefits,
        "interventions": interventions,
        "pomsf_balances": pomsf_balances,
        "utilization": utilization,
        "consent_method": profile.get("consent_method") or "otp",
        "raw": {
            "eligibility": eligibility_raw,
            "client_registry": cr_raw,
            "patient_search": cr_raw,
        },
        "eligibility_error": eligibility_error,
        "client_registry_error": cr_error,
        "coverage_error": coverage_error,
    }


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json() if response.content else {}
    except ValueError:
        return {"raw_text": (response.text or "")[:500]}


def _extract_terminology_entities(raw: Any) -> list[Any]:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        return []
    for key in (
        "results",
        "concepts",
        "data",
        "Data",
        "items",
        "destinationEntities",
        "message",
        "ichi",
        "loinc",
    ):
        value = raw.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = (
                value.get("results")
                or value.get("concepts")
                or value.get("data")
                or value.get("result")
                or value.get("ichi")
                or value.get("loinc")
            )
            if isinstance(nested, list):
                return nested
    if raw.get("code") or raw.get("theCode") or raw.get("id") or raw.get("display"):
        return [raw]
    return []


def _normalize_dha_icd11_results(raw: Any) -> list[dict[str, Any]]:
    """Normalize DHA terminology ICD-11 search payloads into {code, title, id}."""
    return _normalize_dha_concept_results(raw, system_hint="WHO/ICD-11")


def _normalize_dha_concept_results(
    raw: Any,
    *,
    system_hint: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize OCL / terminology concept payloads into {code, title, id, system}."""
    results: list[dict[str, Any]] = []
    for item in _extract_terminology_entities(raw):
        if not isinstance(item, dict):
            continue
        title = (
            item.get("title")
            or item.get("display")
            or item.get("name")
            or item.get("label")
            or item.get("concept_name")
            or item.get("display_name")
            or item.get("clean_title")
        )
        if isinstance(title, dict):
            title = title.get("@value") or title.get("value") or title.get("en")
        names = item.get("names")
        if isinstance(names, list) and names and not title:
            title = next(
                (n.get("name") for n in names if isinstance(n, dict) and n.get("name")),
                None,
            )
        code = (
            item.get("code")
            or item.get("theCode")
            or item.get("id_code")
            or item.get("id")
            or item.get("concept_code")
            or item.get("mnemonic")
            or item.get("external_id")
        )
        if code is not None:
            code = str(code).strip()
        if not code and not title:
            continue
        system = (
            item.get("system")
            or item.get("url")
            or item.get("uri")
            or item.get("@id")
            or system_hint
        )
        results.append({
            "id": str(item.get("id") or item.get("uuid") or code or ""),
            "code": code or None,
            "title": str(title).strip() if title else None,
            "system": system,
            "uri": system,
            "owner": item.get("owner") or item.get("org") or None,
            "source": item.get("source") or None,
        })
    return results


def _hpt_kind(code: str | None) -> str:
    """Classify MOH-PPB HPT codes: GE generic product, PH pack, AC component."""
    c = (code or "").strip().upper()
    if c.startswith("GE"):
        return "generic_product"
    if c.startswith("PH"):
        return "product"
    if c.startswith("AC"):
        return "active_component"
    return "other"


def _normalize_dha_hpt_results(raw: Any) -> list[dict[str, Any]]:
    """Normalize DHA HPT medication concepts into {code, title, kind, system}."""
    results: list[dict[str, Any]] = []
    for item in _extract_terminology_entities(raw):
        if not isinstance(item, dict):
            continue
        title = (
            item.get("title")
            or item.get("display")
            or item.get("display_name")
            or item.get("name")
            or item.get("label")
            or item.get("concept_name")
        )
        if isinstance(title, dict):
            title = title.get("@value") or title.get("value") or title.get("en")
        # Prefer Fully Specified Name when OCL returns names[]
        names = item.get("names")
        if isinstance(names, list) and names:
            fsn = next(
                (
                    n.get("name")
                    for n in names
                    if isinstance(n, dict)
                    and (n.get("name_type") or "").lower().startswith("fully")
                    and n.get("name")
                ),
                None,
            )
            if fsn:
                title = fsn
            elif not title:
                title = next(
                    (n.get("name") for n in names if isinstance(n, dict) and n.get("name")),
                    None,
                )
        code = (
            item.get("code")
            or item.get("theCode")
            or item.get("id")
            or item.get("concept_code")
            or item.get("mnemonic")
            or item.get("external_id")
        )
        if code is not None:
            code = str(code).strip()
        if not code and not title:
            continue
        system = (
            item.get("system")
            or item.get("url")
            or item.get("uri")
            or item.get("@id")
        )
        results.append({
            "id": str(item.get("id") or item.get("uuid") or code or ""),
            "code": code or None,
            "title": str(title).strip() if title else None,
            "kind": _hpt_kind(code),
            "system": system,
            "uri": system,
        })
    return results


def _is_route_not_found(data: Any, text: str = "") -> bool:
    blob = " ".join(
        [
            text or "",
            str(data) if not isinstance(data, dict) else "",
            str((data or {}).get("error_msg", "")) if isinstance(data, dict) else "",
            str((data or {}).get("message", "")) if isinstance(data, dict) else "",
        ]
    ).lower()
    return "route not found" in blob or "no route" in blob


def _response_has_facility(data: Any) -> bool:
    if not isinstance(data, dict):
        return bool(data)

    # Explicit error payloads from /v2/facility-search
    if data.get("status") == "error":
        return False
    msg = data.get("message")
    if isinstance(msg, str) and "not found" in msg.lower():
        return False

    message = msg if isinstance(msg, dict) else data
    if not isinstance(message, dict):
        return False

    found_flag = message.get("found", data.get("found"))
    if found_flag in (1, "1", True, "true", "True"):
        return True
    if found_flag in (0, "0", False, "false", "False"):
        return False

    if (
        message.get("facility_code")
        or message.get("facility_name")
        or message.get("registration_number")
        or message.get("registrationNumber")
        or message.get("frCode")
        or message.get("fr_code")
        or message.get("officialName")
        or message.get("fidCode")
        or message.get("uuid")
        or message.get("id")
    ):
        return True

    results = (
        message.get("result")
        or message.get("results")
        or message.get("facilities")
        or message.get("data")
    )
    if isinstance(results, list):
        return len(results) > 0
    if isinstance(results, dict):
        return bool(
            results.get("frCode")
            or results.get("officialName")
            or results.get("facility_code")
            or results.get("uuid")
        )
    return False


def normalize_facility_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Map facility-search response shapes into HMIS-friendly fields."""
    if not raw:
        return {}

    source: dict[str, Any] = raw
    message = raw.get("message")
    if isinstance(message, dict):
        results = (
            message.get("result")
            or message.get("results")
            or message.get("facilities")
        )
        if isinstance(results, list) and results and isinstance(results[0], dict):
            source = results[0]
        else:
            source = message

    for key in ("data", "facility", "result"):
        nested = source.get(key) if isinstance(source, dict) else None
        if isinstance(nested, dict):
            source = nested
            break
        if isinstance(nested, list) and nested and isinstance(nested[0], dict):
            source = nested[0]
            break

    if isinstance(source, dict):
        facilities = source.get("facilities") or source.get("results")
        if isinstance(facilities, list) and facilities and isinstance(facilities[0], dict):
            source = facilities[0]

    if not isinstance(source, dict):
        return {}

    def pick(*keys: str) -> Any:
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
        return None

    address = source.get("address") if isinstance(source.get("address"), dict) else {}

    return {
        "id": pick("id", "uuid"),
        "facility_code": pick(
            "frCode",
            "fr_code",
            "facility_code",
            "facilityCode",
            "code",
            "fidCode",
            "mfl_code",
            "mflCode",
        ),
        "registration_number": pick(
            "registrationNumber",
            "registration_number",
        ),
        "license_number": pick("licenseNumber", "license_number"),
        "fid_code": pick("fidCode", "fid_code"),
        "name": pick(
            "officialName",
            "facility_name",
            "facilityName",
            "name",
            "official_name",
        ),
        "level": pick(
            "kephLevel",
            "facility_level",
            "facilityLevel",
            "level",
            "keph_level",
        ),
        "facility_type": pick("facilityType", "facility_type", "type"),
        "facility_category": pick("facility_category", "facilityCategory", "category"),
        "ownership": pick(
            "facilityOwnership",
            "facility_owner",
            "facilityOwner",
            "ownership",
            "owner",
            "owner_type",
            "ownerType",
        ),
        "regulator": pick("regulatoryBody", "regulator"),
        "status": pick(
            "regulatoryOperationalStatus",
            "facilityLicenseStatus",
            "operational_status",
            "operationalStatus",
            "status",
        ),
        "sha_contract_status": pick("shaContractStatus", "sha_contract_status"),
        "sha_contracted_services": pick(
            "shaContractedServices",
            "sha_contracted_services",
        ),
        "approved": pick("approved"),
        "license_expiry": pick(
            "facilityLicenseEndDate",
            "current_license_expiry_date",
            "currentLicenseExpiryDate",
            "license_expiry",
        ),
        "county": pick("county", "county_name", "countyName")
        or address.get("county")
        or address.get("County"),
        "sub_county": pick("sub_county", "subCounty", "sub_county_name")
        or address.get("subCounty")
        or address.get("sub_county"),
        "ward": pick("ward", "ward_name", "wardName") or address.get("ward"),
        "constituency": pick("constituency"),
        "address": (
            None
            if isinstance(source.get("address"), dict)
            else pick("address", "physical_address", "physicalAddress")
        ),
        "phone": pick(
            "facilityPhoneNumber",
            "phone",
            "phone_number",
            "phoneNumber",
            "telephone",
        ),
        "email": pick("facilityEmail", "email"),
        "administrator_name": pick(
            "facilityAdministratorName",
            "administrator_name",
        ),
        "is_hub": pick("isHub", "is_hub"),
        "pcn_code": pick("pcnCode", "pcn_code"),
        "latitude": pick("latitude", "lat"),
        "longitude": pick("longitude", "lng", "lon"),
        "found": pick("found"),
    }


def get_facility_by_code(
    facility_code: str,
    *,
    identifier_type: str | None = None,
) -> dict[str, Any]:
    """
    Convenience wrapper for AfyaConnect Facility Registry:

        GET {middleware}/facilities/search
            ?identifier=...&identifier-type=fr-code|mfl|…
    """
    result = ShaHieClient().search_facility_by_code(
        facility_code,
        identifier_type=identifier_type,
    )
    profile = normalize_facility_profile(result.raw)
    return {
        "facility_code": result.facility_code,
        "found": result.found,
        "facility": profile,
        "raw": result.raw,
        "identifier_type": (identifier_type or "").strip() or None,
    }


def _response_has_practitioner(data: Any) -> bool:
    if not isinstance(data, dict):
        return bool(data)
    message = data.get("message")
    if isinstance(message, dict):
        if message.get("id") or message.get("registration_number") or message.get("full_name") or message.get("fullName"):
            return True
        results = message.get("result") or message.get("results")
        if isinstance(results, list):
            return len(results) > 0
    return bool(
        data.get("found")
        or data.get("verified")
        or data.get("practitioner")
        or data.get("professional")
        or data.get("data")
    )


def normalize_practitioner_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Map Health Worker Registry (/professionals) payload into normalized fields."""
    if not raw:
        return {}

    source: dict[str, Any] = raw
    message = raw.get("message")
    if isinstance(message, dict):
        results = message.get("result") or message.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            source = results[0]
        else:
            source = message

    for key in ("data", "practitioner", "professional", "result", "health_worker"):
        nested = source.get(key) if isinstance(source, dict) else None
        if isinstance(nested, dict):
            source = nested
            break
        if isinstance(nested, list) and nested and isinstance(nested[0], dict):
            source = nested[0]
            break

    if not isinstance(source, dict):
        return {}

    def pick(*keys: str) -> Any:
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
            top = raw.get(key) if isinstance(raw, dict) else None
            if top not in (None, ""):
                return top
        return None

    full_name = pick("full_name", "fullName", "name", "practitioner_name")
    first_name = pick("first_name", "firstName", "given_name", "givenName")
    last_name = pick("last_name", "lastName", "family_name", "familyName")
    if not full_name and (first_name or last_name):
        full_name = " ".join(filter(None, [first_name, last_name])).strip()

    return {
        "id": pick("id", "uuid"),
        "registration_number": pick(
            "registration_number",
            "registrationNumber",
            "licence_number",
            "licenceNumber",
            "license_number",
            "licenseNumber",
        ),
        "identification_number": pick(
            "identification_number",
            "identificationNumber",
            "id_number",
            "idNumber",
            "national_id",
            "nationalId",
        ),
        "identification_type": pick(
            "identification_type",
            "identificationType",
            "id_type",
        ),
        "regulator": pick("regulator", "regulatory_body", "regulatoryBody", "council"),
        "full_name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "cadre": pick("cadre", "profession", "specialty", "role"),
        "status": pick("status", "licence_status", "licenseStatus", "active_status"),
        "facility_code": pick("facility_code", "facilityCode", "mfl_code", "fr_code"),
        "phone": pick("phone", "phone_number", "phoneNumber", "mobile"),
        "email": pick("email"),
    }


def get_practitioner_by_id(
    identification_number: str,
    *,
    identification_type: str = "registration_number",
    regulator: str | None = None,
) -> dict[str, Any]:
    """
    Convenience wrapper for AfyaConnect Health Worker Registry:

        GET {middleware}/professionals
            ?identification_number=...&identification_type=...[&regulator=...]
    """
    result = ShaHieClient().search_practitioners(
        identification_number,
        identification_type=identification_type,
        regulator=regulator,
    )
    profile = normalize_practitioner_profile(result.raw)
    return {
        "identification_number": result.identification_number,
        "found": result.found,
        "practitioner": profile,
        "raw": result.raw,
        "identification_type": identification_type,
        "regulator": regulator,
    }


def get_sha_bed_occupancy(facility_code: str | None = None) -> dict[str, Any]:
    """
    Fetch facility bed occupancy from DHA HIE (GET /facilities/{facilityCode}/beds/occupancy).
    https://hie-docs.dha.go.ke/eclaims/eligibility#get-facility-bed-occupancy
    """
    client = ShaHieClient()
    raw = client.get_facility_bed_occupancy(facility_code=facility_code)

    rate = raw.get("bed_occupancy_rate") if isinstance(raw, dict) else None
    if isinstance(rate, dict):
        total_beds = int(rate.get("total_number_of_bed") or 0)
        total_ip_visits = int(rate.get("total_ip_visits") or 0)
        occ_rate = round((total_ip_visits / total_beds * 100), 1) if total_beds > 0 else 0.0
        return {
            "sha_synced": True,
            "facility_name": raw.get("name") or "Facility",
            "bp_level": raw.get("bp_level") or "",
            "total_number_of_bed": total_beds,
            "total_ip_visits": total_ip_visits,
            "number_of_normal_bed": int(rate.get("number_of_normal_bed") or 0),
            "normal_ip_visits": int(rate.get("normal_ip_visits") or 0),
            "number_of_icu_bed": int(rate.get("number_of_icu_bed") or 0),
            "icu_visits": int(rate.get("icu_visits") or 0),
            "number_of_hdu_bed": int(rate.get("number_of_hdu_bed") or 0),
            "hdu_visits": int(rate.get("hdu_visits") or 0),
            "number_of_dialysis_bed": int(rate.get("number_of_dialysis_bed") or 0),
            "dialysis_visits": int(rate.get("dialysis_visits") or 0),
            "number_of_baby_cot": int(rate.get("number_of_baby_cot") or 0),
            "newborn_visits": int(rate.get("newborn_visits") or 0),
            "occupancy_rate": occ_rate,
            "raw": raw,
        }

    return {
        "sha_synced": False,
        "facility_name": "",
        "bp_level": "",
        "total_number_of_bed": 0,
        "total_ip_visits": 0,
        "number_of_normal_bed": 0,
        "normal_ip_visits": 0,
        "number_of_icu_bed": 0,
        "icu_visits": 0,
        "number_of_hdu_bed": 0,
        "hdu_visits": 0,
        "number_of_dialysis_bed": 0,
        "dialysis_visits": 0,
        "number_of_baby_cot": 0,
        "newborn_visits": 0,
        "occupancy_rate": 0.0,
        "raw": raw,
    }


