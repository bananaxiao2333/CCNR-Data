# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""SQLAlchemy engine / session 生命周期。

读、写用两个 engine：

* 读：默认的延迟事务，WAL 下多读不互斥；
* 写：连接层发 `BEGIN IMMEDIATE`，让并发写在事务开始就排队，而不是提交时才发现冲突。

这是本仓库里**唯一**允许出现原生命令的地方（PRAGMA 与 BEGIN IMMEDIATE），
因为 SQLAlchemy 没有等价 API；其余业务代码一律走 repositories。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from ccnr_data.errors import internal, unavailable

__all__ = ["Database", "build_engine", "database_url", "prepare_sqlite_dir"]

ROOT = Path(__file__).resolve().parents[2]
_BUSY_TIMEOUT_S = 5.0


def database_url(db_file: str | Path | None = None) -> str:
    """解析 SQLAlchemy URL：显式 URL 优先，否则由 DB_FILE 推导。"""
    env_url = os.environ.get("CCNR_DATA_DATABASE_URL", "").strip()
    if env_url:
        return env_url
    if db_file is None:
        db_file = os.environ.get("CCNR_DATA_DB_FILE", "var/ccnr-data.db").strip()
    if not str(db_file).strip():
        raise unavailable("CCNR_DATA_DB_FILE 不能为空")
    return f"sqlite+pysqlite:///{Path(db_file).expanduser().resolve()}"


def prepare_sqlite_dir(url: str) -> None:
    """SQLite 文件库的父目录不存在时先建出来。"""
    parsed = make_url(url)
    if not parsed.drivername.startswith("sqlite"):
        return
    database = parsed.database or ""
    if not database or database == ":memory:":
        return
    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _set_sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute(f"PRAGMA busy_timeout = {int(_BUSY_TIMEOUT_S * 1000)}")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.close()


def _disable_implicit_begin(dbapi_connection: object, _record: object) -> None:
    """关掉 pysqlite 的自动 BEGIN，改由 begin 事件显式发 BEGIN IMMEDIATE。"""
    dbapi_connection.isolation_level = None  # type: ignore[attr-defined]


def _begin_immediate(conn: object) -> None:
    conn.exec_driver_sql("BEGIN IMMEDIATE")  # type: ignore[attr-defined]


def build_engine(url: str, *, immediate: bool) -> Engine:
    """建 engine；`immediate=True` 用于写路径。"""
    engine = create_engine(
        url,
        connect_args={"timeout": _BUSY_TIMEOUT_S},
        pool_pre_ping=True,
    )
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _set_sqlite_pragmas)
        if immediate:
            event.listen(engine, "connect", _disable_implicit_begin)
            event.listen(engine, "begin", _begin_immediate)
    return engine


class Database:
    """一个数据库的读/写 engine 与 session 工厂。"""

    def __init__(self, db_file: str | Path = "var/ccnr-data.db", *, url: str | None = None) -> None:
        self._url = url or database_url(db_file)
        self._read_engine: Engine | None = None
        self._write_engine: Engine | None = None
        self._read_factory: sessionmaker[Session] | None = None
        self._write_factory: sessionmaker[Session] | None = None
        self._opened = False

    @property
    def url(self) -> str:
        return self._url

    @property
    def path(self) -> Path:
        """SQLite 文件路径；非 SQLite URL 时返回 URL 的 database 部分。"""
        database = make_url(self._url).database or ""
        return Path(database) if database else Path()

    @property
    def is_open(self) -> bool:
        return self._opened

    def open(self) -> None:
        """建目录、建 engine、校验迁移版本。可重复调用。"""
        if self._opened:
            return
        try:
            prepare_sqlite_dir(self._url)
            self._read_engine = build_engine(self._url, immediate=False)
            self._write_engine = build_engine(self._url, immediate=True)
            self._read_factory = sessionmaker(self._read_engine, expire_on_commit=False)
            self._write_factory = sessionmaker(self._write_engine, expire_on_commit=False)
            self._verify_head()
        except Exception:
            self.close()
            raise
        self._opened = True

    def close(self) -> None:
        if self._read_engine is not None:
            self._read_engine.dispose()
        if self._write_engine is not None:
            self._write_engine.dispose()
        self._read_engine = None
        self._write_engine = None
        self._read_factory = None
        self._write_factory = None
        self._opened = False

    # ---------------------------------------------------------------- 事务

    @contextmanager
    def read(self) -> Iterator[Session]:
        """只读 session：结束即关闭，不提交。"""
        if self._read_factory is None:
            raise unavailable("数据库尚未打开")
        session = self._read_factory()
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def write(self) -> Iterator[Session]:
        """写 session：成功 commit，异常 rollback。"""
        if self._write_factory is None:
            raise unavailable("数据库尚未打开")
        session = self._write_factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    # ---------------------------------------------------------------- 模式

    def _verify_head(self) -> None:
        """库内迁移版本必须等于 Alembic head，否则拒绝启动。"""
        config = AlembicConfig(str(ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", self._url.replace("%", "%%"))
        head = ScriptDirectory.from_config(config).get_current_head()
        if self._read_engine is None:
            raise unavailable("数据库尚未打开")
        with self._read_engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        if current != head:
            raise internal(
                f"数据库迁移版本不匹配：库内 {current or '空库'}，程序要求 {head}。"
                "请先备份，再执行 make db-upgrade（旧库先 make db-adopt）。"
            )
