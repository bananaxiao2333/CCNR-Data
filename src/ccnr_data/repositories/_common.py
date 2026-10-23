# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""仓储层共用的小工具。

轮换清理统一走「按主键子查询 + 批量 DELETE」：SQLite 与 PostgreSQL 都支持，
且不会一次锁住整表。
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import Table, delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

__all__ = ["PURGE_BATCH", "affected_rows", "inserted_id", "purge_before", "table_of"]

#: 单次 DELETE 的行数；分批是为了不让一次清理长时间持有写锁。
PURGE_BATCH = 5000


def table_of(model: object) -> Table:
    """取 ORM 模型的 Table；显式收窄类型，避免 insert/update 被 mypy 判成 FromClause。"""
    return cast(Table, cast(Any, model).__table__)


def inserted_id(result: object) -> int:
    """DML 结果的主键。SQLAlchemy 的 Result 基类没有这个属性，CursorResult 才有。"""
    return int(cast(Any, result).inserted_primary_key[0])


def affected_rows(result: object) -> int:
    return int(getattr(cast(CursorResult[Any], result), "rowcount", 0) or 0)


def purge_before(
    session: Session,
    table: Table,
    *,
    id_column: str,
    time_column: str,
    cutoff_ms: int,
    limit: int = PURGE_BATCH,
) -> int:
    """删除 time_column 早于 cutoff 的至多 limit 行，返回删除行数。"""
    ids = (
        select(table.c[id_column])
        .where(table.c[time_column] < cutoff_ms)
        .order_by(table.c[time_column])
        .limit(limit)
    )
    result = session.execute(delete(table).where(table.c[id_column].in_(ids)))
    return affected_rows(result)
