# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""平台账号 ↔ Casdoor 用户的绑定。

bot 只通过 gRPC 读写这里，不维护本地绑定表。
"""

from __future__ import annotations

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from ccnr_data.errors import failed_precondition, internal
from ccnr_data.models import AccountLink
from ccnr_data.repositories._common import table_of

__all__ = ["get", "get_by_casdoor", "remove", "upsert"]


def get(session: Session, user_id: str) -> RowMapping | None:
    table = table_of(AccountLink)
    return session.execute(select(table).where(table.c.user_id == user_id)).mappings().first()


def get_by_casdoor(session: Session, casdoor_user_id: str) -> RowMapping | None:
    table = table_of(AccountLink)
    return session.execute(select(table).where(table.c.casdoor_user_id == casdoor_user_id)).mappings().first()


def upsert(
    session: Session,
    *,
    user_id: str,
    casdoor_user_id: str,
    source: str,
    now: int,
    overwrite: bool = False,
) -> tuple[RowMapping, bool]:
    """写入绑定，返回 (row, created)；冲突默认拒绝。"""
    table = table_of(AccountLink)
    current = get(session, user_id)
    if current is not None and str(current["casdoor_user_id"]) != casdoor_user_id and not overwrite:
        raise failed_precondition(
            f"平台账号 {user_id} 已绑定到另一个用户 {current['casdoor_user_id']}；改绑必须显式 overwrite"
        )
    same_account = get_by_casdoor(session, casdoor_user_id)
    if same_account is not None and str(same_account["user_id"]) != user_id and not overwrite:
        raise failed_precondition(
            f"Casdoor 用户 {casdoor_user_id} 已绑定到平台账号 {same_account['user_id']}"
        )

    if current is None:
        session.execute(
            insert(table).values(
                user_id=user_id,
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
            .where(table.c.user_id == user_id)
            .values(
                casdoor_user_id=casdoor_user_id,
                source=source,
                updated_at=now,
            )
        )
        created = False
    row = get(session, user_id)
    if row is None:  # pragma: no cover
        raise internal(f"写入账号绑定后读不到行：{user_id}")
    return row, created


def remove(session: Session, user_id: str) -> bool:
    table = table_of(AccountLink)
    result = session.execute(delete(table).where(table.c.user_id == user_id))
    return bool(getattr(result, "rowcount", 0))
