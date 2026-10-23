# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""代理会话与登录失败事件。"""

from __future__ import annotations

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from ccnr_data.models import ProxyEvent, ProxySession
from ccnr_data.repositories._common import PURGE_BATCH, affected_rows, table_of

__all__ = [
    "count_online",
    "deny_stats",
    "end_session",
    "get_session",
    "heartbeat",
    "insert_proxy_event",
    "list_online",
    "purge_proxy_events_before",
    "purge_sessions_before",
    "reap_stale",
    "sessions_between",
    "start_session",
    "switch_server",
]


def start_session(
    session: Session,
    *,
    session_id: str,
    player_uuid: str,
    username: str,
    proxy_id: str,
    server_id: str,
    client_version: str,
    protocol_version: int,
    now: int,
) -> None:
    """会话开始；重放时只刷新 last_seen，不重置 started_at。"""
    table = table_of(ProxySession)
    exists = session.execute(select(table.c.session_id).where(table.c.session_id == session_id)).first()
    if exists is None:
        session.execute(
            insert(table).values(
                session_id=session_id,
                player_uuid=player_uuid,
                username=username,
                proxy_id=proxy_id,
                server_id=server_id,
                started_at=now,
                last_seen_at=now,
                ended_at=None,
                end_reason="",
                client_version=client_version,
                protocol_version=protocol_version,
                created_at=now,
            )
        )
    else:
        session.execute(
            update(table).where(table.c.session_id == session_id).values(last_seen_at=now, username=username)
        )


def insert_proxy_event(
    session: Session,
    *,
    request_id: str,
    kind: str,
    session_id: str,
    player_uuid: str,
    username: str,
    server_id: str,
    from_server_id: str,
    occurred_at: int,
    received_at: int,
    end_reason: str,
    deny_reason: str,
) -> None:
    table = table_of(ProxyEvent)
    session.execute(
        insert(table).values(
            request_id=request_id,
            kind=kind,
            session_id=session_id,
            player_uuid=player_uuid,
            username=username,
            server_id=server_id,
            from_server_id=from_server_id,
            occurred_at=occurred_at,
            received_at=received_at,
            end_reason=end_reason,
            deny_reason=deny_reason,
        )
    )


def get_session(session: Session, session_id: str) -> RowMapping | None:
    table = table_of(ProxySession)
    return session.execute(select(table).where(table.c.session_id == session_id)).mappings().first()


def heartbeat(session: Session, session_id: str, now: int) -> bool:
    """刷新 last_seen；已结束的会话不再复活。"""
    table = table_of(ProxySession)
    result = session.execute(
        update(table)
        .where(table.c.session_id == session_id, table.c.ended_at.is_(None))
        .values(last_seen_at=now)
    )
    return affected_rows(result) == 1


def switch_server(session: Session, session_id: str, server_id: str, now: int) -> bool:
    table = table_of(ProxySession)
    result = session.execute(
        update(table)
        .where(table.c.session_id == session_id, table.c.ended_at.is_(None))
        .values(server_id=server_id, last_seen_at=now)
    )
    return affected_rows(result) == 1


def end_session(session: Session, session_id: str, now: int, reason: str) -> bool:
    """结束会话；重复结束不覆盖第一次的时间与原因。"""
    table = table_of(ProxySession)
    result = session.execute(
        update(table)
        .where(table.c.session_id == session_id, table.c.ended_at.is_(None))
        .values(ended_at=now, last_seen_at=now, end_reason=reason)
    )
    return affected_rows(result) == 1


def list_online(session: Session, *, cutoff: int, server_id: str, limit: int) -> list[RowMapping]:
    table = table_of(ProxySession)
    statement = select(table).where(table.c.ended_at.is_(None), table.c.last_seen_at >= cutoff)
    if server_id:
        statement = statement.where(table.c.server_id == server_id)
    statement = statement.order_by(table.c.started_at).limit(limit)
    return list(session.execute(statement).mappings())


def count_online(session: Session, *, cutoff: int, server_id: str) -> int:
    """在线总数（不受 list_online 的 limit 截断影响）。"""
    table = table_of(ProxySession)
    statement = (
        select(func.count())
        .select_from(table)
        .where(table.c.ended_at.is_(None), table.c.last_seen_at >= cutoff)
    )
    if server_id:
        statement = statement.where(table.c.server_id == server_id)
    return int(session.execute(statement).scalar_one())


def sessions_between(
    session: Session, *, server_id: str, player_uuid: str = "", from_ms: int = 0, to_ms: int = 0
) -> list[RowMapping]:
    """与 [from, to] 有交集的会话。from/to 为 0 表示不限。"""
    table = table_of(ProxySession)
    # 必须是 COALESCE，不能是 OR：SQLite 的 OR 返回 0/1，会把时间窗过滤全裁掉。
    end = func.coalesce(table.c.ended_at, table.c.last_seen_at)
    statement = select(table)
    if server_id:
        statement = statement.where(table.c.server_id == server_id)
    if player_uuid:
        statement = statement.where(table.c.player_uuid == player_uuid)
    if from_ms > 0:
        statement = statement.where(end >= from_ms)
    if to_ms > 0:
        statement = statement.where(table.c.started_at <= to_ms)
    statement = statement.order_by(table.c.started_at)
    return list(session.execute(statement).mappings())


def reap_stale(session: Session, *, cutoff: int, now: int) -> int:
    """把长时间没有心跳的会话收尾，避免代理崩溃后永远在线。"""
    table = table_of(ProxySession)
    result = session.execute(
        update(table)
        .where(table.c.ended_at.is_(None), table.c.last_seen_at < cutoff)
        .values(ended_at=table.c.last_seen_at, end_reason="timeout")
    )
    return affected_rows(result)


def purge_sessions_before(session: Session, cutoff_ms: int, *, limit: int = PURGE_BATCH) -> int:
    """只清理已结束的会话；在线会话永不被轮换删掉。"""
    table = table_of(ProxySession)
    ids = (
        select(table.c.session_id)
        .where(table.c.ended_at.is_not(None), table.c.ended_at < cutoff_ms)
        .order_by(table.c.ended_at)
        .limit(limit)
    )
    result = session.execute(delete(table).where(table.c.session_id.in_(ids)))
    return affected_rows(result)


def deny_stats(session: Session, *, server_id: str, from_ms: int, to_ms: int) -> list[RowMapping]:
    """登录失败按原因分组。"""
    from sqlalchemy import func

    table = table_of(ProxyEvent)
    statement = (
        select(table.c.deny_reason, func.count().label("count"))
        .where(table.c.kind == "LOGIN_DENIED")
        .group_by(table.c.deny_reason)
    )
    if server_id:
        statement = statement.where(table.c.server_id == server_id)
    if from_ms > 0:
        statement = statement.where(table.c.occurred_at >= from_ms)
    if to_ms > 0:
        statement = statement.where(table.c.occurred_at <= to_ms)
    return list(session.execute(statement).mappings())


def purge_proxy_events_before(session: Session, cutoff_ms: int, *, limit: int = PURGE_BATCH) -> int:
    table = table_of(ProxyEvent)
    ids = select(table.c.id).where(table.c.occurred_at < cutoff_ms).order_by(table.c.occurred_at).limit(limit)
    result = session.execute(delete(table).where(table.c.id.in_(ids)))
    return affected_rows(result)
