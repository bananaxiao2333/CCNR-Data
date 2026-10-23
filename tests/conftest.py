# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""测试夹具：一律走**真实 gRPC 通道**。

不用 mock、不直接调服务方法——序列化、状态码、线程池、事务边界都是被测对象，
绕过它们就等于把最容易出问题的一层测掉了。

数据库通过 Alembic 建到 head，与生产走同一条迁移链。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import grpc
import pytest

from ccnr_data.config import Config
from ccnr_data.db import Database
from ccnr_data.server import ServerHandle, build_server
from dbutil import upgrade_database
from moddata.v1 import moddata_pb2_grpc

TEST_SERVER_ID = "test-server"


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Database]:
    path = tmp_path / "test.db"
    url = f"sqlite+pysqlite:///{path}"
    monkeypatch.setenv("CCNR_DATA_DATABASE_URL", url)
    upgrade_database(path)
    database = Database(path)
    database.open()
    yield database
    database.close()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config.resolve(
        db_file=str(tmp_path / "test.db"),
        bind="127.0.0.1:0",
        watch_poll_ms=100,
        max_workers=8,
        log_level="WARNING",
    )


@pytest.fixture
def server(config: Config, db: Database) -> Iterator[ServerHandle]:
    handle = build_server(config, db)
    handle.server.start()
    yield handle
    handle.stop(grace=0)


@pytest.fixture
def channel(server: ServerHandle) -> Iterator[grpc.Channel]:
    chan = grpc.insecure_channel(f"127.0.0.1:{server.port}")
    grpc.channel_ready_future(chan).result(timeout=10)
    yield chan
    chan.close()


@pytest.fixture
def stub(channel: grpc.Channel) -> moddata_pb2_grpc.ModDataServiceStub:
    return moddata_pb2_grpc.ModDataServiceStub(channel)  # type: ignore[no-untyped-call]
