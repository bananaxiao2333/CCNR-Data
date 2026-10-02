# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""日志轮换：按保留天数清理过期日志。

哪些表会被清：
  * `match_events`  事件流水（量最大）
  * `change_log`    变更流
  * `audit_log`     审计
  * `idempotency`   幂等键（保留窗口必须远长于任何重试窗口）

哪些表**永不**自动清理：`players` / `role_overrides` / `server_configs` /
`settlements` / `settlement_lines` —— 它们是业务记录而非日志。

清理是**分批**的（每批 `repo.PURGE_BATCH` 行），所以单次事务不会长时间占住写锁。
SQLite 删除后不会把页还给操作系统，但空闲页会被后续写入复用，
因此文件大小会在"保留窗口的最大量"附近进入稳态，而不是无限增长（见 docs/05 §4）。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass

from ccnr_data import repo
from ccnr_data.clock import now_ms
from ccnr_data.config import Config
from ccnr_data.db import Database

__all__ = ["MS_PER_DAY", "PurgeReport", "RetentionPolicy", "RetentionWorker", "purge_once"]

LOGGER = logging.getLogger(__name__)

MS_PER_DAY = 24 * 60 * 60 * 1000

#: 后台轮换的运行间隔。固定 1 小时：清理是幂等且廉价的，不需要配置项。
PURGE_INTERVAL_SECONDS = 3600

#: 单个 RPC / 单轮清理最多跑多少批，防止一次清理长时间占住连接。
MAX_BATCHES_PER_TABLE = 200


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """各表的保留天数。0 = 永久保留（该表不清理）。"""

    event_days: int
    change_days: int
    audit_days: int
    idempotency_days: int

    @classmethod
    def from_config(cls, config: Config) -> RetentionPolicy:
        return cls(
            event_days=config.event_retention_days,
            change_days=config.change_retention_days,
            audit_days=config.audit_retention_days,
            idempotency_days=config.idempotency_retention_days,
        )

    def enabled(self) -> bool:
        return self.event_days > 0 or self.change_days > 0 or self.audit_days > 0 or self.idempotency_days > 0

    def describe(self) -> str:
        def show(days: int) -> str:
            return "永久" if days == 0 else f"{days} 天"

        return (
            f"事件={show(self.event_days)} 变更流={show(self.change_days)} "
            f"审计={show(self.audit_days)} 幂等键={show(self.idempotency_days)}"
        )


@dataclass(frozen=True, slots=True)
class PurgeReport:
    """一次清理删掉的行数。"""

    events: int = 0
    changes: int = 0
    audit: int = 0
    idempotency: int = 0

    @property
    def total(self) -> int:
        return self.events + self.changes + self.audit + self.idempotency

    def __bool__(self) -> bool:
        return self.total > 0


def _cutoff_ms(days: int, now: int) -> int | None:
    return None if days <= 0 else now - days * MS_PER_DAY


def _drain(db: Database, purge: Callable[[sqlite3.Connection, int], int], cutoff: int) -> int:
    """在独立事务里分批删，直到删空或触及批次上限。"""
    total = 0
    for _ in range(MAX_BATCHES_PER_TABLE):
        with db.write() as conn:
            removed = purge(conn, cutoff)
        total += removed
        if removed < repo.PURGE_BATCH:
            break
    return total


def purge_once(db: Database, policy: RetentionPolicy, *, now: int | None = None) -> PurgeReport:
    """按策略清理一轮，返回各表删除行数。"""
    if not policy.enabled():
        return PurgeReport()
    stamp = now if now is not None else now_ms()

    events = changes = audit = idempotency = 0
    cutoff = _cutoff_ms(policy.event_days, stamp)
    if cutoff is not None:
        events = _drain(db, repo.purge_events_before, cutoff)
    cutoff = _cutoff_ms(policy.change_days, stamp)
    if cutoff is not None:
        changes = _drain(db, repo.purge_changes_before, cutoff)
    cutoff = _cutoff_ms(policy.audit_days, stamp)
    if cutoff is not None:
        audit = _drain(db, repo.purge_audit_before, cutoff)
    cutoff = _cutoff_ms(policy.idempotency_days, stamp)
    if cutoff is not None:
        idempotency = _drain(db, repo.purge_idempotency_before, cutoff)

    report = PurgeReport(events=events, changes=changes, audit=audit, idempotency=idempotency)
    if report:
        LOGGER.info(
            "日志轮换清理：事件 %d 行、变更流 %d 行、审计 %d 行、幂等键 %d 行",
            events,
            changes,
            audit,
            idempotency,
        )
    return report


class RetentionWorker:
    """后台轮换线程。启动时先跑一轮（补上停机期间该清的），之后每小时一轮。"""

    def __init__(
        self, db: Database, policy: RetentionPolicy, *, interval_seconds: int = PURGE_INTERVAL_SECONDS
    ) -> None:
        self._db = db
        self._policy = policy
        self._interval = max(1, interval_seconds)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ccnr-data-retention", daemon=True)

    @property
    def is_running(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        if not self._policy.enabled():
            LOGGER.info("日志轮换已关闭（三张表都是永久保留）")
            return
        LOGGER.info("日志轮换已启用：%s", self._policy.describe())
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            try:
                purge_once(self._db, self._policy)
            except Exception:  # noqa: BLE001 - 清理失败绝不能带崩服务
                LOGGER.exception("日志轮换执行失败，下一轮重试")
            if self._stop.wait(self._interval):
                return
