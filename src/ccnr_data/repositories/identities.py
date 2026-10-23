# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""MC UUID ↔ Casdoor 用户的身份投影。"""

from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from ccnr_data.errors import failed_precondition, internal
from ccnr_data.models import PlayerIdentity
from ccnr_data.repositories._common import table_of

__all__ = ["get_by_casdoor", "get_by_uuid", "get_by_username", "upsert"]


def get_by_uuid(session: Session, player_uuid: str) -> RowMapping | None:
    table = table_of(PlayerIdentity)
    return session.execute(select(table).where(table.c.player_uuid == player_uuid)).mappings().first()


def get_by_username(session: Session, username: str) -> RowMapping | None:
    table = table_of(PlayerIdentity)
    return session.execute(select(table).where(table.c.username_lower == username.lower())).mappings().first()


def get_by_casdoor(session: Session, casdoor_user_id: str) -> RowMapping | None:
    table = table_of(PlayerIdentity)
    return session.execute(select(table).where(table.c.casdoor_user_id == casdoor_user_id)).mappings().first()


def upsert(
    session: Session,
    *,
    player_uuid: str,
    username: str,
    casdoor_user_id: str,
    source: str,
    now: int,
    overwrite: bool = False,
) -> tuple[RowMapping, bool]:
    """写入投影，返回 (row, created)。

    一个 UUID 只对应一个 Casdoor 用户，一个用户名只对应一个 UUID；
    冲突时默认拒绝，必须显式 overwrite。
    """
    table = table_of(PlayerIdentity)
    current = get_by_uuid(session, player_uuid)
    if current is not None and str(current["casdoor_user_id"]) != casdoor_user_id and not overwrite:
        raise failed_precondition(
            f"UUID {player_uuid} 已绑定到另一个 Casdoor 用户 {current['casdoor_user_id']}；"
            "改绑必须显式 overwrite"
        )
    same_name = get_by_username(session, username)
    if same_name is not None and str(same_name["player_uuid"]) != player_uuid:
        raise failed_precondition(f"用户名 {username} 已被 UUID {same_name['player_uuid']} 占用")
    same_casdoor = get_by_casdoor(session, casdoor_user_id)
    if same_casdoor is not None and str(same_casdoor["player_uuid"]) != player_uuid and not overwrite:
        raise failed_precondition(
            f"Casdoor 用户 {casdoor_user_id} 已绑定到 UUID {same_casdoor['player_uuid']}"
        )

    if current is None:
        session.execute(
            insert(table).values(
                player_uuid=player_uuid,
                username=username,
                username_lower=username.lower(),
                casdoor_user_id=casdoor_user_id,
                source=source,
                linked_at=now,
                updated_at=now,
            )
        )
        created = True
    else:
        session.execute(
            update(table)
            .where(table.c.player_uuid == player_uuid)
            .values(
                username=username,
                username_lower=username.lower(),
                casdoor_user_id=casdoor_user_id,
                source=source,
                updated_at=now,
            )
        )
        created = False
    row = get_by_uuid(session, player_uuid)
    if row is None:  # pragma: no cover
        raise internal(f"写入身份投影后读不到行：{player_uuid}")
    return row, created
