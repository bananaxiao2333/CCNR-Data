# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""把旧的 v1 库（schema_meta 版本 1）接入 Alembic。

做三件事，任一步失败都不改数据：

1. 校验库里有完整的 v1 表、且 schema_meta.version == 1；
2. `alembic stamp 0001_baseline`（只写 alembic_version，不动业务表）；
3. `alembic upgrade head`（应用 0002 控制面迁移，并删除 schema_meta）。

建议先备份：`cp var/ccnr-data.db var/ccnr-data.db.bak`。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ccnr_data.db import database_url  # noqa: E402

__all__ = ["V1_TABLES", "main"]

V1_TABLES = frozenset(
    {
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
)


def _fail(message: str) -> int:
    print(f"❌ {message}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="旧 v1 库接入 Alembic")
    parser.add_argument("--database-url", default="", help="覆盖 CCNR_DATA_DATABASE_URL")
    args = parser.parse_args()

    url = args.database_url.strip() or database_url()
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        if "alembic_version" in tables:
            print("✅ 该库已由 Alembic 管理，无需接管；直接 make db-upgrade 即可。")
            return 0
        if "schema_meta" not in tables:
            return _fail("没有 schema_meta：这不是 v1 旧库。空库请直接 make db-upgrade。")

        missing = V1_TABLES - tables
        if missing:
            return _fail(f"v1 表不完整，缺少：{', '.join(sorted(missing))}")

        meta = MetaData()
        schema_meta = Table("schema_meta", meta, autoload_with=engine)
        with engine.connect() as connection:
            row = connection.execute(select(schema_meta.c.version).where(schema_meta.c.id == 1)).first()
        if row is None or int(row[0]) != 1:
            stored = "无记录" if row is None else row[0]
            return _fail(f"schema_meta.version 不是 1（实际 {stored}），拒绝接管。")
    finally:
        engine.dispose()

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    print("→ 校验通过，stamp 0001_baseline")
    command.stamp(config, "0001_baseline")
    print("→ upgrade head")
    command.upgrade(config, "head")
    print("✅ 接管完成。建议再跑一次 make check。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
