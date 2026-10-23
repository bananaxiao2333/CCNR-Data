# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""幂等键与缓存响应。"""

from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ccnr_data.errors import failed_precondition, internal
from ccnr_data.models import Idempotency
from ccnr_data.repositories._common import PURGE_BATCH, purge_before, table_of

__all__ = [
    "claim_idempotency",
    "purge_idempotency_before",
    "store_idempotency_response",
]


def claim_idempotency(
    session: Session,
    *,
    request_id: str,
    method: str,
    request_hash: str,
    created_at: int,
) -> str | None:
    """认领 request_id。

    返回 None 表示「本次由我执行」；返回字符串表示「之前已经执行过」，内容是缓存的响应 JSON。
    同键不同载荷 → FAILED_PRECONDITION（宁可报错，也不回放语义不同的结果）。
    """
    table = table_of(Idempotency)
    try:
        # 用 SAVEPOINT 隔离唯一键冲突：插入失败只回滚这一个点，外层事务仍然可用。
        with session.begin_nested():
            session.execute(
                insert(table).values(
                    request_id=request_id,
                    method=method,
                    request_hash=request_hash,
                    response_json="{}",
                    created_at=created_at,
                )
            )
        return None
    except IntegrityError:
        pass

    row = (
        session.execute(
            select(table.c.method, table.c.request_hash, table.c.response_json).where(
                table.c.request_id == request_id
            )
        )
        .mappings()
        .first()
    )
    if row is None:  # pragma: no cover - 冲突后必然读得到
        raise internal(f"幂等记录冲突但读不到行：{request_id}")
    if str(row["method"]) != method or str(row["request_hash"]) != request_hash:
        raise failed_precondition(
            f"request_id {request_id!r} 已被 {row['method']} 以不同载荷使用；幂等键必须唯一标识一次业务意图"
        )
    cached = str(row["response_json"])
    if cached == "{}":  # pragma: no cover - 同事务提交，不会留下半条记录
        raise internal(f"幂等记录不完整（响应未落盘）：{request_id}")
    return cached


def store_idempotency_response(session: Session, request_id: str, response_json: str) -> None:
    table = table_of(Idempotency)
    session.execute(update(table).where(table.c.request_id == request_id).values(response_json=response_json))


def purge_idempotency_before(session: Session, cutoff_ms: int, *, limit: int = PURGE_BATCH) -> int:
    """删除 created_at 早于 cutoff 的幂等键。

    保留窗口必须远长于任何现实的重试窗口：删早了，迟到的重放会被当成新请求再执行一次。
    """
    return purge_before(
        session,
        table_of(Idempotency),
        id_column="request_id",
        time_column="created_at",
        cutoff_ms=cutoff_ms,
        limit=limit,
    )
