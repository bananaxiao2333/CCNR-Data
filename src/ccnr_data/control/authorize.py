# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""准入判定：固定顺序，先命中先返回。

本模块**只读**：不写库、不发消息。拒绝事件由代理上报，
否则每次登录失败都会产生一条写事务，登录风暴会直接打爆 SQLite 的写锁。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ccnr_data import repositories as repo
from ccnr_data.control.casdoor import CasdoorClient, CasdoorError
from ccnr_data.control.settings import ControlSettings

__all__ = ["Decision", "decide"]

#: 与 control.v1.AuthorizeReason 的后缀一一对应。
ALLOWED = "ALLOWED"
NOT_LINKED = "NOT_LINKED"
EMAIL_UNVERIFIED = "EMAIL_UNVERIFIED"
BANNED = "BANNED"
WHITELIST_ONLY = "WHITELIST_ONLY"
ROLE_DENIED = "ROLE_DENIED"
CASDOOR_UNAVAILABLE = "CASDOOR_UNAVAILABLE"
POLICY_ERROR = "POLICY_ERROR"


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str
    message: str
    roles: tuple[str, ...]
    casdoor_user_id: str
    cache_ttl_seconds: int


def _deny(reason: str, message: str) -> Decision:
    return Decision(False, reason, message, (), "", 0)


def _required_roles(session: Session, scope: str) -> list[str]:
    """服务器策略里可选的 required_roles（放在既有 config_json 里，不新增表）。"""
    if not scope:
        return []
    row = repo.get_server_config(session, scope)
    if row is None:
        return []
    try:
        config = json.loads(str(row["config_json"]))
    except (TypeError, ValueError):
        return []
    roles = config.get("required_roles") if isinstance(config, dict) else None
    if not isinstance(roles, list):
        return []
    return [str(role) for role in roles if str(role).strip()]


def decide(
    session: Session,
    settings: ControlSettings,
    casdoor: CasdoorClient,
    *,
    player_uuid: str,
    username: str,
    scope: str,
    now: int,
) -> Decision:
    identity = repo.identities.get_by_uuid(session, player_uuid)
    if identity is None:
        identity = repo.identities.get_by_username(session, username)
    casdoor_user_id = "" if identity is None else str(identity["casdoor_user_id"])

    # 规则与白名单先于身份：封禁与白名单不应因为未绑定而失效，
    # 顺序必须与 docs/06 §3 一致。
    rules = repo.access.matching_rules(
        session,
        player_uuid=player_uuid,
        username=username,
        casdoor_user_id=casdoor_user_id,
        scope=scope,
        now=now,
    )
    for rule in rules:
        if str(rule["effect"]) == "DENY":
            reason = str(rule["reason"] or "违反服务器准入规则")
            expires = rule["expires_at"]
            suffix = (
                "（至 "
                + datetime.fromtimestamp(int(expires) / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
                + "）"
                if expires
                else ""
            )
            return _deny(BANNED, f"你已被禁止进入：{reason}{suffix}")

    policy = repo.access.get_policy(session, scope) if scope else None
    if policy is None:
        policy = repo.access.get_policy(session, "")
    whitelisted = any(str(rule["effect"]) == "ALLOW" for rule in rules)
    if policy == "whitelist" and not whitelisted:
        return _deny(WHITELIST_ONLY, "本服务器仅限白名单玩家进入")

    if identity is None:
        return _deny(NOT_LINKED, "账号尚未绑定 MC 角色，请先完成 CCNR Pass 登录与账号绑定")

    if not casdoor.enabled:
        return _deny(POLICY_ERROR, "统一登录尚未配置，暂时无法验证账号")

    try:
        user = casdoor.get_user_by_id(casdoor_user_id)
    except CasdoorError:
        if settings.auth_fail_mode == "allow":
            return Decision(True, ALLOWED, "", (), casdoor_user_id, settings.casdoor_cache_ttl_s)
        return _deny(CASDOOR_UNAVAILABLE, "统一登录暂时不可用，请稍后再试")

    if not user.email_verified:
        return _deny(EMAIL_UNVERIFIED, "请先在 CCNR Pass 完成邮箱验证")

    roles = tuple(settings.role_map.get(role, role) for role in user.roles)
    required = _required_roles(session, scope)
    if required and not set(required) & set(roles):
        return _deny(ROLE_DENIED, "你的账号角色没有该服务器的进入权限")

    return Decision(True, ALLOWED, "", roles, casdoor_user_id, settings.casdoor_cache_ttl_s)
