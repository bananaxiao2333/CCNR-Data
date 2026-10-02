# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""数据访问层：只写 SQL，不写业务规则。

全部函数都接收调用方给的 `sqlite3.Connection`，因此服务层可以把多个写入
放进同一个事务（幂等行 + 业务行 + 审计行 + 变更流要么全成要么全不成）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from typing import cast

from ccnr_data.errors import failed_precondition, internal

__all__ = [
    "MAX_CHANGE_BATCH",
    "PURGE_BATCH",
    "append_change",
    "audit",
    "claim_idempotency",
    "fetch_changes",
    "get_player",
    "get_server_config",
    "insert_match_event",
    "insert_settlement",
    "insert_settlement_lines",
    "list_roles",
    "oldest_change_seq",
    "store_idempotency_response",
    "upsert_player",
    "upsert_role_override",
    "purge_audit_before",
    "purge_changes_before",
    "purge_events_before",
    "purge_idempotency_before",
    "upsert_server_config",
]

#: 一次 WatchChanges 最多取多少条变更，避免长事务与内存尖峰。
MAX_CHANGE_BATCH = 500

#: 轮换清理时单个 DELETE 的行数。分批是为了不让一次清理锁住写库太久。
PURGE_BATCH = 5000


def _one(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    return cast("sqlite3.Row | None", cursor.fetchone())


def _all(cursor: sqlite3.Cursor) -> list[sqlite3.Row]:
    return cast("list[sqlite3.Row]", cursor.fetchall())


# ---------------------------------------------------------------------------
# 玩家档案
# ---------------------------------------------------------------------------


def get_player(conn: sqlite3.Connection, player_uuid: str, server_id: str) -> sqlite3.Row | None:
    """按 (uuid, server) 取档案；不存在返回 None。"""
    return _one(
        conn.execute(
            "SELECT player_uuid, server_id, username, experience, level, version, updated_at "
            "FROM players WHERE player_uuid = ? AND server_id = ?",
            (player_uuid, server_id),
        )
    )


def upsert_player(
    conn: sqlite3.Connection,
    *,
    player_uuid: str,
    server_id: str,
    username: str,
    experience: int,
    level: int,
    updated_at: int,
) -> sqlite3.Row:
    """写入档案并 +1 版本号，返回写入后的行。

    `username` 传空串表示"不更新已有名字"——权威端在离线结算时拿不到玩家名，
    不能因此把库里已有的名字抹掉。
    """
    conn.execute(
        """
        INSERT INTO players (player_uuid, server_id, username, experience, level, version, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT (player_uuid, server_id) DO UPDATE SET
            username   = CASE WHEN excluded.username = '' THEN players.username
                              ELSE excluded.username END,
            experience = excluded.experience,
            level      = excluded.level,
            version    = players.version + 1,
            updated_at = excluded.updated_at
        """,
        (player_uuid, server_id, username, experience, level, updated_at),
    )
    row = get_player(conn, player_uuid, server_id)
    if row is None:  # pragma: no cover - upsert 成功后必然可读
        raise internal(f"写入玩家档案后读不到行：{player_uuid} @ {server_id}")
    return row


# ---------------------------------------------------------------------------
# 角色覆盖
# ---------------------------------------------------------------------------


def list_roles(conn: sqlite3.Connection, player_uuid: str, server_id: str) -> list[str]:
    """已启用的角色，按名字排序。"""
    rows = _all(
        conn.execute(
            "SELECT role FROM role_overrides "
            "WHERE player_uuid = ? AND server_id = ? AND enabled = 1 ORDER BY role",
            (player_uuid, server_id),
        )
    )
    return [str(r["role"]) for r in rows]


def upsert_role_override(
    conn: sqlite3.Connection,
    *,
    player_uuid: str,
    server_id: str,
    role: str,
    enabled: bool,
    source: str,
    updated_at: int,
) -> None:
    """写入一条角色开关。enabled=False 的行保留，用于区分"没给过"与"给过又收回"。"""
    conn.execute(
        """
        INSERT INTO role_overrides (player_uuid, server_id, role, enabled, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (player_uuid, server_id, role) DO UPDATE SET
            enabled    = excluded.enabled,
            source     = excluded.source,
            updated_at = excluded.updated_at
        """,
        (player_uuid, server_id, role, 1 if enabled else 0, source, updated_at),
    )


# ---------------------------------------------------------------------------
# 服务器策略
# ---------------------------------------------------------------------------


def get_server_config(conn: sqlite3.Connection, server_id: str) -> sqlite3.Row | None:
    return _one(
        conn.execute(
            "SELECT server_id, role_policy, config_json, version, updated_at "
            "FROM server_configs WHERE server_id = ?",
            (server_id,),
        )
    )


def upsert_server_config(
    conn: sqlite3.Connection,
    *,
    server_id: str,
    role_policy: str,
    config_json: str,
    updated_at: int,
) -> sqlite3.Row:
    conn.execute(
        """
        INSERT INTO server_configs (server_id, role_policy, config_json, version, updated_at)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT (server_id) DO UPDATE SET
            role_policy = excluded.role_policy,
            config_json = excluded.config_json,
            version     = server_configs.version + 1,
            updated_at  = excluded.updated_at
        """,
        (server_id, role_policy, config_json, updated_at),
    )
    row = get_server_config(conn, server_id)
    if row is None:  # pragma: no cover - upsert 成功后必然可读
        raise internal(f"写入服务器策略后读不到行：{server_id}")
    return row


# ---------------------------------------------------------------------------
# 结算
# ---------------------------------------------------------------------------


def insert_settlement(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    server_id: str,
    player_uuid: str,
    match_id: str,
    reason: str,
    xp_before: int,
    xp_after: int,
    level_before: int,
    level_after: int,
    gain: int,
    diverged: bool,
    settled_at: int,
    created_at: int,
) -> int:
    """写入结算头，返回 settlement id。"""
    cursor = conn.execute(
        """
        INSERT INTO settlements (request_id, server_id, player_uuid, match_id, reason,
                                 xp_before, xp_after, level_before, level_after, gain,
                                 diverged, settled_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request_id,
            server_id,
            player_uuid,
            match_id,
            reason,
            xp_before,
            xp_after,
            level_before,
            level_after,
            gain,
            1 if diverged else 0,
            settled_at,
            created_at,
        ),
    )
    return int(cursor.lastrowid or 0)


def insert_settlement_lines(
    conn: sqlite3.Connection,
    settlement_id: int,
    lines: Sequence[tuple[int, str, str, int]],
) -> None:
    """批量写入结算明细。入参为 (line_no, rule_id, title, value)。"""
    if not lines:
        return
    conn.executemany(
        "INSERT INTO settlement_lines (settlement_id, line_no, rule_id, title, value) VALUES (?, ?, ?, ?, ?)",
        [(settlement_id, no, rule, title, value) for no, rule, title, value in lines],
    )


# ---------------------------------------------------------------------------
# 事件流水
# ---------------------------------------------------------------------------


def insert_match_event(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    server_id: str,
    kind: str,
    match_id: str,
    phase_id: str,
    previous_phase_id: str,
    definition_id: str,
    actor_uuid: str,
    target_uuid: str,
    payload_json: str,
    occurred_at: int,
    created_at: int,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO match_events (request_id, server_id, kind, match_id, phase_id, previous_phase_id,
                                  definition_id, actor_uuid, target_uuid, payload_json,
                                  occurred_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request_id,
            server_id,
            kind,
            match_id,
            phase_id,
            previous_phase_id,
            definition_id,
            actor_uuid,
            target_uuid,
            payload_json,
            occurred_at,
            created_at,
        ),
    )
    return int(cursor.lastrowid or 0)


# ---------------------------------------------------------------------------
# 幂等
# ---------------------------------------------------------------------------


def claim_idempotency(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    method: str,
    request_hash: str,
    created_at: int,
) -> str | None:
    """认领 request_id。

    返回 `None` 表示"本次由我执行"；返回字符串表示"之前已经执行过"，内容是缓存的响应 JSON。
    同一个 request_id 配不同载荷 → FAILED_PRECONDITION（宁可报错，也不回放一个语义不同的结果）。
    """
    cursor = conn.execute(
        "INSERT INTO idempotency (request_id, method, request_hash, response_json, created_at) "
        "VALUES (?, ?, ?, '{}', ?) ON CONFLICT (request_id) DO NOTHING",
        (request_id, method, request_hash, created_at),
    )
    if cursor.rowcount == 1:
        return None

    row = _one(
        conn.execute(
            "SELECT method, request_hash, response_json FROM idempotency WHERE request_id = ?",
            (request_id,),
        )
    )
    if row is None:  # pragma: no cover - 冲突分支必然读得到
        raise internal(f"幂等记录冲突但读不到行：{request_id}")
    if str(row["method"]) != method or str(row["request_hash"]) != request_hash:
        raise failed_precondition(
            f"request_id {request_id!r} 已被 {row['method']} 以不同载荷使用；幂等键必须唯一标识一次业务意图"
        )
    cached = str(row["response_json"])
    if cached == "{}":  # pragma: no cover - 同事务提交，不会留下半条记录
        raise internal(f"幂等记录不完整（响应未落盘）：{request_id}")
    return cached


def store_idempotency_response(conn: sqlite3.Connection, request_id: str, response_json: str) -> None:
    conn.execute(
        "UPDATE idempotency SET response_json = ? WHERE request_id = ?",
        (response_json, request_id),
    )


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------


def audit(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    target: str,
    request_id: str,
    before_json: str | None,
    after_json: str | None,
    created_at: int,
) -> None:
    conn.execute(
        "INSERT INTO audit_log (actor, action, target, request_id, before_json, after_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (actor, action, target, request_id, before_json, after_json, created_at),
    )


# ---------------------------------------------------------------------------
# 变更流
# ---------------------------------------------------------------------------


def append_change(
    conn: sqlite3.Connection,
    *,
    change_type: str,
    server_id: str,
    player_uuid: str,
    version: int,
    payload_json: str,
    occurred_at: int,
) -> int:
    """追加一条变更，返回全局单调序号。"""
    cursor = conn.execute(
        "INSERT INTO change_log (change_type, server_id, player_uuid, version, payload_json, occurred_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (change_type, server_id, player_uuid, version, payload_json, occurred_at),
    )
    return int(cursor.lastrowid or 0)


def fetch_changes(
    conn: sqlite3.Connection,
    *,
    server_id: str,
    since_seq: int,
    limit: int = MAX_CHANGE_BATCH,
) -> list[sqlite3.Row]:
    """取序号大于 since_seq 的变更；server_id 为空串表示不过滤服务器。"""
    sql = (
        "SELECT seq, change_type, server_id, player_uuid, version, payload_json, occurred_at "
        "FROM change_log WHERE seq > ?"
    )
    params: list[object] = [since_seq]
    if server_id:
        sql += " AND server_id = ?"
        params.append(server_id)
    sql += " ORDER BY seq LIMIT ?"
    params.append(limit)
    return _all(conn.execute(sql, params))


def iter_lines(conn: sqlite3.Connection, settlement_id: int) -> Iterable[sqlite3.Row]:
    """读某次结算的明细（测试与排障用）。"""
    sql = (
        "SELECT line_no, rule_id, title, value FROM settlement_lines WHERE settlement_id = ? ORDER BY line_no"
    )
    return cast("Iterable[sqlite3.Row]", iter(_all(conn.execute(sql, (settlement_id,)))))


# ---------------------------------------------------------------------------
# 日志轮换
# ---------------------------------------------------------------------------


def _purge(conn: sqlite3.Connection, sql: str, cutoff_ms: int, limit: int) -> int:
    cursor = conn.execute(sql, (cutoff_ms, limit))
    return int(cursor.rowcount if cursor.rowcount >= 0 else 0)


def purge_events_before(conn: sqlite3.Connection, cutoff_ms: int, *, limit: int = PURGE_BATCH) -> int:
    """删除 occurred_at 早于 cutoff 的事件流水，返回删除行数。"""
    return _purge(
        conn,
        "DELETE FROM match_events WHERE id IN ("
        "  SELECT id FROM match_events WHERE occurred_at < ? ORDER BY occurred_at LIMIT ?)",
        cutoff_ms,
        limit,
    )


def purge_changes_before(conn: sqlite3.Connection, cutoff_ms: int, *, limit: int = PURGE_BATCH) -> int:
    """删除 occurred_at 早于 cutoff 的变更流。落后于该窗口的订阅方会丢事件。"""
    return _purge(
        conn,
        "DELETE FROM change_log WHERE seq IN ("
        "  SELECT seq FROM change_log WHERE occurred_at < ? ORDER BY occurred_at LIMIT ?)",
        cutoff_ms,
        limit,
    )


def purge_audit_before(conn: sqlite3.Connection, cutoff_ms: int, *, limit: int = PURGE_BATCH) -> int:
    """删除 created_at 早于 cutoff 的审计日志。"""
    return _purge(
        conn,
        "DELETE FROM audit_log WHERE id IN ("
        "  SELECT id FROM audit_log WHERE created_at < ? ORDER BY created_at LIMIT ?)",
        cutoff_ms,
        limit,
    )


def purge_idempotency_before(conn: sqlite3.Connection, cutoff_ms: int, *, limit: int = PURGE_BATCH) -> int:
    """删除 created_at 早于 cutoff 的幂等键。

    保留窗口必须远长于任何现实的重试窗口：删早了，迟到的重放会被当成新请求再执行一次。
    """
    return _purge(
        conn,
        "DELETE FROM idempotency WHERE request_id IN ("
        "  SELECT request_id FROM idempotency WHERE created_at < ? ORDER BY created_at LIMIT ?)",
        cutoff_ms,
        limit,
    )


def oldest_change_seq(conn: sqlite3.Connection) -> int:
    """变更流里现存的最小序号；空表返回 0。用于判断订阅游标是否已经落后到丢事件。"""
    row = _one(conn.execute("SELECT MIN(seq) AS oldest FROM change_log"))
    if row is None or row["oldest"] is None:
        return 0
    return int(row["oldest"])
