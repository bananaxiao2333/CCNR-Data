# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""服务装配：迁移版本、PRAGMA、目录创建、健康检查。"""

from __future__ import annotations

from pathlib import Path

import pytest
from grpc_health.v1 import health_pb2, health_pb2_grpc

from ccnr_data.db import Database
from ccnr_data.errors import DataServiceError
from ccnr_data.server import SERVICE_NAME, ServerHandle
from dbutil import raw_connection, upgrade_database

EXPECTED_TABLES = {
    "alembic_version",
    "players",
    "role_overrides",
    "server_configs",
    "settlements",
    "settlement_lines",
    "match_events",
    "idempotency",
    "audit_log",
    "change_log",
    "player_identities",
    "access_rules",
    "access_policies",
    "proxy_sessions",
    "proxy_events",
}


def test_schema_created_by_migrations(db: Database) -> None:
    conn = raw_connection(db)
    try:
        tables = {
            str(row["name"]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()
    assert tables >= EXPECTED_TABLES


def test_wal_and_foreign_keys_enabled(db: Database) -> None:
    conn = raw_connection(db)
    try:
        # journal_mode 是库级设置；foreign_keys 是连接级设置，必须看服务自己的连接。
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()
    with db.read() as session:
        enabled = session.connection().exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert enabled == 1


def test_open_is_idempotent(db: Database) -> None:
    db.open()
    db.open()
    assert db.is_open


def test_creates_parent_directory_before_failing_on_missing_migration(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "ccnr.db"
    database = Database(nested)
    try:
        with pytest.raises(DataServiceError):
            database.open()
        assert nested.parent.is_dir()
    finally:
        database.close()


def test_migration_mismatch_refuses_to_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """版本对不上必须拒绝启动，绝不自作主张改库。"""
    path = tmp_path / "mismatch.db"
    monkeypatch.setenv("CCNR_DATA_DATABASE_URL", f"sqlite+pysqlite:///{path}")
    upgrade_database(path)
    conn = raw_connection(Database(path))
    try:
        conn.execute("UPDATE alembic_version SET version_num = '0001_baseline'")
        conn.commit()
    finally:
        conn.close()

    database = Database(path)
    try:
        with pytest.raises(DataServiceError) as err:
            database.open()
        assert "迁移版本不匹配" in err.value.detail
    finally:
        database.close()


def test_health_reports_serving(server: ServerHandle, channel) -> None:
    health = health_pb2_grpc.HealthStub(channel)  # type: ignore[no-untyped-call]
    serving = health_pb2.HealthCheckResponse.SERVING
    assert health.Check(health_pb2.HealthCheckRequest(service="")).status == serving
    assert health.Check(health_pb2.HealthCheckRequest(service=SERVICE_NAME)).status == serving
