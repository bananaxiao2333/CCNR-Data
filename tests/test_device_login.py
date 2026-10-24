# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""Device Code 登录：Begin / 轮询 / 绑定 / 拒绝 / 过期。

Casdoor 用本地 HTTP 桩模拟，但走真实的 httpx 客户端、JWT 解析与轮询 worker。
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs

import grpc
import pytest
from sqlalchemy import update

from ccnr_data import repositories as repo
from ccnr_data.config import Config
from ccnr_data.control.settings import ControlSettings
from ccnr_data.db import Database
from ccnr_data.models import DeviceLogin
from ccnr_data.server import build_server
from control.v1 import control_pb2, control_pb2_grpc

UUID = "44444444-4444-4444-4444-444444444444"
USER = "testuser"


def _jwt(claims: dict[str, object]) -> str:
    def enc(data: dict[str, object]) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


class _CasdoorHandler(BaseHTTPRequestHandler):
    mode = "pending"
    user_code = "ABCD-EFGH"
    device_code = "device-code-1"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 协议
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode())
        if self.path == "/api/device-auth":
            self._json(
                {
                    "device_code": self.device_code,
                    "user_code": self.user_code,
                    "verification_uri": "http://pass.example/device",
                    "expires_in": 120,
                    "interval": 1,
                }
            )
            return
        if self.path == "/api/login/oauth/access_token":
            grant = (form.get("grant_type") or [""])[0]
            assert grant == "urn:ietf:params:oauth:grant-type:device_code"
            if self.mode == "pending":
                self._json({"error": "authorization_pending"})
            elif self.mode == "denied":
                self._json({"error": "access_denied"})
            else:
                token = _jwt({"owner": "ccnr", "preferred_username": USER, "sub": "sub-1"})
                self._json({"access_token": token, "expires_in": 604800})
            return
        self._json({"status": "error", "msg": "not found"}, 404)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 协议
        if self.path.startswith("/api/get-user"):
            self._json(
                {
                    "status": "ok",
                    "data": {
                        "id": "uuid-1",
                        "name": USER,
                        "displayName": USER,
                        "email": f"{USER}@example.com",
                        "emailVerified": True,
                        "owner": "ccnr",
                        "roles": [],
                    },
                }
            )
            return
        self._json({"status": "error", "msg": "not found"}, 404)

    def _json(self, payload: dict[str, object], code: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        pass


@pytest.fixture
def casdoor() -> Iterator[SimpleNamespace]:
    handler = type("Handler", (_CasdoorHandler,), {})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(url=f"http://127.0.0.1:{httpd.server_address[1]}", handler=handler)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _settings(endpoint: str, tokens: dict[str, str] | None = None) -> ControlSettings:
    return ControlSettings(
        http_bind="127.0.0.1:0",
        client_tokens=dict(tokens or {}),
        casdoor_endpoint=endpoint,
        casdoor_client_id="client",
        casdoor_client_secret="secret",
        casdoor_organization="ccnr",
        auth_fail_mode="deny",
    )


@contextmanager
def _running(
    config: Config, db: Database, settings: ControlSettings
) -> Iterator[tuple[control_pb2_grpc.ControlServiceStub, object]]:
    handle = build_server(config, db, settings)
    handle.server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{handle.port}")
    grpc.channel_ready_future(channel).result(timeout=10)
    try:
        yield control_pb2_grpc.ControlServiceStub(channel), handle  # type: ignore[no-untyped-call]
    finally:
        channel.close()
        handle.stop(grace=0)


def _begin(stub: control_pb2_grpc.ControlServiceStub) -> control_pb2.BeginDeviceLoginResponse:
    return stub.BeginDeviceLogin(
        control_pb2.BeginDeviceLoginRequest(player_uuid=UUID, username=USER, proxy_id="velocity-test")
    )


def test_device_login_binds_identity(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    with _running(config, db, _settings(casdoor.url)) as (stub, handle):
        begun = _begin(stub)
        assert begun.user_code == "ABCD-EFGH"
        assert begun.verification_uri.startswith("http://pass.example/")
        pending = stub.GetDeviceLoginStatus(control_pb2.GetDeviceLoginStatusRequest(login_id=begun.login_id))
        assert pending.status == control_pb2.DEVICE_LOGIN_STATUS_PENDING

        casdoor.handler.mode = "approved"
        assert handle.device_poller.poll_once() == 1  # type: ignore[union-attr]
        approved = stub.GetDeviceLoginStatus(control_pb2.GetDeviceLoginStatusRequest(login_id=begun.login_id))
        assert approved.status == control_pb2.DEVICE_LOGIN_STATUS_APPROVED
        assert approved.casdoor_user_id == "ccnr/testuser"
        assert approved.player_uuid == UUID

        resolved = stub.ResolvePlayer(control_pb2.ResolvePlayerRequest(player_uuid=UUID))
        assert resolved.found is True
        assert resolved.casdoor_user_id == "ccnr/testuser"


def test_device_login_denied(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    with _running(config, db, _settings(casdoor.url)) as (stub, handle):
        begun = _begin(stub)
        casdoor.handler.mode = "denied"
        handle.device_poller.poll_once()  # type: ignore[union-attr]
        status = stub.GetDeviceLoginStatus(control_pb2.GetDeviceLoginStatusRequest(login_id=begun.login_id))
        assert status.status == control_pb2.DEVICE_LOGIN_STATUS_DENIED
        assert "拒绝" in status.message


def test_approve_by_code_binds_identity(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    with _running(config, db, _settings(casdoor.url)) as (stub, _handle):
        begun = _begin(stub)
        approved = stub.ApproveDeviceLogin(
            control_pb2.ApproveDeviceLoginRequest(
                user_code=begun.user_code,
                casdoor_user_id="ccnr/qq-user",
                actor="bot",
            )
        )
        assert approved.success is True
        assert approved.player_uuid == UUID
        status = stub.GetDeviceLoginStatus(control_pb2.GetDeviceLoginStatusRequest(login_id=begun.login_id))
        assert status.status == control_pb2.DEVICE_LOGIN_STATUS_APPROVED
        assert status.casdoor_user_id == "ccnr/qq-user"


def test_http_approve_requires_token(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    with _running(config, db, _settings(casdoor.url, tokens={"bot": "s3cret"})) as (_stub, handle):
        now = int(time.time() * 1000)
        with db.write() as session:
            repo.device_logins.create(
                session,
                login_id="http-login",
                device_code="device-code-http",
                user_code="HTTP01",
                player_uuid=UUID,
                username=USER,
                proxy_id="test",
                purpose="GAME",
                interval_s=1,
                created_at=now,
                expires_at=now + 60000,
            )
        assert handle.http_edge is not None  # type: ignore[union-attr]
        handle.http_edge.start()  # type: ignore[union-attr]
        url = f"http://127.0.0.1:{handle.http_edge.port}/internal/device/approve"  # type: ignore[union-attr]
        payload = json.dumps(
            {"user_code": "HTTP01", "casdoor_user_id": "ccnr/qq-user", "actor": "bot"}
        ).encode()
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(urllib.request.Request(url, data=payload, method="POST"), timeout=5)
        assert denied.value.code == 401

        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer s3cret",
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read())
        assert body["status"] == "ok"
        assert body["player_uuid"] == UUID


def test_device_login_expires(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    with _running(config, db, _settings(casdoor.url)) as (stub, handle):
        begun = _begin(stub)
        assert begun.expires_in == 120
        # 把记录改成已过期，验证惰性 EXPIRED（不依赖真实等待）。
        with db.write() as session:
            session.execute(
                update(DeviceLogin)
                .where(DeviceLogin.id == begun.login_id)
                .values(expires_at=int(time.time() * 1000) - 1)
            )
        status = stub.GetDeviceLoginStatus(control_pb2.GetDeviceLoginStatusRequest(login_id=begun.login_id))
        assert status.status == control_pb2.DEVICE_LOGIN_STATUS_EXPIRED


def test_device_login_requires_valid_ids(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    with _running(config, db, _settings(casdoor.url)) as (stub, _handle):
        with pytest.raises(grpc.RpcError) as bad_uuid:
            stub.BeginDeviceLogin(
                control_pb2.BeginDeviceLoginRequest(player_uuid="not-a-uuid", username=USER)
            )
        assert bad_uuid.value.code() == grpc.StatusCode.INVALID_ARGUMENT

        with pytest.raises(grpc.RpcError) as missing:
            stub.GetDeviceLoginStatus(control_pb2.GetDeviceLoginStatusRequest(login_id="no-such-login"))
        assert missing.value.code() == grpc.StatusCode.NOT_FOUND


def _begin_link(
    stub: control_pb2_grpc.ControlServiceStub, expected: str
) -> control_pb2.BeginDeviceLoginResponse:
    return stub.BeginDeviceLogin(
        control_pb2.BeginDeviceLoginRequest(
            username="platform-user", purpose="LINK", expected_casdoor_user_id=expected
        )
    )


def test_link_login_only_accepts_expected_account(
    config: Config, db: Database, casdoor: SimpleNamespace
) -> None:
    with _running(config, db, _settings(casdoor.url)) as (stub, handle):
        begun = _begin_link(stub, "ccnr/testuser")
        casdoor.handler.mode = "approved"
        assert handle.device_poller.poll_once() == 1  # type: ignore[union-attr]

        status = stub.GetDeviceLoginStatus(control_pb2.GetDeviceLoginStatusRequest(login_id=begun.login_id))
        assert status.status == control_pb2.DEVICE_LOGIN_STATUS_APPROVED
        assert status.casdoor_user_id == "ccnr/testuser"

        link = stub.GetAccountLink(control_pb2.GetAccountLinkRequest(user_id="platform-user"))
        assert link.found is True
        assert link.link.casdoor_user_id == "ccnr/testuser"
        assert link.link.source == "PASS"


def test_link_login_accepts_bare_username(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    with _running(config, db, _settings(casdoor.url)) as (stub, handle):
        begun = _begin_link(stub, "testuser")
        casdoor.handler.mode = "approved"
        assert handle.device_poller.poll_once() == 1  # type: ignore[union-attr]

        status = stub.GetDeviceLoginStatus(control_pb2.GetDeviceLoginStatusRequest(login_id=begun.login_id))
        assert status.status == control_pb2.DEVICE_LOGIN_STATUS_APPROVED
        assert status.casdoor_user_id == "ccnr/testuser"


def test_link_login_rejects_other_account(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    with _running(config, db, _settings(casdoor.url)) as (stub, handle):
        begun = _begin_link(stub, "ccnr/someone-else")
        casdoor.handler.mode = "approved"
        assert handle.device_poller.poll_once() == 1  # type: ignore[union-attr]

        status = stub.GetDeviceLoginStatus(control_pb2.GetDeviceLoginStatusRequest(login_id=begun.login_id))
        assert status.status == control_pb2.DEVICE_LOGIN_STATUS_DENIED
        assert "不一致" in status.message
        assert "ccnr/testuser" in status.message

        link = stub.GetAccountLink(control_pb2.GetAccountLinkRequest(user_id="platform-user"))
        assert link.found is False


def test_approve_link_rejects_other_account(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    with _running(config, db, _settings(casdoor.url)) as (stub, _handle):
        begun = _begin_link(stub, "ccnr/testuser")
        with pytest.raises(grpc.RpcError) as mismatch:
            stub.ApproveDeviceLogin(
                control_pb2.ApproveDeviceLoginRequest(
                    user_code=begun.user_code, casdoor_user_id="ccnr/someone-else", actor="bot"
                )
            )
        assert mismatch.value.code() == grpc.StatusCode.INVALID_ARGUMENT

        # 拒绝发生在写事务里，事务回滚后会话仍是 PENDING；轮询路径才会落 DENIED。
        status = stub.GetDeviceLoginStatus(control_pb2.GetDeviceLoginStatusRequest(login_id=begun.login_id))
        assert status.status == control_pb2.DEVICE_LOGIN_STATUS_PENDING
