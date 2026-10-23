# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""测试专用：建库与直接看库。

生产代码禁止裸 SQL；测试需要一个独立视角来断言落库结果，
所以这里显式开 sqlite3 连接，并用 Alembic 建库（与生产同一条迁移链）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from ccnr_data.db import Database

__all__ = ["raw_connection", "upgrade_database"]

ROOT = Path(__file__).resolve().parents[1]


def upgrade_database(path: Path) -> str:
    """把空库升到 head，返回 SQLAlchemy URL。"""
    url = f"sqlite+pysqlite:///{path}"
    config = AlembicConfig(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    return url


def raw_connection(database: Database) -> sqlite3.Connection:
    connection = sqlite3.connect(database.path)
    connection.row_factory = sqlite3.Row
    return connection
