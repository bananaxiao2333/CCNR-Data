# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""HTTP 边缘：只放健康、指标与（后续）身份回调，不做第二套业务 API。

用标准库 ThreadingHTTPServer + prometheus_client，避免为此引入 Web 框架。
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import literal, select

from ccnr_data.config import parse_bind
from ccnr_data.control.settings import ControlSettings
from ccnr_data.db import Database

__all__ = ["HttpEdge"]

LOGGER = logging.getLogger(__name__)


class _Handler(BaseHTTPRequestHandler):
    server_version = "ccnr-data"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的协议
        if self.path.split("?")[0] == "/metrics":
            body = generate_latest()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.split("?")[0] == "/healthz":
            database: Database = self.server.database  # type: ignore[attr-defined]
            settings: ControlSettings = self.server.settings  # type: ignore[attr-defined]
            try:
                with database.read() as session:
                    session.execute(select(literal(1))).scalar()
            except Exception:  # noqa: BLE001 - 健康检查只报告，不抛
                self._json(503, {"status": "error", "database": "error"})
                return
            self._json(
                200,
                {
                    "status": "ok",
                    "database": "ok",
                    "casdoor": "configured" if settings.casdoor_enabled else "disabled",
                },
            )
            return
        self._json(404, {"status": "not_found"})

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        LOGGER.debug("http edge: " + fmt, *args)


class HttpEdge:
    """在独立线程里跑的健康/指标端点。"""

    def __init__(self, bind: str, db: Database, settings: ControlSettings) -> None:
        host, port = parse_bind(bind)
        self._server = ThreadingHTTPServer((host, port), _Handler)
        self._server.daemon_threads = True
        self._server.database = db  # type: ignore[attr-defined]
        self._server.settings = settings  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, name="ccnr-data-http", daemon=True)
        self._started = False

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()
        LOGGER.info("HTTP 边缘已监听 %s:%d", *self._server.server_address[:2])

    def stop(self, timeout: float = 5.0) -> None:
        # serve_forever 没跑过时 shutdown() 会等一个永远不来的事件，必须先判断。
        if self._started:
            self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)
