# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""状态变更审计。事件不写这里。"""

from __future__ import annotations

from sqlalchemy import insert
from sqlalchemy.orm import Session

from ccnr_data.models import AuditLog
from ccnr_data.repositories._common import PURGE_BATCH, purge_before, table_of

__all__ = ["audit", "purge_audit_before"]


def audit(
    session: Session,
    *,
    actor: str,
    action: str,
    target: str,
    request_id: str,
    before_json: str | None,
    after_json: str | None,
    created_at: int,
) -> None:
    table = table_of(AuditLog)
    session.execute(
        insert(table).values(
            actor=actor,
            action=action,
            target=target,
            request_id=request_id,
            before_json=before_json,
            after_json=after_json,
            created_at=created_at,
        )
    )


def purge_audit_before(session: Session, cutoff_ms: int, *, limit: int = PURGE_BATCH) -> int:
    """删除 created_at 早于 cutoff 的审计日志。"""
    return purge_before(
        session,
        table_of(AuditLog),
        id_column="id",
        time_column="created_at",
        cutoff_ms=cutoff_ms,
        limit=limit,
    )
