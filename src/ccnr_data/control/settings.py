# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""控制面配置：只读环境变量，越界/半配置一律启动失败。

与 config.py 分开，是为了让数据面（模组）的配置不受控制面扩张影响；
两者都遵循同一条规则：不静默钳制，错就报 ConfigError。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from ccnr_data.config import ConfigError

__all__ = ["ControlSettings"]

ENV_PREFIX = "CCNR_DATA_"

DEFAULT_HTTP_BIND = "127.0.0.1:8082"
DEFAULT_CASDOOR_ORG = "ccnr"
DEFAULT_CASDOOR_TIMEOUT_MS = 2000
DEFAULT_CASDOOR_CACHE_TTL_S = 60
DEFAULT_HEARTBEAT_TTL_S = 180
DEFAULT_PROXY_EVENT_RETENTION_DAYS = 30
DEFAULT_SESSION_RETENTION_DAYS = 365
FAIL_MODES = ("deny", "allow")


def _text(name: str, default: str) -> str:
    value = os.environ.get(ENV_PREFIX + name)
    return default if value is None else value.strip()


def _int(name: str, default: int) -> int:
    raw = os.environ.get(ENV_PREFIX + name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{ENV_PREFIX}{name} 不是整数：{raw!r}") from exc


def _json_map(name: str) -> dict[str, str]:
    raw = os.environ.get(ENV_PREFIX + name, "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{ENV_PREFIX}{name} 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise ConfigError(f"{ENV_PREFIX}{name} 必须是 {{string: string}} 的 JSON 对象")
    return dict(data)


def _check_range(name: str, value: int, low: int, high: int) -> int:
    if not low <= value <= high:
        raise ConfigError(f"{name} 必须在 {low}–{high} 之间，实际 {value}")
    return value


@dataclass(frozen=True, slots=True)
class ControlSettings:
    """一份解析完成、已校验的控制面配置。"""

    http_bind: str
    client_tokens: dict[str, str] = field(default_factory=dict)
    casdoor_endpoint: str = ""
    casdoor_client_id: str = ""
    casdoor_client_secret: str = ""
    casdoor_organization: str = DEFAULT_CASDOOR_ORG
    casdoor_timeout_ms: int = DEFAULT_CASDOOR_TIMEOUT_MS
    casdoor_cache_ttl_s: int = DEFAULT_CASDOOR_CACHE_TTL_S
    auth_fail_mode: str = "deny"
    role_map: dict[str, str] = field(default_factory=dict)
    heartbeat_ttl_s: int = DEFAULT_HEARTBEAT_TTL_S
    proxy_event_retention_days: int = DEFAULT_PROXY_EVENT_RETENTION_DAYS
    session_retention_days: int = DEFAULT_SESSION_RETENTION_DAYS

    @property
    def casdoor_enabled(self) -> bool:
        return bool(self.casdoor_endpoint and self.casdoor_client_id and self.casdoor_client_secret)

    @classmethod
    def resolve(cls) -> ControlSettings:
        endpoint = _text("CASDOOR_ENDPOINT", "").rstrip("/")
        client_id = _text("CASDOOR_CLIENT_ID", "")
        client_secret = _text("CASDOOR_CLIENT_SECRET", "")
        configured = [bool(endpoint), bool(client_id), bool(client_secret)]
        if any(configured) and not all(configured):
            raise ConfigError(
                "Casdoor 半配置：CASDOOR_ENDPOINT / CLIENT_ID / CLIENT_SECRET 必须同时给或同时留空"
            )
        fail_mode = _text("AUTH_FAIL_MODE", "deny").lower()
        if fail_mode not in FAIL_MODES:
            raise ConfigError(f"AUTH_FAIL_MODE 必须是 {', '.join(FAIL_MODES)}，实际 {fail_mode!r}")

        return cls(
            http_bind=_text("HTTP_BIND", DEFAULT_HTTP_BIND),
            client_tokens=_json_map("CLIENT_TOKENS"),
            casdoor_endpoint=endpoint,
            casdoor_client_id=client_id,
            casdoor_client_secret=client_secret,
            casdoor_organization=_text("CASDOOR_ORGANIZATION", DEFAULT_CASDOOR_ORG),
            casdoor_timeout_ms=_check_range(
                "casdoor_timeout_ms", _int("CASDOOR_TIMEOUT_MS", DEFAULT_CASDOOR_TIMEOUT_MS), 100, 10000
            ),
            casdoor_cache_ttl_s=_check_range(
                "casdoor_cache_ttl_s",
                _int("CASDOOR_CACHE_TTL_S", DEFAULT_CASDOOR_CACHE_TTL_S),
                0,
                3600,
            ),
            auth_fail_mode=fail_mode,
            role_map=_json_map("ROLE_MAP"),
            heartbeat_ttl_s=_check_range(
                "heartbeat_ttl_s", _int("HEARTBEAT_TTL_S", DEFAULT_HEARTBEAT_TTL_S), 30, 3600
            ),
            proxy_event_retention_days=_check_range(
                "proxy_event_retention_days",
                _int("PROXY_EVENT_RETENTION_DAYS", DEFAULT_PROXY_EVENT_RETENTION_DAYS),
                0,
                3650,
            ),
            session_retention_days=_check_range(
                "session_retention_days",
                _int("SESSION_RETENTION_DAYS", DEFAULT_SESSION_RETENTION_DAYS),
                0,
                3650,
            ),
        )
