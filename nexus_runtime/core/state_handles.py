"""
nexus_runtime.core.state_handles
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

HMAC-SHA256 signed opaque client-side state handles for stateless horizontal
scaling across Nexus Runtime replicas, strictly bound to tenant_id & sub.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


class StateHandleAuthError(PermissionError):
    """Raised when an opaque state handle fails integrity, expiry, or identity binding checks."""


@dataclass(frozen=True, slots=True)
class VerifiedStateHandle:
    run_id: str
    tenant_id: str
    sub: str
    step_index: int
    issued_at: int
    expires_at: int


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * ((4 - len(segment) % 4) % 4))


class StateHandleManager:
    """
    Mints and verifies compact HMAC-SHA256 opaque handles (`nxsh_...`) for
    workflow cursors and MCP Task handles.

    Important security invariant: an opaque state handle is NOT authentication;
    presenting a valid handle under a different verified tenant_id or sub
    fails with `StateHandleAuthError` (HTTP 403).
    """

    def __init__(self, secret: Optional[str] = None, default_ttl_seconds: int = 3600) -> None:
        raw_secret = secret or os.getenv("NEXUS_STATE_HANDLE_SECRET") or secrets.token_hex(32)
        self._secret = raw_secret.encode("utf-8")
        self.default_ttl_seconds = default_ttl_seconds

    def mint(
        self,
        *,
        run_id: str,
        tenant_id: str,
        sub: str = "anonymous",
        step_index: int = 0,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        now = int(time.time())
        exp = now + (ttl_seconds or self.default_ttl_seconds)
        claims: Dict[str, Any] = {
            "rid": run_id,
            "tid": tenant_id,
            "sub": sub,
            "idx": step_index,
            "iat": now,
            "exp": exp,
        }
        payload_b64 = _b64u_encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        sig = hmac.new(self._secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
        return f"nxsh_{payload_b64}.{_b64u_encode(sig)}"

    def verify(
        self,
        handle: str,
        *,
        expected_tenant_id: str,
        expected_sub: str,
        now: Optional[float] = None,
    ) -> VerifiedStateHandle:
        if not isinstance(handle, str) or not handle.startswith("nxsh_") or "." not in handle:
            raise StateHandleAuthError("Malformed or unsigned opaque state handle.")

        body = handle[len("nxsh_") :]
        payload_b64, sig_b64 = body.split(".", 1)
        expected_sig = hmac.new(self._secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
        try:
            provided_sig = _b64u_decode(sig_b64)
            claims = json.loads(_b64u_decode(payload_b64))
        except Exception as exc:
            raise StateHandleAuthError(f"Unparseable opaque state handle: {exc}") from exc

        if not hmac.compare_digest(provided_sig, expected_sig):
            raise StateHandleAuthError("Opaque state handle HMAC signature mismatch.")

        current = time.time() if now is None else now
        if current >= float(claims.get("exp", 0)):
            raise StateHandleAuthError("Opaque state handle has expired.")

        if claims.get("tid") != expected_tenant_id or claims.get("sub") != expected_sub:
            raise StateHandleAuthError(
                "Authorization denied: opaque state handle does not belong to authenticated tenant/principal."
            )

        return VerifiedStateHandle(
            run_id=str(claims["rid"]),
            tenant_id=str(claims["tid"]),
            sub=str(claims["sub"]),
            step_index=int(claims["idx"]),
            issued_at=int(claims["iat"]),
            expires_at=int(claims["exp"]),
        )
