# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""运行时配置：环境变量为底，命令行参数覆盖。

只做配置解析与范围校验，不读文件、不连库。越界一律**启动失败**而不是静默钳制——
静默钳制会让"我配了 50ms 轮询"变成"实际 100ms"，排障时看不出任何线索。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Config",
    "ConfigError",
    "DEFAULT_AUDIT_RETENTION_DAYS",
    "DEFAULT_BIND",
    "DEFAULT_CHANGE_RETENTION_DAYS",
    "DEFAULT_DB_FILE",
    "DEFAULT_EVENT_RETENTION_DAYS",
    "DEFAULT_IDEMPOTENCY_RETENTION_DAYS",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_MAX_WORKERS",
    "DEFAULT_WATCH_POLL_MS",
    "LOG_LEVELS",
]

ENV_PREFIX = "CCNR_DATA_"

DEFAULT_DB_FILE = "var/ccnr-data.db"
DEFAULT_BIND = "127.0.0.1:8081"
DEFAULT_WATCH_POLL_MS = 500
DEFAULT_MAX_WORKERS = 16
DEFAULT_LOG_LEVEL = "INFO"

# 日志轮换：保留天数，0 = 永久保留。
#   match_events 是事件流水（量最大，默认保留 30 天）
#   change_log   是变更流（只作为订阅游标，默认保留 7 天；消费者落后超过这个窗口会丢事件）
#   audit_log    是审计（合规用，默认保留 365 天）
#   idempotency  是幂等键（每个写入一行，默认保留 30 天）——
#                必须在「远长于任何重试窗口」之后才能删：删早了，迟到的重放会被当成新请求再执行一次。
# settlements / settlement_lines 是业务记录不是日志，永不自动清除。
DEFAULT_EVENT_RETENTION_DAYS = 30
DEFAULT_CHANGE_RETENTION_DAYS = 7
DEFAULT_AUDIT_RETENTION_DAYS = 365
DEFAULT_IDEMPOTENCY_RETENTION_DAYS = 30
RETENTION_DAYS_MAX = 3650

WATCH_POLL_MIN_MS = 100
WATCH_POLL_MAX_MS = 5000
MAX_WORKERS_MIN = 1
MAX_WORKERS_MAX = 256

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(ValueError):
    """配置非法。启动阶段抛出，让进程带着可读的原因退出。"""


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(ENV_PREFIX + name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(ENV_PREFIX + name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{ENV_PREFIX}{name} 不是整数：{raw!r}") from exc


def _check_range(name: str, value: int, low: int, high: int) -> int:
    if not low <= value <= high:
        raise ConfigError(f"{name} 必须在 {low}–{high} 之间，实际 {value}")
    return value


def parse_bind(raw: str) -> tuple[str, int]:
    """把 `host:port` 拆成 (host, port)。地址必须显式给出，不做隐式默认。"""
    text = raw.strip()
    if not text:
        raise ConfigError("bind 不能为空，格式为 host:port")
    host, sep, port_text = text.rpartition(":")
    if not sep or not host:
        raise ConfigError(f"bind 格式应为 host:port，实际 {raw!r}")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ConfigError(f"bind 端口不是整数：{port_text!r}") from exc
    # 0 是合法的："让内核分配一个空闲端口"。测试与容器编排都靠它避免固定端口冲突。
    if not 0 <= port <= 65535:
        raise ConfigError(f"bind 端口必须在 0–65535 之间（0 = 内核分配），实际 {port}")
    return host, port


@dataclass(frozen=True, slots=True)
class Config:
    """一份解析完成、已校验的配置。"""

    db_file: Path
    bind: str
    watch_poll_ms: int
    max_workers: int
    log_level: str
    event_retention_days: int
    change_retention_days: int
    audit_retention_days: int
    idempotency_retention_days: int

    @property
    def bind_host_port(self) -> tuple[str, int]:
        return parse_bind(self.bind)

    @classmethod
    def resolve(
        cls,
        *,
        db_file: str | None = None,
        bind: str | None = None,
        watch_poll_ms: int | None = None,
        max_workers: int | None = None,
        log_level: str | None = None,
        event_retention_days: int | None = None,
        change_retention_days: int | None = None,
        audit_retention_days: int | None = None,
        idempotency_retention_days: int | None = None,
    ) -> Config:
        """命令行参数（非 None 者）覆盖环境变量，环境变量覆盖内置默认。"""
        resolved_db = db_file if db_file is not None else _env_str("DB_FILE", DEFAULT_DB_FILE)
        resolved_bind = bind if bind is not None else _env_str("BIND", DEFAULT_BIND)
        resolved_poll = (
            watch_poll_ms if watch_poll_ms is not None else _env_int("WATCH_POLL_MS", DEFAULT_WATCH_POLL_MS)
        )
        resolved_workers = (
            max_workers if max_workers is not None else _env_int("MAX_WORKERS", DEFAULT_MAX_WORKERS)
        )
        level = (log_level if log_level is not None else _env_str("LOG_LEVEL", DEFAULT_LOG_LEVEL)).upper()
        event_days = (
            event_retention_days
            if event_retention_days is not None
            else _env_int("EVENT_RETENTION_DAYS", DEFAULT_EVENT_RETENTION_DAYS)
        )
        change_days = (
            change_retention_days
            if change_retention_days is not None
            else _env_int("CHANGE_RETENTION_DAYS", DEFAULT_CHANGE_RETENTION_DAYS)
        )
        audit_days = (
            audit_retention_days
            if audit_retention_days is not None
            else _env_int("AUDIT_RETENTION_DAYS", DEFAULT_AUDIT_RETENTION_DAYS)
        )
        idem_days = (
            idempotency_retention_days
            if idempotency_retention_days is not None
            else _env_int("IDEMPOTENCY_RETENTION_DAYS", DEFAULT_IDEMPOTENCY_RETENTION_DAYS)
        )

        if not resolved_db.strip():
            raise ConfigError("db_file 不能为空")
        parse_bind(resolved_bind)
        _check_range("watch_poll_ms", resolved_poll, WATCH_POLL_MIN_MS, WATCH_POLL_MAX_MS)
        _check_range("max_workers", resolved_workers, MAX_WORKERS_MIN, MAX_WORKERS_MAX)
        if level not in LOG_LEVELS:
            raise ConfigError(f"log_level 必须是 {', '.join(LOG_LEVELS)} 之一，实际 {level!r}")
        for name, days in (
            ("event_retention_days", event_days),
            ("change_retention_days", change_days),
            ("audit_retention_days", audit_days),
            ("idempotency_retention_days", idem_days),
        ):
            # 0 是"永久保留"的显式取值，其余必须落在合理区间；负数一律拒绝。
            if days != 0:
                _check_range(name, days, 1, RETENTION_DAYS_MAX)

        return cls(
            db_file=Path(resolved_db).expanduser(),
            bind=resolved_bind.strip(),
            watch_poll_ms=resolved_poll,
            max_workers=resolved_workers,
            log_level=level,
            event_retention_days=event_days,
            change_retention_days=change_days,
            audit_retention_days=audit_days,
            idempotency_retention_days=idem_days,
        )
