# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""命令行入口：`python -m ccnr_data`。"""

from __future__ import annotations

import argparse
import sys

from ccnr_data.config import (
    DEFAULT_AUDIT_RETENTION_DAYS,
    DEFAULT_BIND,
    DEFAULT_CHANGE_RETENTION_DAYS,
    DEFAULT_DB_FILE,
    DEFAULT_EVENT_RETENTION_DAYS,
    DEFAULT_IDEMPOTENCY_RETENTION_DAYS,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_WORKERS,
    DEFAULT_WATCH_POLL_MS,
    LOG_LEVELS,
    WATCH_POLL_MAX_MS,
    WATCH_POLL_MIN_MS,
    Config,
    ConfigError,
)
from ccnr_data.db import SCHEMA_VERSION
from ccnr_data.server import configure_logging, serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ccnr_data",
        description="CCNR 统一数据服务（gRPC）。命令行参数优先于 CCNR_DATA_* 环境变量。",
    )
    parser.add_argument("--db-file", default=None, help=f"SQLite 文件路径（默认 {DEFAULT_DB_FILE}）")
    parser.add_argument("--bind", default=None, help=f"监听地址 host:port（默认 {DEFAULT_BIND}）")
    parser.add_argument(
        "--watch-poll-ms",
        type=int,
        default=None,
        help=f"WatchChanges 轮询间隔毫秒，{WATCH_POLL_MIN_MS}–{WATCH_POLL_MAX_MS}（默认 {DEFAULT_WATCH_POLL_MS}）",
    )
    parser.add_argument(
        "--max-workers", type=int, default=None, help=f"gRPC 线程池大小（默认 {DEFAULT_MAX_WORKERS}）"
    )
    parser.add_argument(
        "--log-level", default=None, choices=LOG_LEVELS, help=f"日志级别（默认 {DEFAULT_LOG_LEVEL}）"
    )
    parser.add_argument(
        "--event-retention-days",
        type=int,
        default=None,
        help=f"事件流水保留天数，0=永久（默认 {DEFAULT_EVENT_RETENTION_DAYS}）",
    )
    parser.add_argument(
        "--change-retention-days",
        type=int,
        default=None,
        help=f"变更流保留天数，0=永久（默认 {DEFAULT_CHANGE_RETENTION_DAYS}）",
    )
    parser.add_argument(
        "--audit-retention-days",
        type=int,
        default=None,
        help=f"审计日志保留天数，0=永久（默认 {DEFAULT_AUDIT_RETENTION_DAYS}）",
    )
    parser.add_argument(
        "--idempotency-retention-days",
        type=int,
        default=None,
        help=f"幂等键保留天数，0=永久（默认 {DEFAULT_IDEMPOTENCY_RETENTION_DAYS}）",
    )
    parser.add_argument("--version", action="version", version=f"ccnr-data 模式版本 {SCHEMA_VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = Config.resolve(
            db_file=args.db_file,
            bind=args.bind,
            watch_poll_ms=args.watch_poll_ms,
            max_workers=args.max_workers,
            log_level=args.log_level,
            event_retention_days=args.event_retention_days,
            change_retention_days=args.change_retention_days,
            audit_retention_days=args.audit_retention_days,
            idempotency_retention_days=args.idempotency_retention_days,
        )
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    configure_logging(config.log_level)
    try:
        return serve(config)
    except RuntimeError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
