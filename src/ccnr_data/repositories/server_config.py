# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""服务器级策略。"""

from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from ccnr_data.errors import internal
from ccnr_data.models import ServerConfig
from ccnr_data.repositories._common import table_of

__all__ = ["get_server_config", "upsert_server_config"]


def get_server_config(session: Session, server_id: str) -> RowMapping | None:
    table = table_of(ServerConfig)
    return session.execute(select(table).where(table.c.server_id == server_id)).mappings().first()


def upsert_server_config(
    session: Session,
    *,
    server_id: str,
    role_policy: str,
    config_json: str,
    updated_at: int,
) -> RowMapping:
    table = table_of(ServerConfig)
    current = (
        session.execute(select(table.c.version).where(table.c.server_id == server_id)).mappings().first()
    )
    if current is None:
        session.execute(
            insert(table).values(
                server_id=server_id,
                role_policy=role_policy,
                config_json=config_json,
                version=1,
                updated_at=updated_at,
            )
        )
    else:
        session.execute(
            update(table)
            .where(table.c.server_id == server_id)
            .values(
                role_policy=role_policy,
                config_json=config_json,
                version=int(current["version"]) + 1,
                updated_at=updated_at,
            )
        )
    row = get_server_config(session, server_id)
    if row is None:  # pragma: no cover
        raise internal(f"写入服务器策略后读不到行：{server_id}")
    return row
