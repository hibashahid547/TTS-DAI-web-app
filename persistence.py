"""HTTP clients for PostgREST Data API and object Store API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

import httpx


JsonDict = Dict[str, Any]
JsonValue = Union[JsonDict, List[Any], str, int, float, bool, None]


class ApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class DataApi:
    """Minimal PostgREST client."""

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                "apikey": api_key,
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        headers = dict(extra_headers or {})
        response = self._client.request(
            method,
            path if path.startswith("/") else f"/{path}",
            params=params,
            json=json,
            headers=headers,
        )
        if response.status_code >= 400:
            raise ApiError(
                f"Data API {method} {path} failed: {response.status_code}",
                status_code=response.status_code,
                body=response.text,
            )
        if response.status_code == 204 or not response.content:
            return None
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            return response.json()
        return response.text

    def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: Optional[Dict[str, str]] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[JsonDict]:
        params: Dict[str, Any] = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = limit
        data = self._request("GET", f"/{table}", params=params)
        return data or []

    def insert(self, table: str, row: JsonDict) -> JsonDict:
        data = self._request(
            "POST",
            f"/{table}",
            json=row,
            extra_headers={"Prefer": "return=representation"},
        )
        if isinstance(data, list):
            if not data:
                raise ApiError(f"Insert into {table} returned no rows")
            return data[0]
        if isinstance(data, dict):
            return data
        raise ApiError(f"Unexpected insert response for {table}: {data!r}")

    def upsert(
        self,
        table: str,
        row: JsonDict,
        *,
        on_conflict: str,
    ) -> JsonDict:
        data = self._request(
            "POST",
            f"/{table}",
            params={"on_conflict": on_conflict},
            json=row,
            extra_headers={
                "Prefer": "resolution=merge-duplicates,return=representation",
            },
        )
        if isinstance(data, list):
            if not data:
                raise ApiError(f"Upsert into {table} returned no rows")
            return data[0]
        if isinstance(data, dict):
            return data
        raise ApiError(f"Unexpected upsert response for {table}: {data!r}")

    def delete(self, table: str, *, filters: Dict[str, str]) -> None:
        self._request(
            "DELETE",
            f"/{table}",
            params=filters,
            extra_headers={"Prefer": "return=minimal"},
        )


class StoreApi:
    """
    Object storage client.

    STORE_API_URL should point at the buckets root, e.g.
    https://host/.../storage-api/buckets/
    """

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 120.0):
        self.base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "apikey": api_key,
                "Authorization": f"Bearer {api_key}",
            },
        )

    def close(self) -> None:
        self._client.close()

    def object_url(self, bucket: str, path: str) -> str:
        clean = path.lstrip("/")
        encoded = "/".join(quote(part, safe="") for part in clean.split("/"))
        return f"{self.base_url}{bucket}/objects/{encoded}"

    def public_url(self, bucket: str, path: str) -> str:
        # Public buckets serve the same object URL without auth.
        return self.object_url(bucket, path)

    def upload(
        self,
        bucket: str,
        path: str,
        data: bytes,
        *,
        content_type: str,
    ) -> str:
        url = self.object_url(bucket, path)
        response = self._client.put(
            url,
            content=data,
            headers={"Content-Type": content_type},
        )
        if response.status_code >= 400:
            raise ApiError(
                f"Store upload failed: {response.status_code}",
                status_code=response.status_code,
                body=response.text,
            )
        return self.public_url(bucket, path)

    def download(self, bucket: str, path: str) -> bytes:
        url = self.object_url(bucket, path)
        response = self._client.get(url)
        if response.status_code >= 400:
            raise ApiError(
                f"Store download failed: {response.status_code}",
                status_code=response.status_code,
                body=response.text,
            )
        return response.content

    def remove(self, bucket: str, paths: List[str]) -> None:
        for path in paths:
            url = self.object_url(bucket, path)
            response = self._client.delete(url)
            if response.status_code >= 400 and response.status_code != 404:
                raise ApiError(
                    f"Store delete failed for {path}: {response.status_code}",
                    status_code=response.status_code,
                    body=response.text,
                )
