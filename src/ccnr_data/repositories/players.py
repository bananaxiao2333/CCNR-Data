# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""玩家档案与角色开关。"""

from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from ccnr_data.errors import internal
from ccnr_data.models import Player, RoleOverride
from ccnr_data.repositories._common import table_of

__all__ = ["get_player", "list_roles", "upsert_player", "upsert_role_override"]


def get_player(session: Session, player_uuid: str, server_id: str) -> RowMapping | None:
    """按 (uuid, server) 取档案；不存在返回 None。"""
    table = table_of(Player)
    return (
        session.execute(
            select(table).where(table.c.player_uuid == player_uuid, table.c.server_id == server_id)
        )
        .mappings()
        .first()
    )


def upsert_player(
    session: Session,
    *,
    player_uuid: str,
    server_id: str,
    username: str,
    experience: int,
    level: int,
    updated_at: int,
) -> RowMapping:
    """写入档案并 +1 版本号，返回写入后的行。

    username 传空串表示「不更新已有名字」：权威端离线结算时拿不到玩家名，
    不能因此把库里已有的名字抹掉。
    """
    table = table_of(Player)
    current = (
        session.execute(
            select(table.c.version, table.c.username).where(
                table.c.player_uuid == player_uuid, table.c.server_id == server_id
            )
        )
        .mappings()
        .first()
    )
    if current is None:
        session.execute(
            insert(table).values(
                player_uuid=player_uuid,
                server_id=server_id,
                username=username,
                experience=experience,
                level=level,
                version=1,
                updated_at=updated_at,
            )
        )
    else:
        session.execute(
            update(table)
            .where(table.c.player_uuid == player_uuid, table.c.server_id == server_id)
            .values(
                username=username or str(current["username"]),
                experience=experience,
                level=level,
                version=int(current["version"]) + 1,
                updated_at=updated_at,
            )
        )
    row = get_player(session, player_uuid, server_id)
    if row is None:  # pragma: no cover - 写入成功后必然可读
        raise internal(f"写入玩家档案后读不到行：{player_uuid} @ {server_id}")
    return row


def list_roles(session: Session, player_uuid: str, server_id: str) -> list[str]:
    """已启用的角色，按名字排序。"""
    table = table_of(RoleOverride)
    values: list[object] = list(
        session.execute(
            select(table.c.role)
            .where(
                table.c.player_uuid == player_uuid,
                table.c.server_id == server_id,
                table.c.enabled == 1,
            )
            .order_by(table.c.role)
        ).scalars()
    )
    return [str(value) for value in values]


def upsert_role_override(
    session: Session,
    *,
    player_uuid: str,
    server_id: str,
    role: str,
    enabled: bool,
    source: str,
    updated_at: int,
) -> None:
    """写入一条角色开关。enabled=False 的行保留，用于区分「没给过」与「给过又收回」。"""
    table = table_of(RoleOverride)
    exists = session.execute(
        select(table.c.role).where(
            table.c.player_uuid == player_uuid,
            table.c.server_id == server_id,
            table.c.role == role,
        )
    ).first()
    values = {
        "enabled": 1 if enabled else 0,
        "source": source,
        "updated_at": updated_at,
    }
    if exists is None:
        session.execute(
            insert(table).values(player_uuid=player_uuid, server_id=server_id, role=role, **values)
        )
    else:
        session.execute(
            update(table)
            .where(
                table.c.player_uuid == player_uuid,
                table.c.server_id == server_id,
                table.c.role == role,
            )
            .values(**values)
        )
