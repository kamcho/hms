from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings
from django.core.cache import cache


TOKEN_CACHE_KEY = "icd11_access_token"


class Icd11Error(Exception):
    """Base WHO ICD-11 API error."""


class Icd11ConfigError(Icd11Error):
    """Raised when ICD-11 API credentials/settings are missing."""


class Icd11RequestError(Icd11Error):
    """Raised when ICD-11 API request fails."""


class Icd11Client:
    """
    Thin client for WHO ICD-API v2.

    Docs: https://icd.who.int/docs/icd-api/APIDoc-Version2/
    Auth: https://icd.who.int/docs/icd-api/API-Authentication/
    """

    def __init__(self) -> None:
        self.api_base = settings.ICD11_API_BASE_URL.rstrip("/")
        self.token_url = settings.ICD11_TOKEN_URL
        self.client_id = settings.ICD11_CLIENT_ID
        self.client_secret = settings.ICD11_CLIENT_SECRET
        self.release = settings.ICD11_RELEASE
        self.linearization = settings.ICD11_LINEARIZATION
        self.language = settings.ICD11_LANGUAGE
        self.timeout = settings.ICD11_TIMEOUT_SECONDS
        self.verify_ssl = settings.ICD11_VERIFY_SSL

    def _validate_config(self) -> None:
        if not self.client_id or not self.client_secret:
            raise Icd11ConfigError(
                "ICD11_CLIENT_ID and ICD11_CLIENT_SECRET are required. "
                "Register at https://icd.who.int/icdapi and add keys to .env."
            )

    def _get_access_token(self, *, force_refresh: bool = False) -> str:
        self._validate_config()
        if not force_refresh:
            cached = cache.get(TOKEN_CACHE_KEY)
            if cached:
                return str(cached)

        try:
            response = httpx.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "scope": "icdapi_access",
                },
                auth=(self.client_id, self.client_secret),
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise Icd11RequestError(f"ICD-11 token request failed: {exc}") from exc

        token = payload.get("access_token")
        if not token:
            raise Icd11RequestError("ICD-11 token response did not include access_token.")

        expires_in = int(payload.get("expires_in") or 3300)
        cache.set(TOKEN_CACHE_KEY, token, timeout=max(expires_in - 60, 60))
        return str(token)

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "API-Version": "v2",
            "Accept": "application/json",
            "Accept-Language": self.language,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("http://") or path.startswith("https://"):
            url = path.replace("http://id.who.int", self.api_base).replace(
                "https://id.who.int", self.api_base
            )
        else:
            url = f"{self.api_base}/{path.lstrip('/')}"

        token = self._get_access_token()
        try:
            response = httpx.request(
                method,
                url,
                params=params,
                headers=self._headers(token),
                timeout=self.timeout,
                verify=self.verify_ssl,
                follow_redirects=True,
            )
            if response.status_code == 401:
                token = self._get_access_token(force_refresh=True)
                response = httpx.request(
                    method,
                    url,
                    params=params,
                    headers=self._headers(token),
                    timeout=self.timeout,
                    verify=self.verify_ssl,
                    follow_redirects=True,
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise Icd11RequestError(f"ICD-11 request failed for {url}: {exc}") from exc

        if not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"value": data}

    def list_releases(self) -> list[dict[str, Any]]:
        """List ICD-11 MMS releases."""
        data = self._request("GET", "/icd/release/11")
        releases = data.get("release") or data.get("releases") or data
        if isinstance(releases, list):
            return [r for r in releases if isinstance(r, dict)]
        if isinstance(releases, dict):
            return [releases]
        return []

    def search(
        self,
        query: str,
        *,
        release: str | None = None,
        linearization: str | None = None,
        subtree_filter: str | None = None,
        include_keyword_result: bool = False,
    ) -> dict[str, Any]:
        """
        Search ICD-11 MMS linearization.

        GET /icd/release/11/{release}/{linearization}/search?q=...
        """
        clean_query = (query or "").strip()
        if not clean_query:
            raise ValueError("query is required.")

        rel = release or self.release
        lin = linearization or self.linearization
        path = f"/icd/release/11/{rel}/{lin}/search"
        params: dict[str, Any] = {"q": clean_query}
        if subtree_filter:
            params["subtreeFilterUsesFoundationDescendants"] = "false"
            params["subtreeFilter"] = subtree_filter
        if include_keyword_result:
            params["includeKeywordResult"] = "true"

        raw = self._request("GET", path, params=params)
        return {
            "query": clean_query,
            "release": rel,
            "linearization": lin,
            "results": normalize_search_results(raw),
            "raw": raw,
        }

    def get_entity(self, entity_ref: str) -> dict[str, Any]:
        """
        Fetch an ICD entity by numeric id or full https://id.who.int/icd/entity/{id} URI.
        """
        ref = (entity_ref or "").strip()
        if not ref:
            raise ValueError("entity_ref is required.")

        if ref.startswith("http://") or ref.startswith("https://"):
            path = ref
        else:
            entity_id = ref.rstrip("/").split("/")[-1]
            path = f"/icd/entity/{entity_id}"

        raw = self._request("GET", path)
        return {
            "entity": normalize_entity(raw),
            "raw": raw,
        }

    def get_code_info(
        self,
        code: str,
        *,
        release: str | None = None,
        linearization: str | None = None,
    ) -> dict[str, Any]:
        """
        Lookup ICD-11 MMS code details.

        GET /icd/release/11/{release}/{linearization}/codeinfo/{code}
        """
        clean_code = (code or "").strip().upper()
        if not clean_code:
            raise ValueError("code is required.")

        rel = release or self.release
        lin = linearization or self.linearization
        path = f"/icd/release/11/{rel}/{lin}/codeinfo/{clean_code}"
        raw = self._request("GET", path)
        return {
            "code": clean_code,
            "release": rel,
            "linearization": lin,
            "entity": normalize_entity(raw),
            "raw": raw,
        }


def _entity_id_from_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    return uri.rstrip("/").split("/")[-1] or None


def normalize_entity(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}

    title = (
        data.get("title")
        or data.get("@title")
        or data.get("label")
        or data.get("preferred")
    )
    if isinstance(title, dict):
        title = title.get("@value") or title.get("value")

    definition = data.get("definition")
    if isinstance(definition, dict):
        definition = definition.get("@value") or definition.get("value")

    coding = data.get("codingInfo") or data.get("codeInfo") or {}
    if isinstance(coding, dict):
        code = coding.get("code") or coding.get("theCode")
    else:
        code = data.get("code") or data.get("theCode")

    entity_uri = data.get("@id") or data.get("id") or data.get("stemId")
    if isinstance(entity_uri, dict):
        entity_uri = entity_uri.get("@id") or entity_uri.get("id")

    return {
        "id": _entity_id_from_uri(entity_uri if isinstance(entity_uri, str) else None),
        "uri": entity_uri if isinstance(entity_uri, str) else None,
        "title": title,
        "code": code,
        "definition": definition,
        "class_kind": data.get("classKind"),
        "is_leaf": data.get("isLeaf") or data.get("isLeafInMms"),
        "parent": data.get("parent"),
        "child": data.get("child"),
    }


def normalize_search_results(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []

    entities = (
        raw.get("destinationEntities")
        or raw.get("entities")
        or raw.get("results")
        or []
    )
    if not isinstance(entities, list):
        return []

    results: list[dict[str, Any]] = []
    for item in entities:
        if not isinstance(item, dict):
            continue
        uri = item.get("@id") or item.get("id") or item.get("stemId")
        title = item.get("title") or item.get("label")
        if isinstance(title, dict):
            title = title.get("@value") or title.get("value")
        results.append({
            "id": _entity_id_from_uri(uri if isinstance(uri, str) else None),
            "uri": uri if isinstance(uri, str) else None,
            "title": title,
            "code": item.get("theCode") or item.get("code"),
            "is_leaf": item.get("isLeaf"),
            "score": item.get("hasMatchingScore") or item.get("score"),
            "chapter": item.get("chapter"),
        })
    return results


def search_icd11(query: str, **kwargs: Any) -> dict[str, Any]:
    from django.conf import settings as django_settings

    if getattr(django_settings, 'ICD11_USE_LOCAL_DB', True):
        from .icd11_local import local_icd11_count, search_icd11_local

        if local_icd11_count(
            release=kwargs.get('release'),
            linearization=kwargs.get('linearization'),
        ):
            limit = int(kwargs.pop('limit', 25))
            return search_icd11_local(query, limit=limit, **kwargs)

    return Icd11Client().search(query, **kwargs)


def get_icd11_entity(entity_ref: str, **kwargs: Any) -> dict[str, Any]:
    from django.conf import settings as django_settings

    if getattr(django_settings, 'ICD11_USE_LOCAL_DB', True):
        from .icd11_local import get_icd11_entity_local, local_icd11_count

        if local_icd11_count(
            release=kwargs.get('release'),
            linearization=kwargs.get('linearization'),
        ):
            payload = get_icd11_entity_local(entity_ref, **kwargs)
            if payload:
                return payload

    return Icd11Client().get_entity(entity_ref)


def get_icd11_code_info(code: str, **kwargs: Any) -> dict[str, Any]:
    from django.conf import settings as django_settings

    if getattr(django_settings, 'ICD11_USE_LOCAL_DB', True):
        from .icd11_local import get_icd11_code_info_local, local_icd11_count

        if local_icd11_count(
            release=kwargs.get('release'),
            linearization=kwargs.get('linearization'),
        ):
            payload = get_icd11_code_info_local(code, **kwargs)
            if payload:
                return payload

    return Icd11Client().get_code_info(code, **kwargs)
