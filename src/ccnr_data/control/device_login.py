# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""Device Code 轮询：把「玩家在 CCNR Pass 点了授权」变成身份投影。

网络调用在写事务之外；每次只处理一条待登录记录，避免一个慢请求拖住整批。
"""

from __future__ import annotations

import logging
import threading

from ccnr_data import repositories as repo
from ccnr_data.clock import now_ms
from ccnr_data.control.casdoor import (
    CasdoorClient,
    CasdoorError,
    DeviceAuthDenied,
    DeviceAuthExpired,
    DeviceAuthPending,
    DeviceAuthSlowDown,
)
from ccnr_data.db import Database
from ccnr_data.errors import DataServiceError

__all__ = ["DeviceLoginPoller"]

LOGGER = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 2
#: 历史登录记录保留一天，足够排障，也不会让表无限增长。
RETENTION_MS = 24 * 60 * 60 * 1000


class DeviceLoginPoller:
    def __init__(
        self,
        db: Database,
        casdoor: CasdoorClient,
        *,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._db = db
        self._casdoor = casdoor
        self._interval = max(1, interval_seconds)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ccnr-data-device-login", daemon=True)

    @property
    def is_running(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def poll_once(self) -> int:
        """处理一轮；返回状态发生变化的记录数（测试直接调用它）。"""
        now = now_ms()
        with self._db.read() as session:
            rows = repo.device_logins.pending(session, now=now)
        changed = 0
        for row in rows:
            login_id = str(row["id"])
            try:
                identity = self._casdoor.poll_device_token(str(row["device_code"]))
            except (DeviceAuthPending, DeviceAuthSlowDown):
                continue
            except DeviceAuthDenied as exc:
                self._mark(login_id, repo.device_logins.DENIED, str(exc))
                changed += 1
                continue
            except DeviceAuthExpired as exc:
                self._mark(login_id, repo.device_logins.EXPIRED, str(exc))
                changed += 1
                continue
            except CasdoorError:
                LOGGER.warning("device login %s 轮询失败，下一轮重试", login_id, exc_info=True)
                continue

            with self._db.write() as session:
                try:
                    repo.identities.upsert(
                        session,
                        player_uuid=str(row["player_uuid"]),
                        username=str(row["username"]),
                        casdoor_user_id=identity.casdoor_user_id,
                        source="PASS",
                        now=now,
                        overwrite=False,
                    )
                except DataServiceError as exc:
                    repo.device_logins.mark(session, login_id, repo.device_logins.DENIED, message=exc.detail)
                else:
                    repo.device_logins.mark(
                        session,
                        login_id,
                        repo.device_logins.APPROVED,
                        casdoor_user_id=identity.casdoor_user_id,
                        now=now,
                    )
                    LOGGER.info("device login 通过：%s（%s）", row["username"], identity.casdoor_user_id)
            changed += 1

        with self._db.write() as session:
            repo.device_logins.purge_before(session, now - RETENTION_MS)
        return changed

    def _mark(self, login_id: str, status: str, message: str) -> None:
        with self._db.write() as session:
            repo.device_logins.mark(session, login_id, status, message=message)

    def _run(self) -> None:
        while True:
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 - 轮询失败不能带崩服务
                LOGGER.exception("device login 轮询失败，下一轮重试")
            if self._stop.wait(self._interval):
                return
