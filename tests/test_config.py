# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""配置解析与范围校验。"""

from __future__ import annotations

import pytest

from ccnr_data.config import Config, ConfigError, parse_bind


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(__import__("os").environ):
        if name.startswith("CCNR_DATA_"):
            monkeypatch.delenv(name)
    config = Config.resolve()
    assert config.bind == "127.0.0.1:8081"
    assert config.watch_poll_ms == 500
    assert config.max_workers == 16
    assert (config.event_retention_days, config.change_retention_days, config.audit_retention_days) == (
        30,
        7,
        365,
    )


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCNR_DATA_BIND", "0.0.0.0:9000")
    monkeypatch.setenv("CCNR_DATA_WATCH_POLL_MS", "250")
    monkeypatch.setenv("CCNR_DATA_EVENT_RETENTION_DAYS", "3")
    config = Config.resolve()
    assert config.bind_host_port == ("0.0.0.0", 9000)
    assert config.watch_poll_ms == 250
    assert config.event_retention_days == 3


def test_cli_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCNR_DATA_BIND", "0.0.0.0:9000")
    assert Config.resolve(bind="127.0.0.1:1").bind == "127.0.0.1:1"


@pytest.mark.parametrize("raw", ["", "localhost", "host:", "host:abc", "host:-1", "host:70000"])
def test_bad_bind_rejected(raw: str) -> None:
    with pytest.raises(ConfigError):
        parse_bind(raw)


def test_port_zero_allowed() -> None:
    """0 = 内核分配端口，测试与容器编排靠它避免固定端口冲突。"""
    assert parse_bind("127.0.0.1:0") == ("127.0.0.1", 0)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"watch_poll_ms": 99}, "低于下限"),
        ({"watch_poll_ms": 5001}, "高于上限"),
        ({"max_workers": 0}, "线程数为零"),
        ({"max_workers": 1000}, "线程数过大"),
        ({"event_retention_days": -1}, "负数保留天数"),
        ({"event_retention_days": 99999}, "保留天数过大"),
        ({"log_level": "TRACE"}, "未知日志级别"),
    ],
)
def test_out_of_range_rejected(kwargs: dict[str, object], reason: str) -> None:
    with pytest.raises(ConfigError):
        Config.resolve(**kwargs)  # type: ignore[arg-type]


def test_zero_retention_means_keep_forever() -> None:
    config = Config.resolve(event_retention_days=0)
    assert config.event_retention_days == 0


def test_non_integer_env_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCNR_DATA_MAX_WORKERS", "many")
    with pytest.raises(ConfigError):
        Config.resolve()
