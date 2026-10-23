# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""变更流：供 WatchChanges 做断线续传。"""

from __future__ import annotations

from sqlalchemy import func, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from ccnr_data.models import ChangeLog
from ccnr_data.repositories._common import PURGE_BATCH, inserted_id, purge_before, table_of

__all__ = [
    "MAX_CHANGE_BATCH",
    "append_change",
    "fetch_changes",
    "oldest_change_seq",
    "purge_changes_before",
]

#: 一次 WatchChanges 最多取多少条变更，避免长事务与内存尖峰。
MAX_CHANGE_BATCH = 500


def append_change(
    session: Session,
    *,
    change_type: str,
    server_id: str,
    player_uuid: str,
    version: int,
    payload_json: str,
    occurred_at: int,
) -> int:
    """追加一条变更，返回全局单调序号。"""
    table = table_of(ChangeLog)
    result = session.execute(
        insert(table).values(
            change_type=change_type,
            server_id=server_id,
            player_uuid=player_uuid,
            version=version,
            payload_json=payload_json,
            occurred_at=occurred_at,
        )
    )
    return inserted_id(result)


def fetch_changes(
    session: Session,
    *,
    server_id: str,
    since_seq: int,
    limit: int = MAX_CHANGE_BATCH,
) -> list[RowMapping]:
    """取序号大于 since_seq 的变更；server_id 为空串表示不过滤服务器。"""
    table = table_of(ChangeLog)
    statement = select(table).where(table.c.seq > since_seq)
    if server_id:
        statement = statement.where(table.c.server_id == server_id)
    statement = statement.order_by(table.c.seq).limit(limit)
    return list(session.execute(statement).mappings())


def oldest_change_seq(session: Session) -> int:
    """变更流里现存的最小序号；空表返回 0。"""
    table = table_of(ChangeLog)
    value = session.execute(select(func.min(table.c.seq))).scalar()
    return 0 if value is None else int(value)


def purge_changes_before(session: Session, cutoff_ms: int, *, limit: int = PURGE_BATCH) -> int:
    """删除 occurred_at 早于 cutoff 的变更流。落后于该窗口的订阅方会丢事件。"""
    return purge_before(
        session,
        table_of(ChangeLog),
        id_column="seq",
        time_column="occurred_at",
        cutoff_ms=cutoff_ms,
        limit=limit,
    )
