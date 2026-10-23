# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""Casdoor Device Code 登录会话。"""

from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from ccnr_data.models import DeviceLogin
from ccnr_data.repositories._common import (
    PURGE_BATCH,
    affected_rows,
    table_of,
)
from ccnr_data.repositories._common import (
    purge_before as _purge_before,
)

__all__ = ["create", "get", "mark", "pending", "purge_before"]

PENDING = "PENDING"
APPROVED = "APPROVED"
DENIED = "DENIED"
EXPIRED = "EXPIRED"


def create(
    session: Session,
    *,
    login_id: str,
    device_code: str,
    user_code: str,
    player_uuid: str,
    username: str,
    proxy_id: str,
    interval_s: int,
    created_at: int,
    expires_at: int,
) -> None:
    session.execute(
        insert(table_of(DeviceLogin)).values(
            id=login_id,
            device_code=device_code,
            user_code=user_code,
            player_uuid=player_uuid,
            username=username,
            proxy_id=proxy_id,
            status=PENDING,
            interval_s=interval_s,
            created_at=created_at,
            expires_at=expires_at,
            approved_at=None,
            casdoor_user_id="",
            message="",
        )
    )


def get(session: Session, login_id: str) -> RowMapping | None:
    table = table_of(DeviceLogin)
    return session.execute(select(table).where(table.c.id == login_id)).mappings().first()


def pending(session: Session, *, now: int, limit: int = 50) -> list[RowMapping]:
    table = table_of(DeviceLogin)
    return list(
        session.execute(
            select(table)
            .where(table.c.status == PENDING, table.c.expires_at > now)
            .order_by(table.c.created_at)
            .limit(limit)
        ).mappings()
    )


def mark(
    session: Session,
    login_id: str,
    status: str,
    *,
    casdoor_user_id: str = "",
    message: str = "",
    now: int | None = None,
) -> bool:
    values: dict[str, object] = {"status": status, "message": message}
    if casdoor_user_id:
        values["casdoor_user_id"] = casdoor_user_id
    if status == APPROVED and now is not None:
        values["approved_at"] = now
    result = session.execute(
        update(table_of(DeviceLogin)).where(table_of(DeviceLogin).c.id == login_id).values(**values)
    )
    return affected_rows(result) == 1


def purge_before(session: Session, cutoff_ms: int, *, limit: int = PURGE_BATCH) -> int:
    return _purge_before(
        session,
        table_of(DeviceLogin),
        id_column="id",
        time_column="created_at",
        cutoff_ms=cutoff_ms,
        limit=limit,
    )
