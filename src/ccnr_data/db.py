# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""SQLite 连接与事务。

线程模型：gRPC 线程池里的每个线程持有自己的连接（`threading.local`），
SQLite 在 WAL 模式下允许"多读一写"，因此不需要额外加锁。
写路径统一走 `write()`，它开 `BEGIN IMMEDIATE`：立刻取写锁，
让并发写请求串行排队（`busy_timeout` 内等待），而不是在提交时才发现冲突。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from ccnr_data.clock import now_ms
from ccnr_data.errors import internal, unavailable

__all__ = ["Database", "SCHEMA_VERSION"]

LOGGER = logging.getLogger(__name__)

#: 与 schema.sql 里的 DDL 对应。改 schema 必须同时加迁移阶梯（见 docs/03）。
SCHEMA_VERSION = 1

_BUSY_TIMEOUT_S = 5.0


class Database:
    """一个 SQLite 库的连接管理器 + 事务边界。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._connections: set[sqlite3.Connection] = set()
        self._opened = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._opened

    def open(self) -> None:
        """建目录、建连接、跑 bootstrap。可重复调用。"""
        if self._opened:
            return
        parent = self._path.expanduser().resolve().parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise unavailable(f"无法创建数据库目录 {parent}：{exc}") from exc
        self._opened = True
        try:
            self._bootstrap()
        except Exception:
            self._opened = False
            raise

    def close(self) -> None:
        with self._lock:
            connections = list(self._connections)
            self._connections.clear()
        for conn in connections:
            try:
                conn.close()
            except sqlite3.Error:  # pragma: no cover - 关闭失败无补救手段，仅记录
                LOGGER.warning("关闭数据库连接失败", exc_info=True)
        self._opened = False

    # ---------------------------------------------------------------- 连接

    def _connect(self) -> sqlite3.Connection:
        if not self._opened:
            raise unavailable("数据库尚未打开")
        conn = sqlite3.connect(
            self._path,
            timeout=_BUSY_TIMEOUT_S,
            isolation_level=None,  # 事务边界完全由 write() 显式控制
            # 连接按线程归属（threading.local），同一连接不会被两个线程同时使用；
            # 放开同线程限制只是为了能在停机时从主线程关闭 gRPC 工作线程建的连接。
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = %d" % int(_BUSY_TIMEOUT_S * 1000))  # noqa: UP031 - PRAGMA 不接受参数绑定
        conn.execute("PRAGMA synchronous = NORMAL")
        with self._lock:
            self._connections.add(conn)
        return conn

    def connection(self) -> sqlite3.Connection:
        """当前线程的连接（首次访问时建立）。"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    # ---------------------------------------------------------------- 事务

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """写事务：BEGIN IMMEDIATE → 提交 / 回滚。"""
        conn = self.connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            raise unavailable(f"无法获取数据库写锁：{exc}") from exc
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        conn.commit()

    # ---------------------------------------------------------------- 模式

    def _bootstrap(self) -> None:
        schema_sql = resources.files("ccnr_data").joinpath("schema.sql").read_text(encoding="utf-8")
        conn = self.connection()
        try:
            conn.executescript(schema_sql)
        except sqlite3.Error as exc:
            raise unavailable(f"初始化数据库模式失败：{exc}") from exc

        row = conn.execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_meta (id, version, applied_at) VALUES (1, ?, ?)",
                (SCHEMA_VERSION, now_ms()),
            )
            return
        stored = int(row["version"])
        if stored != SCHEMA_VERSION:
            raise internal(
                f"数据库模式版本不匹配：库内 {stored}，本程序 {SCHEMA_VERSION}。"
                "请先备份并按 docs/03-数据模型.md 的迁移步骤升级，本服务不会自动改库。"
            )
