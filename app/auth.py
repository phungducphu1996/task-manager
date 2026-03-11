from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import AUTH_REQUIRED, ETSY_JWT_ALGORITHM, ETSY_JWT_SECRET

http_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user_id: str
    username: str
    role: str
    raw_claims: dict[str, Any]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_seller(self) -> bool:
        return self.role == "user"


def decode_etsy_jwt(token: str) -> Principal:
    if not ETSY_JWT_SECRET:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="missing_etsy_jwt_secret")
    claims = _decode_hs256_jwt(token, ETSY_JWT_SECRET, ETSY_JWT_ALGORITHM)

    subject = str(claims.get("sub") or "").strip()
    username = str(claims.get("username") or "").strip()
    role = str(claims.get("role") or "").strip().lower()

    if not subject or not username or role not in {"admin", "user"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token_claims")

    return Principal(user_id=subject, username=username, role=role, raw_claims=claims)


def _decode_hs256_jwt(token: str, secret: str, expected_alg: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")

    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(_urlsafe_b64decode(header_b64).decode("utf-8"))
        payload = json.loads(_urlsafe_b64decode(payload_b64).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token") from exc

    alg = str(header.get("alg") or "")
    if alg != expected_alg or alg != "HS256":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unsupported_token_alg")

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    got_sig = _urlsafe_b64decode(signature_b64)
    if not hmac.compare_digest(expected_sig, got_sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token_signature")

    exp = payload.get("exp")
    if exp is not None:
        try:
            exp_value = float(exp)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token_exp") from exc
        if exp_value < time.time():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token_expired")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token_payload")
    return payload


def _urlsafe_b64decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data + padding)


def get_optional_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
) -> Principal | None:
    if not credentials:
        if AUTH_REQUIRED:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_authorization")
        return None
    return decode_etsy_jwt(credentials.credentials)


def get_current_principal(
    principal: Principal | None = Depends(get_optional_principal),
) -> Principal:
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_authorization")
    return principal
