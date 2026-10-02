# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""服务装配：健康检查、模式 bootstrap、版本护栏。"""

from __future__ import annotations

from pathlib import Path

import grpc
import pytest
from grpc_health.v1 import health_pb2, health_pb2_grpc

from ccnr_data.db import SCHEMA_VERSION, Database
from ccnr_data.errors import DataServiceError
from ccnr_data.server import SERVICE_NAME, ServerHandle

EXPECTED_TABLES = {
    "schema_meta",
    "players",
    "role_overrides",
    "server_configs",
    "settlements",
    "settlement_lines",
    "match_events",
    "idempotency",
    "audit_log",
    "change_log",
}


def test_schema_created_on_open(db: Database) -> None:
    conn = db.connection()
    tables = {
        str(r["name"]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    assert tables >= EXPECTED_TABLES
    assert (
        conn.execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()["version"] == SCHEMA_VERSION
    )


def test_wal_and_foreign_keys_enabled(db: Database) -> None:
    conn = db.connection()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_open_is_idempotent(db: Database) -> None:
    db.open()
    db.open()
    assert db.is_open


def test_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "ccnr.db"
    database = Database(nested)
    database.open()
    try:
        assert nested.exists()
    finally:
        database.close()


def test_schema_version_mismatch_refuses_to_start(tmp_path: Path) -> None:
    """版本对不上必须拒绝启动，绝不自作主张改库。"""
    path = tmp_path / "mismatch.db"
    first = Database(path)
    first.open()
    with first.write() as conn:
        conn.execute("UPDATE schema_meta SET version = 99 WHERE id = 1")
    first.close()

    second = Database(path)
    with pytest.raises(DataServiceError) as err:
        second.open()
    assert "模式版本不匹配" in err.value.detail


def test_health_reports_serving(server: ServerHandle, channel) -> None:
    health = health_pb2_grpc.HealthStub(channel)  # type: ignore[no-untyped-call]
    assert health.Check(health_pb2.HealthCheckRequest()).status == health_pb2.HealthCheckResponse.SERVING
    assert (
        health.Check(health_pb2.HealthCheckRequest(service=SERVICE_NAME)).status
        == health_pb2.HealthCheckResponse.SERVING
    )


def test_stop_takes_service_offline(server: ServerHandle, channel) -> None:
    """stop() 之后端口不再服务：负载均衡会把流量挪走，这正是要先摘健康检查的目的。"""
    health = health_pb2_grpc.HealthStub(channel)  # type: ignore[no-untyped-call]
    server.stop(grace=0)
    with pytest.raises(grpc.RpcError) as err:
        health.Check(health_pb2.HealthCheckRequest(service=SERVICE_NAME))
    assert err.value.code() == grpc.StatusCode.UNAVAILABLE
