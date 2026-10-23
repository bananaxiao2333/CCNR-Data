# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""日志轮换：保留天数与过期清理。"""

from __future__ import annotations

import sqlite3

from ccnr_data import repositories as repo
from ccnr_data.clock import now_ms
from ccnr_data.db import Database
from ccnr_data.retention import MS_PER_DAY, PurgeReport, RetentionPolicy, RetentionWorker, purge_once
from dbutil import raw_connection
from moddata.v1 import moddata_pb2
from support import SERVER_ID, apply_request, event_request, new_uuid

KIND = moddata_pb2.EventKind


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])  # noqa: S608 - 表名来自测试常量


def _seed_event(stub, *, occurred_at: int) -> None:
    stub.RecordEvent(event_request(KIND.EVENT_KIND_ROUND_ENDED, occurred_at=occurred_at))


def test_purge_removes_only_expired(stub, db: Database) -> None:
    now = now_ms()
    _seed_event(stub, occurred_at=now - 40 * MS_PER_DAY)  # 过期
    _seed_event(stub, occurred_at=now - 1 * MS_PER_DAY)  # 保留
    stub.ApplyExperience(apply_request(new_uuid(), 1))  # 审计行的来源（事件不写审计）

    report = purge_once(
        db, RetentionPolicy(event_days=30, change_days=30, audit_days=30, idempotency_days=30), now=now
    )

    assert report.events == 1
    assert report.changes == 1  # 过期事件的变更流同样被清
    # 审计按**入账时刻**计时（不是事件时刻），刚写的那条不该过期。
    assert report.audit == 0
    conn = raw_connection(db)
    assert _count(conn, "match_events") == 1
    assert _count(conn, "change_log") == 2
    assert _count(conn, "audit_log") == 1


def test_audit_expires_by_write_time(stub, db: Database) -> None:
    now = now_ms()
    stub.ApplyExperience(apply_request(new_uuid(), 1))

    report = purge_once(
        db,
        RetentionPolicy(event_days=0, change_days=0, audit_days=30, idempotency_days=0),
        now=now + 40 * MS_PER_DAY,
    )

    assert report.audit == 1
    conn = raw_connection(db)
    assert _count(conn, "audit_log") == 0
    assert _count(conn, "change_log") == 1  # 变更流 0=永久，不受影响


def test_zero_days_means_keep_forever(stub, db: Database) -> None:
    now = now_ms()
    _seed_event(stub, occurred_at=now - 400 * MS_PER_DAY)

    policy = RetentionPolicy(event_days=0, change_days=0, audit_days=0, idempotency_days=0)
    assert not policy.enabled()
    assert purge_once(db, policy, now=now) == PurgeReport()

    conn = raw_connection(db)
    assert _count(conn, "match_events") == 1
    assert _count(conn, "change_log") == 1


def test_policy_can_target_a_single_table(stub, db: Database) -> None:
    now = now_ms()
    _seed_event(stub, occurred_at=now - 40 * MS_PER_DAY)

    report = purge_once(
        db, RetentionPolicy(event_days=30, change_days=0, audit_days=0, idempotency_days=0), now=now
    )

    assert report.events == 1
    assert report.changes == 0
    conn = raw_connection(db)
    assert _count(conn, "change_log") == 1  # 变更流按 0=永久 保留


def test_business_tables_are_never_purged(stub, db: Database) -> None:
    """玩家档案与结算是业务记录，不是日志。"""
    player = new_uuid()
    stub.ApplyExperience(apply_request(player, 5))
    stub.RecordSettlement(
        moddata_pb2.RecordSettlementRequest(
            request_id="req-settle-keep",
            server_id=SERVER_ID,
            player_uuid=player,
            reason="command",
            xp_before=5,
            xp_after=5,
            level_before=0,
            level_after=0,
            gain=0,
        )
    )

    now = now_ms()
    # 幂等键单独设 0=永久，验证"它是否被删"只取决于它自己的窗口。
    purge_once(
        db,
        RetentionPolicy(event_days=1, change_days=1, audit_days=1, idempotency_days=0),
        now=now + 400 * MS_PER_DAY,
    )

    conn = raw_connection(db)
    assert _count(conn, "players") == 1
    assert _count(conn, "settlements") == 1
    assert _count(conn, "idempotency") == 2


def test_idempotency_expires_on_its_own_window(stub, db: Database) -> None:
    """幂等键必须能被清理（否则每个写入都留一行，是第二大的表）；
    但默认窗口 30 天远长于任何重试窗口，不会误判迟到重放。"""
    stub.ApplyExperience(apply_request(new_uuid(), 1))
    assert _count(raw_connection(db), "idempotency") == 1

    purge_once(
        db,
        RetentionPolicy(event_days=0, change_days=0, audit_days=0, idempotency_days=30),
        now=now_ms() + 31 * MS_PER_DAY,
    )
    assert _count(raw_connection(db), "idempotency") == 0


def test_purge_is_batched(db: Database) -> None:
    """单批上限之外的行要分多次删完，且中途不锁死写库。"""
    now = now_ms()
    old = now - 100 * MS_PER_DAY
    total = repo.PURGE_BATCH + 25
    conn = raw_connection(db)
    conn.executemany(
        "INSERT INTO match_events (request_id, server_id, kind, match_id, phase_id, previous_phase_id, "
        "definition_id, actor_uuid, target_uuid, payload_json, occurred_at, created_at) "
        "VALUES (?, ?, ?, '', '', '', '', '', '', '{}', ?, ?)",
        [(f"req-{i}", SERVER_ID, "EVENT_KIND_ROUND_ENDED", old, old) for i in range(total)],
    )
    conn.commit()

    report = purge_once(
        db, RetentionPolicy(event_days=1, change_days=0, audit_days=0, idempotency_days=1), now=now
    )
    assert report.events == total
    assert _count(conn, "match_events") == 0


def test_report_truthiness() -> None:
    assert not PurgeReport()
    assert PurgeReport(events=1)


def test_worker_starts_and_stops(db: Database) -> None:
    policy = RetentionPolicy(event_days=1, change_days=1, audit_days=1, idempotency_days=1)
    worker = RetentionWorker(db, policy, interval_seconds=3600)
    worker.start()
    worker.stop(timeout=5)
    # 启动即跑过一轮：没有过期数据时不应留下任何行
    assert _count(raw_connection(db), "match_events") == 0


def test_disabled_worker_does_not_start_thread(db: Database) -> None:
    worker = RetentionWorker(
        db, RetentionPolicy(event_days=0, change_days=0, audit_days=0, idempotency_days=0)
    )
    worker.start()
    worker.stop()
    assert not worker.is_running


def test_describe_marks_forever() -> None:
    assert (
        RetentionPolicy(0, 7, 365, 30).describe()
        == "事件=永久 变更流=7 天 审计=365 天 幂等键=30 天 代理事件=永久 会话=永久"
    )
