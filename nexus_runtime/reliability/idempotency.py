"""
nexus_runtime.reliability.idempotency
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Idempotency control for distributed agent invocations.
Guarantees at-most-once execution semantics for identical idempotency keys,
prevents race conditions, and caches completed responses for seamless retries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class IdempotencyStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IdempotencyRecord(BaseModel):
    key: str
    tenant_id: str
    request_hash: str
    status: IdempotencyStatus
    response_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    expires_at: float


class IdempotencyConflictError(Exception):
    """Raised when an operation with the same idempotency key is already in progress or has a different payload."""
    pass


class IdempotencyManager:
    """
    Manages idempotency tokens, request hashing, and cached responses.
    """

    def __init__(self, default_ttl_seconds: float = 3600.0) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._records: Dict[str, IdempotencyRecord] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def _hash_payload(self, payload: Any) -> str:
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _make_storage_key(self, tenant_id: str, key: str) -> str:
        return f"{tenant_id}::{key}"

    async def _get_lock(self, storage_key: str) -> asyncio.Lock:
        async with self._global_lock:
            if storage_key not in self._locks:
                self._locks[storage_key] = asyncio.Lock()
            return self._locks[storage_key]

    async def acquire_or_get(
        self,
        tenant_id: str,
        idempotency_key: str,
        payload: Any,
        ttl_seconds: Optional[float] = None,
    ) -> tuple[bool, Optional[Dict[str, Any]]]:
        """
        Attempts to acquire an idempotency lease.
        Returns:
            (is_new_execution: bool, cached_response: Optional[Dict[str, Any]])
        Raises:
            IdempotencyConflictError if already in progress or payload hash mismatch.
        """
        storage_key = self._make_storage_key(tenant_id, idempotency_key)
        request_hash = self._hash_payload(payload)
        now = time.time()
        ttl = ttl_seconds or self.default_ttl_seconds

        lock = await self._get_lock(storage_key)
        async with lock:
            record = self._records.get(storage_key)

            if record:
                # Check expiration
                if now > record.expires_at:
                    # Expired, allow re-leasing
                    record = None
                else:
                    # Validate payload hash
                    if record.request_hash != request_hash:
                        raise IdempotencyConflictError(
                            f"Idempotency key '{idempotency_key}' was previously used with a different request payload."
                        )

                    if record.status == IdempotencyStatus.IN_PROGRESS:
                        raise IdempotencyConflictError(
                            f"Operation with idempotency key '{idempotency_key}' is currently IN_PROGRESS."
                        )

                    if record.status == IdempotencyStatus.COMPLETED:
                        return False, record.response_data

                    if record.status == IdempotencyStatus.FAILED:
                        # Allow retry on failure
                        pass

            # Create new lease
            self._records[storage_key] = IdempotencyRecord(
                key=idempotency_key,
                tenant_id=tenant_id,
                request_hash=request_hash,
                status=IdempotencyStatus.IN_PROGRESS,
                expires_at=now + ttl,
            )
            return True, None

    async def complete(
        self,
        tenant_id: str,
        idempotency_key: str,
        response_data: Dict[str, Any],
    ) -> None:
        storage_key = self._make_storage_key(tenant_id, idempotency_key)
        lock = await self._get_lock(storage_key)
        async with lock:
            record = self._records.get(storage_key)
            if record:
                record.status = IdempotencyStatus.COMPLETED
                record.response_data = response_data

    async def fail(
        self,
        tenant_id: str,
        idempotency_key: str,
        error_message: str,
    ) -> None:
        storage_key = self._make_storage_key(tenant_id, idempotency_key)
        lock = await self._get_lock(storage_key)
        async with lock:
            record = self._records.get(storage_key)
            if record:
                record.status = IdempotencyStatus.FAILED
                record.error_message = error_message
