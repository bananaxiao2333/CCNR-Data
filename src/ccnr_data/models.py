# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""全部表的 SQLAlchemy 2.0 模型。

时间列统一 UTC epoch 毫秒（见 docs/03），不用 DateTime：SQLite 与 PostgreSQL 的
排序、比较语义一致，也不会出现时区歧义。

表结构的唯一权威是 `alembic/versions/`；本文件必须与迁移保持一致，
`alembic check` 会在门禁里验证。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "AccessPolicy",
    "AccessRule",
    "AuditLog",
    "Base",
    "ChangeLog",
    "Idempotency",
    "MatchEvent",
    "Player",
    "PlayerIdentity",
    "ProxyEvent",
    "ProxySession",
    "RoleOverride",
    "ServerConfig",
    "Settlement",
    "SettlementLine",
]


class Base(DeclarativeBase):
    """所有表的基类。"""


# ---------------------------------------------------------------------------
# 数据面（moddata.v1）
# ---------------------------------------------------------------------------


class Player(Base):
    """玩家档案：经验 / 等级 / 名字 / 乐观锁版本。"""

    __tablename__ = "players"

    player_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    server_id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, default="")
    experience: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (Index("idx_players_server", "server_id"),)


class RoleOverride(Base):
    """角色开关。保留 enabled=0 的行，区分「从没给过」与「给过又收回」。"""

    __tablename__ = "role_overrides"

    player_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    server_id: Mapped[str] = mapped_column(Text, primary_key=True)
    role: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (Index("idx_role_overrides_player", "player_uuid", "server_id"),)


class ServerConfig(Base):
    """服务器级策略。"""

    __tablename__ = "server_configs"

    server_id: Mapped[str] = mapped_column(Text, primary_key=True)
    role_policy: Mapped[str] = mapped_column(Text)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[int] = mapped_column(Integer)


class Settlement(Base):
    """结算头。request_id 唯一，重放不会重复落账。"""

    __tablename__ = "settlements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(Text, unique=True)
    server_id: Mapped[str] = mapped_column(Text)
    player_uuid: Mapped[str] = mapped_column(Text)
    match_id: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text)
    xp_before: Mapped[int] = mapped_column(Integer)
    xp_after: Mapped[int] = mapped_column(Integer)
    level_before: Mapped[int] = mapped_column(Integer)
    level_after: Mapped[int] = mapped_column(Integer)
    gain: Mapped[int] = mapped_column(Integer)
    diverged: Mapped[int] = mapped_column(Integer, default=0)
    settled_at: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        Index("idx_settlements_player", "player_uuid", "server_id", "id"),
        Index("idx_settlements_match", "server_id", "match_id", "id"),
    )


class SettlementLine(Base):
    """结算明细。repeated 的顺序即上报顺序。"""

    __tablename__ = "settlement_lines"

    settlement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("settlements.id", ondelete="CASCADE"), primary_key=True
    )
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    value: Mapped[int] = mapped_column(Integer)


class MatchEvent(Base):
    """对局事件流水。只追加，不改不删。"""

    __tablename__ = "match_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(Text, unique=True)
    server_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    match_id: Mapped[str] = mapped_column(Text, default="")
    phase_id: Mapped[str] = mapped_column(Text, default="")
    previous_phase_id: Mapped[str] = mapped_column(Text, default="")
    definition_id: Mapped[str] = mapped_column(Text, default="")
    actor_uuid: Mapped[str] = mapped_column(Text, default="")
    target_uuid: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    occurred_at: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        Index("idx_match_events_match", "server_id", "match_id", "id"),
        Index("idx_match_events_occurred", "occurred_at"),
    )


class Idempotency(Base):
    """幂等键 + 缓存响应。与业务行同事务提交。"""

    __tablename__ = "idempotency"

    request_id: Mapped[str] = mapped_column(Text, primary_key=True)
    method: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(Text)
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer)


class AuditLog(Base):
    """状态变更的前后值。事件不写这里。"""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(Text, default="")
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (Index("idx_audit_created", "created_at"),)


class ChangeLog(Base):
    """变更流。seq 全局单调，WatchChanges 用它做游标。"""

    __tablename__ = "change_log"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    change_type: Mapped[str] = mapped_column(Text)
    server_id: Mapped[str] = mapped_column(Text)
    player_uuid: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    occurred_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        Index("idx_change_log_server", "server_id", "seq"),
        Index("idx_change_log_occurred", "occurred_at"),
        {"sqlite_autoincrement": True},
    )


# ---------------------------------------------------------------------------
# 控制面（control.v1）
# ---------------------------------------------------------------------------


class PlayerIdentity(Base):
    """MC UUID ↔ Casdoor 用户的投影。Casdoor 是唯一身份源。"""

    __tablename__ = "player_identities"

    player_uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, default="")
    username_lower: Mapped[str] = mapped_column(Text)
    casdoor_user_id: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="ADMIN")
    linked_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        Index("uq_player_identities_username", "username_lower", unique=True),
        Index("idx_player_identities_casdoor", "casdoor_user_id"),
    )


class AccessRule(Base):
    """封禁 / 白名单规则；作用域为空串表示全局。"""

    __tablename__ = "access_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_type: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    effect: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        Index("uq_access_rules_subject", "subject_type", "subject", "scope", unique=True),
        Index("idx_access_rules_expires", "expires_at"),
    )


class AccessPolicy(Base):
    """作用域的准入模式：open / whitelist。"""

    __tablename__ = "access_policies"

    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    mode: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[int] = mapped_column(Integer)


class ProxySession(Base):
    """代理会话。在线 = ended_at 为空且 last_seen 足够新。"""

    __tablename__ = "proxy_sessions"

    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    player_uuid: Mapped[str] = mapped_column(Text)
    username: Mapped[str] = mapped_column(Text, default="")
    proxy_id: Mapped[str] = mapped_column(Text)
    server_id: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[int] = mapped_column(Integer)
    last_seen_at: Mapped[int] = mapped_column(Integer)
    ended_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_reason: Mapped[str] = mapped_column(Text, default="")
    client_version: Mapped[str] = mapped_column(Text, default="")
    protocol_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        Index("idx_proxy_sessions_online", "ended_at", "last_seen_at"),
        Index("idx_proxy_sessions_player", "player_uuid", "started_at"),
        Index("idx_proxy_sessions_server", "server_id", "started_at"),
    )


class ProxyEvent(Base):
    """代理事件流水（登录失败、转服、结束原因等）。"""

    __tablename__ = "proxy_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(Text)
    session_id: Mapped[str] = mapped_column(Text, default="")
    player_uuid: Mapped[str] = mapped_column(Text, default="")
    username: Mapped[str] = mapped_column(Text, default="")
    server_id: Mapped[str] = mapped_column(Text, default="")
    from_server_id: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[int] = mapped_column(Integer)
    end_reason: Mapped[str] = mapped_column(Text, default="")
    deny_reason: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("idx_proxy_events_occurred", "occurred_at"),)
