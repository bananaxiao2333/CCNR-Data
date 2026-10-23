# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""会话收尾：代理崩溃后不能永远显示在线。

每 60 秒把 last_seen 早于阈值的未结束会话收尾；与日志轮换分开，
因为轮换是小时级、收尾是分钟级。
"""

from __future__ import annotations

import logging
import threading

from ccnr_data import repositories as repo
from ccnr_data.clock import now_ms
from ccnr_data.db import Database

__all__ = ["SessionReaper"]

LOGGER = logging.getLogger(__name__)

REAP_INTERVAL_SECONDS = 60


class SessionReaper:
    def __init__(
        self, db: Database, *, idle_seconds: int, interval_seconds: int = REAP_INTERVAL_SECONDS
    ) -> None:
        self._db = db
        self._idle_ms = idle_seconds * 1000
        self._interval = max(10, interval_seconds)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ccnr-data-reaper", daemon=True)

    @property
    def is_running(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            try:
                now = now_ms()
                with self._db.write() as session:
                    closed = repo.proxy.reap_stale(session, cutoff=now - self._idle_ms, now=now)
                if closed:
                    LOGGER.info("会话收尾：%d 个超时会话", closed)
            except Exception:  # noqa: BLE001 - 收尾失败不能带崩服务
                LOGGER.exception("会话收尾失败，下一轮重试")
            if self._stop.wait(self._interval):
                return
