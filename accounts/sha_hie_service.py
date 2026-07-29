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


class ShaHieClient:
    """Thin client for SHA/DHA HIE endpoints (AfyaLink)."""

    def __init__(self) -> None:
        self.base_url = settings.SHA_HIE_BASE_URL.rstrip("/")
        self.username = settings.SHA_HIE_USERNAME
        self.password = settings.SHA_HIE_PASSWORD
        self.agent_id = getattr(settings, "SHA_HIE_AGENT_ID", "") or ""
        self.consumer_key = getattr(settings, "SHA_HIE_CONSUMER_KEY", "") or ""
        self.consumer_secret = getattr(settings, "SHA_HIE_CONSUMER_SECRET", "") or ""
        self.timeout = settings.SHA_HIE_TIMEOUT_SECONDS
        self.verify_ssl = settings.SHA_HIE_VERIFY_SSL
        self.token_path = settings.SHA_HIE_TOKEN_PATH
        self.client_verify_path = settings.SHA_HIE_CLIENT_VERIFY_PATH
        self.eligibility_path = getattr(
            settings,
            "SHA_HIE_ELIGIBILITY_PATH",
            "/v2/eligibility",
        )
        self.facility_search_path = getattr(
            settings,
            "SHA_HIE_FACILITY_SEARCH_PATH",
            "/v2/facility-search",
        )
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

    def _validate_config(self) -> None:
        if not self.username or not self.password:
            raise ShaHieConfigError(
                "SHA_HIE_USERNAME and SHA_HIE_PASSWORD are required."
            )
        if not self.consumer_key:
            raise ShaHieConfigError(
                "SHA_HIE_CONSUMER_KEY is required (Token Authentication Key)."
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
        AfyaLink Basic Authentication flow:
        GET /v1/hie-auth?key={consumer_key}
        Authorization: Basic base64(username:password)

        Notes:
        - Token response is often a raw JWT string (not JSON).
        - Docs indicate the JWT is valid for a single API call/session, so we do not cache.
        """
        self._validate_config()
        print(
            f"[SHA DEBUG] auth start base={self.base_url} "
            f"token_path={self.token_path} key={self.consumer_key} agent={self.agent_id}"
        )
        # Prefer configured UAT host; only fall back to api host for auth path discovery.
        attempts = [
            {
                "base": self.base_url,
                "path": self.token_path,
                "auth": (self.username, self.password),
                "params": {"key": self.consumer_key},
            },
        ]
        if "api.dha.go.ke" not in self.base_url:
            attempts.append({
                "base": "https://api.dha.go.ke",
                "path": "/v1/hie-auth",
                "auth": (self.username, self.password),
                "params": {"key": self.consumer_key},
            })

        errors: list[str] = []
        for attempt in attempts:
            url = f"{attempt['base'].rstrip('/')}{attempt['path']}"
            print(f"[SHA DEBUG] auth attempt GET {url}?key={attempt['params'].get('key')}")
            try:
                response = httpx.get(
                    url,
                    params=attempt["params"],
                    auth=attempt["auth"],
                    timeout=self.timeout,
                    verify=self.verify_ssl,
                    follow_redirects=True,
                )
                print(f"[SHA DEBUG] auth response status={response.status_code} body={response.text[:120]!r}")
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
                print(f"[SHA DEBUG] auth success token_len={len(token)}")
                return token
            except httpx.HTTPError as exc:
                print(f"[SHA DEBUG] auth HTTP error: {exc}")
                errors.append(f"{url} -> {exc}")
                continue

        raise ShaHieRequestError(
            "Failed to authenticate with SHA HIE. Tried: " + "; ".join(errors)
        )

    def _authorized_get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
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

    def get_patient_by_id_number(
        self,
        id_number: str,
        *,
        identification_type: str = "National ID",
    ) -> ShaPatientLookupResult:
        """
        Query SHA eligibility / patient coverage by national ID.

        GET /v2/eligibility
            ?identification_type=National ID
            &identification_number={id}
        """
        clean_id = (id_number or "").strip()
        if not clean_id:
            raise ValueError("id_number is required.")

        # AfyaLink eligibility docs: only identification_type + identification_number.
        # https://afyalink.dha.go.ke/apidocs/eligibility
        candidates = [self.base_url]
        params = {
            "identification_type": identification_type,
            "identification_number": clean_id,
        }
        print(
            f"[SHA DEBUG] eligibility lookup id={clean_id} type={identification_type}"
        )
        last_error: Exception | None = None
        for base in candidates:
            url = f"{base.rstrip('/')}{self.eligibility_path}"
            try:
                print(f"[SHA DEBUG] eligibility GET {url}")
                # Fresh token for each call (AfyaLink JWT is single-use/session).
                response = self._authorized_get(url, params)
                print(
                    f"[SHA DEBUG] eligibility status={response.status_code} "
                    f"body={response.text[:300]!r}"
                )
                if response.status_code == 522:
                    raise ShaHieRequestError(
                        f"{url} returned HTTP 522 (Cloudflare: origin timed out). "
                        "Authentication succeeded but the UAT eligibility service did not respond. "
                        "This is an upstream AfyaLink/UAT infrastructure issue — contact DHA support "
                        "or retry later. Client Registry fallback may still return demographics only."
                    )
                if response.status_code == 404:
                    last_error = ShaHieRequestError(f"{url} -> 404")
                    continue
                response.raise_for_status()
                data = response.json() if response.content else {}
                found = _response_has_patient(data)
                print(f"[SHA DEBUG] eligibility parsed found={found}")
                return ShaPatientLookupResult(
                    id_number=clean_id,
                    found=found,
                    raw=data if isinstance(data, dict) else {"value": data},
                )
            except Exception as exc:  # noqa: BLE001 - collect and try next base
                print(f"[SHA DEBUG] eligibility error: {exc}")
                last_error = exc
                continue
        raise ShaHieRequestError(f"SHA eligibility request failed: {last_error}")

    def fetch_client_registry(
        self,
        id_number: str,
        *,
        identification_type: str = "National ID",
    ) -> ShaPatientLookupResult:
        """Optional Client Registry fetch (CR demographics)."""
        clean_id = (id_number or "").strip()
        if not clean_id:
            raise ValueError("id_number is required.")
        agent = self.agent_id or self.consumer_key
        if not agent:
            raise ShaHieConfigError("SHA_HIE_AGENT_ID is required for client registry lookup.")

        url = f"{self.base_url}{self.client_verify_path}"
        params = {
            "identification_type": identification_type,
            "identification_number": clean_id,
            "agent": agent,
        }
        print(f"[SHA DEBUG] client-registry GET {url} id={clean_id} agent={agent}")
        try:
            response = self._authorized_get(url, params)
            print(
                f"[SHA DEBUG] client-registry status={response.status_code} "
                f"body={response.text[:400]!r}"
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ShaHieRequestError(f"SHA client-registry request failed: {exc}") from exc

        data = response.json() if response.content else {}
        data = decrypt_response_pii(data)
        return ShaPatientLookupResult(
            id_number=clean_id,
            found=_response_has_patient(data),
            raw=data if isinstance(data, dict) else {"value": data},
        )

    def search_facility_by_code(self, facility_code: str) -> ShaFacilityLookupResult:
        """
        Search facility registry by registration / facility code.

        Docs list /v1/facility-search, but current UAT serves /v2/facility-search.
        We try the configured path first, then fall back to the other version.
        """
        clean_code = (facility_code or "").strip()
        if not clean_code:
            raise ValueError("facility_code is required.")

        primary = self.facility_search_path or "/v2/facility-search"
        candidates = [primary]
        for alt in ("/v2/facility-search", "/v1/facility-search"):
            if alt not in candidates:
                candidates.append(alt)

        params = {"facility_code": clean_code}
        last_error: Exception | None = None
        last_raw: dict[str, Any] | None = None

        for path in candidates:
            url = f"{self.base_url.rstrip('/')}{path}"
            print(f"[SHA DEBUG] facility-search GET {url}?facility_code={clean_code}")
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

                # Gateway "route missing" — try next path.
                if response.status_code == 404 and _is_route_not_found(raw, response.text):
                    last_error = ShaHieRequestError(f"{url} -> 404 Route Not Found")
                    continue

                # Facility truly missing on this API version.
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
        return f"{self.terminology_base_url.rstrip('/')}/{path.lstrip('/')}"

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
            raise ShaHieRequestError(f"{action} failed ({response.status_code}): {detail}")
        return raw

    def send_claim_otp(self, *, patient_id: str, phone: str | None = None) -> dict[str, Any]:
        """POST /claims/otp — request OTP for visit consent (payload may vary by UAT)."""
        body: dict[str, Any] = {"patient_id": (patient_id or "").strip()}
        if phone:
            body["phone"] = phone
        url = self._eclaims_url("/claims/otp")
        response = self._authorized_request("POST", url, json_body=body)
        return self._raise_for_eclaims(response, "claims/otp")

    def create_virtual_claim(
        self,
        *,
        patient_id: str,
        service_type: str,
        intervention_codes: list[str],
        otp: str,
        practitioner_identification_type: str | None = None,
        practitioner_identification_number: str | None = None,
        practitioner_regulation_body: str | None = None,
    ) -> dict[str, Any]:
        """POST /claims/visit — start visit / create virtual claim (OTP path)."""
        body: dict[str, Any] = {
            "patient_id": (patient_id or "").strip(),
            "service_type": (service_type or "OUTPATIENT").strip().upper(),
            "intervention_codes": list(intervention_codes or []),
            "otp": (otp or "").strip(),
        }
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
        return None

    eligible = pick("eligible")
    return {
        "cr_id": pick("cr_id", "clientRegistryId", "client_registry_id", "id"),
        "id_number": pick(
            "id_number",
            "national_id",
            "request_id_number",
            "identification_number",
            "identificationNumber",
        ),
        "first_name": pick("first_name", "firstName", "given_name", "givenName"),
        "last_name": pick("last_name", "lastName", "family_name", "familyName"),
        "full_name": pick("full_name", "fullName", "name"),
        "gender": pick("gender", "sex"),
        "date_of_birth": pick("date_of_birth", "dateOfBirth", "dob", "birthDate"),
        "phone": pick("phone", "phone_number", "phoneNumber", "mobile"),
        "email": pick("email"),
        "county": pick("county"),
        "sub_county": pick("sub_county", "subCounty"),
        "identification_type": pick("identification_type", "identificationType"),
        "eligible": eligible,
        "eligibility_status": (
            "eligible" if eligible in (1, "1", True) else
            "not_eligible" if eligible in (0, "0", False) else
            pick("eligibility_status", "eligibilityStatus", "coverage_status", "status", "message")
        ),
        "eligibility_message": pick("message", "reason"),
        "possible_solution": pick("possible_solution", "possibleSolution"),
        "coverage_end_date": pick("coverageEndDate", "coverage_end_date"),
        "scheme": pick("scheme", "coverage_scheme", "coverageScheme"),
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
) -> dict[str, Any]:
    """
    Lookup SHA patient by National ID.

    Tries eligibility first, then Client Registry for demographics + dependents.
    If eligibility is down (e.g. Cloudflare 522), CR-only results are still returned.

    When *skip_eligibility* is True the eligibility API call is skipped entirely
    and only the Client Registry is queried (registration + dependents only).
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

    if not skip_eligibility:
        try:
            result = client.get_patient_by_id_number(
                id_number,
                identification_type=id_type,
            )
            eligibility_raw = result.raw if isinstance(result.raw, dict) else {"value": result.raw}
            found = result.found
            profile = normalize_patient_profile(eligibility_raw)
        except Exception as exc:  # noqa: BLE001 - fall back to CR
            eligibility_error = str(exc)
            print(f"[SHA DEBUG] eligibility unavailable, will try CR: {exc}")
    else:
        eligibility_error = "skipped"
        print("[SHA DEBUG] eligibility check skipped (registration-only mode)")

    try:
        cr = client.fetch_client_registry(
            id_number,
            identification_type=id_type,
        )
        cr_raw = cr.raw if isinstance(cr.raw, dict) else {"value": cr.raw}
        if cr.found:
            found = True
            cr_profile = normalize_patient_profile(cr_raw)
            for key, value in cr_profile.items():
                if value in (None, ""):
                    continue
                if key == "cr_id" or not profile.get(key):
                    profile[key] = value
        dependents = extract_dependents_from_raw(cr_raw)
    except Exception as exc:  # noqa: BLE001 - optional enrichment
        cr_error = str(exc)
        print(f"[SHA DEBUG] client-registry unavailable: {exc}")

    if not dependents:
        dependents = extract_dependents_from_raw(eligibility_raw)

    if not profile.get("id_number"):
        profile["id_number"] = (id_number or "").strip()
    profile["role"] = "principal"

    if not found and eligibility_error and cr_error:
        raise ShaHieRequestError(
            f"SHA lookup failed (eligibility: {eligibility_error}; "
            f"client-registry: {cr_error})"
        )
    if not found and eligibility_error and not cr_raw:
        raise ShaHieRequestError(eligibility_error)

    return {
        "id_number": (id_number or "").strip(),
        "found": found,
        "patient": profile,
        "dependents": dependents,
        "raw": {
            "eligibility": eligibility_raw,
            "client_registry": cr_raw,
        },
        "eligibility_error": eligibility_error,
        "client_registry_error": cr_error,
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
        "items",
        "destinationEntities",
        "message",
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
            )
            if isinstance(nested, list):
                return nested
    if raw.get("code") or raw.get("theCode") or raw.get("id") or raw.get("display"):
        return [raw]
    return []


def _normalize_dha_icd11_results(raw: Any) -> list[dict[str, Any]]:
    """Normalize DHA terminology ICD-11 search payloads into {code, title, id}."""
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
        )
        if isinstance(title, dict):
            title = title.get("@value") or title.get("value") or title.get("en")
        code = (
            item.get("code")
            or item.get("theCode")
            or item.get("id")
            or item.get("concept_code")
            or item.get("mnemonic")
        )
        if code is not None:
            code = str(code).strip()
        if not code and not title:
            continue
        results.append({
            "id": str(item.get("id") or item.get("uuid") or code or ""),
            "code": code or None,
            "title": str(title).strip() if title else None,
            "uri": item.get("url") or item.get("uri") or item.get("@id"),
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
        or message.get("id")
    ):
        return True

    results = message.get("result") or message.get("results") or message.get("facilities")
    if isinstance(results, list):
        return len(results) > 0
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

    return {
        "id": pick("id"),
        "facility_code": pick(
            "facility_code",
            "facilityCode",
            "code",
            "mfl_code",
            "mflCode",
        ),
        "registration_number": pick(
            "registration_number",
            "registrationNumber",
        ),
        "name": pick(
            "facility_name",
            "facilityName",
            "name",
            "official_name",
            "officialName",
        ),
        "level": pick("facility_level", "facilityLevel", "level", "keph_level"),
        "facility_type": pick("facility_type", "facilityType", "type"),
        "facility_category": pick("facility_category", "facilityCategory", "category"),
        "ownership": pick(
            "facility_owner",
            "facilityOwner",
            "ownership",
            "owner",
            "owner_type",
            "ownerType",
        ),
        "regulator": pick("regulator"),
        "status": pick(
            "operational_status",
            "operationalStatus",
            "status",
        ),
        "approved": pick("approved"),
        "license_expiry": pick(
            "current_license_expiry_date",
            "currentLicenseExpiryDate",
            "license_expiry",
        ),
        "county": pick("county", "county_name", "countyName"),
        "sub_county": pick("sub_county", "subCounty", "sub_county_name"),
        "ward": pick("ward", "ward_name", "wardName"),
        "constituency": pick("constituency"),
        "address": pick("address", "physical_address", "physicalAddress"),
        "phone": pick("phone", "phone_number", "phoneNumber", "telephone"),
        "email": pick("email"),
        "latitude": pick("latitude", "lat"),
        "longitude": pick("longitude", "lng", "lon"),
        "found": pick("found"),
    }


def get_facility_by_code(facility_code: str) -> dict[str, Any]:
    """
    Convenience wrapper for:

        GET /v2/facility-search?facility_code=...
    """
    result = ShaHieClient().search_facility_by_code(facility_code)
    profile = normalize_facility_profile(result.raw)
    return {
        "facility_code": result.facility_code,
        "found": result.found,
        "facility": profile,
        "raw": result.raw,
    }
