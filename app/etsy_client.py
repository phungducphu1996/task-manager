from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException, status

from app.config import ETSY_API_BASE_URL


def _request_etsy(path: str, method: str = "GET", payload: dict[str, Any] | None = None, token: str | None = None) -> dict[str, Any]:
    url = f"{ETSY_API_BASE_URL}/{path.lstrip('/')}"
    body = None
    headers = {"Content-Type": "application/json; charset=utf-8"}

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url=url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=12) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="ignore")
        detail = f"etsy_http_{exc.code}"
        try:
            parsed = json.loads(raw_error)
            if isinstance(parsed, dict) and parsed.get("detail"):
                detail = str(parsed.get("detail"))
        except json.JSONDecodeError:
            pass
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except URLError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="etsy_unreachable") from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="etsy_invalid_json") from exc


def etsy_login(username: str, password: str) -> dict[str, Any]:
    return _request_etsy("auth/login", method="POST", payload={"username": username, "password": password})


def etsy_me(token: str) -> dict[str, Any]:
    return _request_etsy("me", method="GET", token=token)


def etsy_sellers(token: str) -> list[dict[str, Any]]:
    # Preferred endpoint for Social integration.
    try:
        data = _request_etsy("users/sellers", method="GET", token=token)
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [row for row in data["items"] if isinstance(row, dict)]
    except HTTPException as exc:
        if exc.status_code not in {404, 405}:
            raise

    # Fallback to existing users endpoints (some variants reject page_size with 422).
    rows: list[Any] = []
    fallback_paths = (
        "users?page=1&page_size=200",
        "users?page=1&per_page=200",
        "users?page=1&limit=200",
        "users",
    )
    for path in fallback_paths:
        try:
            data = _request_etsy(path, method="GET", token=token)
        except HTTPException as exc:
            if exc.status_code in {404, 405, 422}:
                continue
            raise

        if isinstance(data, dict) and isinstance(data.get("items"), list):
            rows = data["items"]
            break
        if isinstance(data, list):
            rows = data
            break

    sellers: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "").lower()
        if role not in {"user", "seller"}:
            continue
        if not bool(row.get("is_active", True)):
            continue
        sellers.append(row)
    return sellers
