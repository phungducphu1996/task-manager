from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import ZALO_SHARED_SECRET, ZALO_WORKER_URL


def _post_worker(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not ZALO_WORKER_URL:
        return {"ok": False, "error": "zalo_worker_not_configured"}

    url = f"{ZALO_WORKER_URL}/{path.lstrip('/')}"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if ZALO_SHARED_SECRET:
        headers["X-Internal-Secret"] = ZALO_SHARED_SECRET
    body = json.dumps(payload).encode("utf-8")
    request = Request(url=url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=12) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {"ok": True}
            if isinstance(parsed, dict):
                return parsed
            return {"ok": True, "data": parsed}
    except HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(raw_error)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"ok": False, "error": f"http_{exc.code}", "raw_error": raw_error}
    except URLError as exc:
        return {"ok": False, "error": "zalo_worker_unreachable", "detail": str(exc)}


def send_text(text: str) -> dict[str, Any]:
    return _post_worker("api/send-text", {"text": text})


def send_package(package: dict[str, Any]) -> dict[str, Any]:
    # Preferred endpoint if worker supports rich package.
    result = _post_worker("api/send-package", {"package": package})
    if result.get("ok"):
        return result

    media = package.get("media") or []
    media_text = "\n".join(media)
    fallback_text = (
        f"[FULL POST PACKAGE]\n"
        f"Title: {package.get('title')}\n"
        f"Caption: {package.get('caption')}\n"
        f"Hashtags: {package.get('hashtags')}\n"
        f"Mentions: {package.get('mentions')}\n"
        f"Product URL: {package.get('product_url')}\n"
        f"Media:\n{media_text}"
    )
    fallback = send_text(fallback_text)
    if fallback.get("ok"):
        return {"ok": True, "fallback": True}
    return fallback

