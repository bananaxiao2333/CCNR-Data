# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""封禁 / 白名单规则与作用域准入模式。"""

from __future__ import annotations

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from ccnr_data.errors import internal
from ccnr_data.models import AccessPolicy, AccessRule
from ccnr_data.repositories._common import table_of

__all__ = [
    "delete_rule",
    "get_policy",
    "get_policy_row",
    "list_policies",
    "matching_rules",
    "set_policy",
    "upsert_rule",
]


def matching_rules(
    session: Session,
    *,
    player_uuid: str,
    username: str,
    casdoor_user_id: str,
    scope: str,
    now: int,
) -> list[RowMapping]:
    """取命中该玩家、且未过期的规则（scope 与全局）。"""
    table = table_of(AccessRule)
    subjects = [
        (table.c.subject_type == "PLAYER_UUID") & (table.c.subject == player_uuid),
        (table.c.subject_type == "USERNAME") & (table.c.subject == username.lower()),
        (table.c.subject_type == "CASDOOR_USER") & (table.c.subject == casdoor_user_id),
    ]
    scopes = [table.c.scope == "", table.c.scope == scope] if scope else [table.c.scope == ""]
    statement = select(table).where(
        or_(*subjects),
        or_(*scopes),
        or_(table.c.expires_at.is_(None), table.c.expires_at > now),
    )
    return list(session.execute(statement).mappings())


def get_policy(session: Session, scope: str) -> str | None:
    """返回该作用域的模式；没有记录返回 None（调用方按 open 处理）。"""
    table = table_of(AccessPolicy)
    row = session.execute(select(table.c.mode).where(table.c.scope == scope)).first()
    return None if row is None else str(row[0])


def get_policy_row(session: Session, scope: str) -> RowMapping | None:
    table = table_of(AccessPolicy)
    return session.execute(select(table).where(table.c.scope == scope)).mappings().first()


def list_policies(session: Session) -> list[RowMapping]:
    table = table_of(AccessPolicy)
    return list(session.execute(select(table).order_by(table.c.scope)).mappings())


def set_policy(session: Session, *, scope: str, mode: str, now: int) -> None:
    table = table_of(AccessPolicy)
    exists = session.execute(select(table.c.scope).where(table.c.scope == scope)).first()
    if exists is None:
        session.execute(insert(table).values(scope=scope, mode=mode, updated_at=now))
    else:
        session.execute(update(table).where(table.c.scope == scope).values(mode=mode, updated_at=now))


def upsert_rule(
    session: Session,
    *,
    subject_type: str,
    subject: str,
    effect: str,
    scope: str,
    expires_at: int | None,
    reason: str,
    actor: str,
    now: int,
) -> RowMapping:
    """按 (subject_type, subject, scope) 覆盖规则。"""
    table = table_of(AccessRule)
    normalized = subject.lower() if subject_type == "USERNAME" else subject
    current = (
        session.execute(
            select(table.c.id).where(
                table.c.subject_type == subject_type,
                table.c.subject == normalized,
                table.c.scope == scope,
            )
        )
        .mappings()
        .first()
    )
    if current is None:
        session.execute(
            insert(table).values(
                subject_type=subject_type,
                subject=normalized,
                effect=effect,
                scope=scope,
                expires_at=expires_at,
                reason=reason,
                actor=actor,
                created_at=now,
            )
        )
    else:
        session.execute(
            update(table)
            .where(table.c.id == int(current["id"]))
            .values(
                effect=effect,
                expires_at=expires_at,
                reason=reason,
                actor=actor,
                created_at=now,
            )
        )
    row = (
        session.execute(
            select(table).where(
                table.c.subject_type == subject_type,
                table.c.subject == normalized,
                table.c.scope == scope,
            )
        )
        .mappings()
        .first()
    )
    if row is None:  # pragma: no cover
        raise internal(f"写入准入规则后读不到行：{subject_type}/{subject}@{scope}")
    return row


def list_rules(
    session: Session,
    *,
    subject_type: str | None,
    subject: str,
    scope: str,
    include_expired: bool,
    now: int,
) -> list[RowMapping]:
    table = table_of(AccessRule)
    statement = select(table)
    if subject_type:
        statement = statement.where(table.c.subject_type == subject_type)
    if subject:
        normalized = subject.lower() if subject_type == "USERNAME" else subject
        statement = statement.where(table.c.subject == normalized)
    if scope:
        statement = statement.where(table.c.scope == scope)
    if not include_expired:
        statement = statement.where(or_(table.c.expires_at.is_(None), table.c.expires_at > now))
    statement = statement.order_by(table.c.id)
    return list(session.execute(statement).mappings())


def delete_rule(session: Session, rule_id: int) -> bool:
    table = table_of(AccessRule)
    result = session.execute(delete(table).where(table.c.id == rule_id))
    return bool(getattr(result, "rowcount", 0))
