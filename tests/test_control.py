# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""控制面：准入、身份、遥测统计、鉴权与 HTTP 边缘。

全部走真实 gRPC / HTTP 通道；Casdoor 用一个本地 HTTP 桩模拟，
测的是真实的 REST 客户端、缓存和熔断路径，而不是 mock 掉它们。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import grpc
import pytest
from google.protobuf.timestamp_pb2 import Timestamp

from ccnr_data.config import Config
from ccnr_data.control.settings import ControlSettings
from ccnr_data.db import Database
from ccnr_data.server import ServerHandle, build_server
from control.v1 import control_pb2, control_pb2_grpc
from dbutil import raw_connection
from moddata.v1 import moddata_pb2, moddata_pb2_grpc

UUID = "11111111-1111-1111-1111-111111111111"
UUID_2 = "22222222-2222-2222-2222-222222222222"
CASDOOR_ID = "casdoor-user-1"


# ---------------------------------------------------------------- Casdoor 桩


class _CasdoorHandler(BaseHTTPRequestHandler):
    users: dict[str, dict[str, object]] = {}

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 协议
        if self.path == "/api/login/oauth/access_token":
            self._send({"access_token": "test-token", "expires_in": 3600})
            return
        self._send({"status": "error"}, 404)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 协议
        parsed = urlparse(self.path)
        if parsed.path != "/api/get-user":
            self._send({"status": "error"}, 404)
            return
        query = parse_qs(parsed.query)
        key = (query.get("id") or query.get("name") or [""])[0]
        user = self.users.get(key)
        if user is None:
            self._send({"status": "error", "msg": "not found"}, 404)
            return
        self._send({"status": "ok", "data": user})

    def _send(self, payload: dict[str, object], code: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        pass


@pytest.fixture
def casdoor() -> Iterator[SimpleNamespace]:
    users: dict[str, dict[str, object]] = {}
    handler = type("Handler", (_CasdoorHandler,), {"users": users})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(url=f"http://127.0.0.1:{httpd.server_address[1]}", users=users)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _user(
    *, user_id: str = CASDOOR_ID, verified: bool = True, roles: tuple[str, ...] = ("member",)
) -> dict[str, object]:
    return {
        "id": user_id,
        "name": user_id,
        "displayName": user_id,
        "email": f"{user_id}@example.com",
        "emailVerified": verified,
        "owner": "ccnr",
        "roles": [{"name": role} for role in roles],
    }


# ---------------------------------------------------------------- 装配


def _settings(
    *,
    endpoint: str = "",
    fail_mode: str = "deny",
    tokens: dict[str, str] | None = None,
    heartbeat_ttl_s: int = 180,
) -> ControlSettings:
    return ControlSettings(
        http_bind="127.0.0.1:0",
        client_tokens=dict(tokens or {}),
        casdoor_endpoint=endpoint,
        casdoor_client_id="client" if endpoint else "",
        casdoor_client_secret="secret" if endpoint else "",
        casdoor_organization="ccnr",
        auth_fail_mode=fail_mode,
        heartbeat_ttl_s=heartbeat_ttl_s,
    )


@contextmanager
def _running(
    config: Config, db: Database, settings: ControlSettings
) -> Iterator[tuple[ServerHandle, control_pb2_grpc.ControlServiceStub, moddata_pb2_grpc.ModDataServiceStub]]:
    handle = build_server(config, db, settings)
    handle.server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{handle.port}")
    grpc.channel_ready_future(channel).result(timeout=10)
    try:
        yield (
            handle,
            control_pb2_grpc.ControlServiceStub(channel),  # type: ignore[no-untyped-call]
            moddata_pb2_grpc.ModDataServiceStub(channel),  # type: ignore[no-untyped-call]
        )
    finally:
        channel.close()
        handle.stop(grace=0)


def _bind(
    stub: control_pb2_grpc.ControlServiceStub,
    *,
    request_id: str = "bind-1",
    player_uuid: str = UUID,
    username: str = "Alice",
    casdoor_user_id: str = CASDOOR_ID,
    overwrite: bool = False,
) -> control_pb2.BindPlayerIdentityResponse:
    return stub.BindPlayerIdentity(
        control_pb2.BindPlayerIdentityRequest(
            request_id=request_id,
            player_uuid=player_uuid,
            username=username,
            casdoor_user_id=casdoor_user_id,
            source=control_pb2.IDENTITY_SOURCE_ADMIN,
            actor="test",
            overwrite=overwrite,
        )
    )


def _authorize(
    stub: control_pb2_grpc.ControlServiceStub,
    *,
    player_uuid: str = UUID,
    username: str = "Alice",
    server_id: str = "",
) -> control_pb2.AuthorizePlayerResponse:
    return stub.AuthorizePlayer(
        control_pb2.AuthorizePlayerRequest(player_uuid=player_uuid, username=username, server_id=server_id)
    )


def _report(
    stub: control_pb2_grpc.ControlServiceStub,
    *,
    request_id: str,
    kind: control_pb2.ProxyEventKind,
    session_id: str = "sess-1",
    player_uuid: str = UUID,
    username: str = "Alice",
    server_id: str = "lobby",
    from_server_id: str = "",
    deny_reason: str = "",
    end_reason: str = "",
    occurred_at: Timestamp | None = None,
) -> control_pb2.ReportProxyEventResponse:
    return stub.ReportProxyEvent(
        control_pb2.ReportProxyEventRequest(
            request_id=request_id,
            kind=kind,
            session_id=session_id,
            player_uuid=player_uuid,
            username=username,
            server_id=server_id,
            from_server_id=from_server_id,
            deny_reason=deny_reason,
            end_reason=end_reason,
            occurred_at=occurred_at if occurred_at is not None else Timestamp(),
        )
    )


def _count(db: Database, table: str) -> int:
    conn = raw_connection(db)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _past(delta_seconds: int) -> Timestamp:
    stamp = Timestamp()
    stamp.FromSeconds(int(time.time()) - delta_seconds)
    return stamp


# ---------------------------------------------------------------- 准入与身份


def test_authorize_unlinked_is_not_linked(config: Config, db: Database) -> None:
    with _running(config, db, _settings()) as (_handle, stub, _mod):
        response = _authorize(stub)
        assert response.allowed is False
        assert response.reason == control_pb2.AUTHORIZE_REASON_NOT_LINKED
        assert response.message


def test_bind_then_resolve_by_all_subjects(config: Config, db: Database) -> None:
    with _running(config, db, _settings()) as (_handle, stub, _mod):
        bound = _bind(stub)
        assert bound.success and bound.created
        assert bound.player_uuid == UUID

        by_uuid = stub.ResolvePlayer(control_pb2.ResolvePlayerRequest(player_uuid=UUID))
        assert by_uuid.found and by_uuid.username == "Alice"
        assert by_uuid.casdoor_user_id == CASDOOR_ID

        by_name = stub.ResolvePlayer(control_pb2.ResolvePlayerRequest(username="alice"))
        assert by_name.found and by_name.player_uuid == UUID

        by_casdoor = stub.ResolvePlayer(control_pb2.ResolvePlayerRequest(casdoor_user_id=CASDOOR_ID))
        assert by_casdoor.found and by_casdoor.player_uuid == UUID

        missing = stub.ResolvePlayer(control_pb2.ResolvePlayerRequest(player_uuid=UUID_2))
        assert missing.found is False

        with pytest.raises(grpc.RpcError) as err:
            stub.ResolvePlayer(control_pb2.ResolvePlayerRequest())
        assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_rebind_requires_overwrite(config: Config, db: Database) -> None:
    with _running(config, db, _settings()) as (_handle, stub, _mod):
        _bind(stub)
        with pytest.raises(grpc.RpcError) as err:
            _bind(stub, request_id="bind-2", casdoor_user_id="other-user")
        assert err.value.code() == grpc.StatusCode.FAILED_PRECONDITION

        changed = _bind(stub, request_id="bind-3", casdoor_user_id="other-user", overwrite=True)
        assert changed.success and changed.created is False
        assert changed.casdoor_user_id == "other-user"


def test_authorize_allow_ban_whitelist(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    casdoor.users[CASDOOR_ID] = _user()
    with _running(config, db, _settings(endpoint=casdoor.url)) as (_handle, stub, _mod):
        _bind(stub)
        allowed = _authorize(stub)
        assert allowed.allowed is True
        assert allowed.reason == control_pb2.AUTHORIZE_REASON_ALLOWED
        assert allowed.cache_ttl_seconds > 0

        denied = stub.SetAccessRule(
            control_pb2.SetAccessRuleRequest(
                request_id="ban-1",
                subject_type=control_pb2.SUBJECT_TYPE_PLAYER_UUID,
                subject=UUID,
                effect=control_pb2.RULE_EFFECT_DENY,
                reason="测试封禁",
                actor="test",
            )
        )
        assert denied.rule.effect == control_pb2.RULE_EFFECT_DENY
        banned = _authorize(stub)
        assert banned.allowed is False
        assert banned.reason == control_pb2.AUTHORIZE_REASON_BANNED
        assert "测试封禁" in banned.message

        stub.DeleteAccessRule(control_pb2.DeleteAccessRuleRequest(request_id="unban-1", id=denied.rule.id))
        assert _authorize(stub).allowed is True

        stub.SetAccessPolicy(
            control_pb2.SetAccessPolicyRequest(
                request_id="whitelist-1",
                scope="",
                mode=control_pb2.ACCESS_MODE_WHITELIST,
                actor="test",
            )
        )
        whitelist = _authorize(stub)
        assert whitelist.allowed is False
        assert whitelist.reason == control_pb2.AUTHORIZE_REASON_WHITELIST_ONLY

        stub.SetAccessRule(
            control_pb2.SetAccessRuleRequest(
                request_id="allow-1",
                subject_type=control_pb2.SUBJECT_TYPE_USERNAME,
                subject="Alice",
                effect=control_pb2.RULE_EFFECT_ALLOW,
                actor="test",
            )
        )
        assert _authorize(stub).allowed is True

        policies = stub.ListAccessPolicies(control_pb2.ListAccessPoliciesRequest())
        assert [(item.scope, item.mode) for item in policies.policies] == [
            ("", control_pb2.ACCESS_MODE_WHITELIST)
        ]


def test_expired_rule_does_not_ban(config: Config, db: Database) -> None:
    with _running(config, db, _settings()) as (_handle, stub, _mod):
        _bind(stub)
        stub.SetAccessRule(
            control_pb2.SetAccessRuleRequest(
                request_id="ban-expired",
                subject_type=control_pb2.SUBJECT_TYPE_PLAYER_UUID,
                subject=UUID,
                effect=control_pb2.RULE_EFFECT_DENY,
                expires_at=_past(60),
                actor="test",
            )
        )
        response = _authorize(stub)
        # 身份已绑定但 Casdoor 未配置，因此落在 POLICY_ERROR 而不是 BANNED。
        assert response.reason == control_pb2.AUTHORIZE_REASON_POLICY_ERROR


def test_casdoor_disabled_refuses_linked_player(config: Config, db: Database) -> None:
    with _running(config, db, _settings()) as (_handle, stub, _mod):
        _bind(stub)
        response = _authorize(stub)
        assert response.allowed is False
        assert response.reason == control_pb2.AUTHORIZE_REASON_POLICY_ERROR


def test_email_unverified(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    casdoor.users[CASDOOR_ID] = _user(verified=False)
    with _running(config, db, _settings(endpoint=casdoor.url)) as (_handle, stub, _mod):
        _bind(stub)
        response = _authorize(stub)
        assert response.allowed is False
        assert response.reason == control_pb2.AUTHORIZE_REASON_EMAIL_UNVERIFIED


def test_role_requirement_is_scoped(config: Config, db: Database, casdoor: SimpleNamespace) -> None:
    casdoor.users[CASDOOR_ID] = _user(roles=("guest",))
    with _running(config, db, _settings(endpoint=casdoor.url)) as (_handle, stub, mod):
        _bind(stub)
        mod.UpdateServerConfig(
            moddata_pb2.UpdateServerConfigRequest(
                request_id="cfg-1",
                server_id="survival",
                config_json='{"required_roles": ["admin"]}',
                actor="test",
            )
        )
        denied = _authorize(stub, server_id="survival")
        assert denied.allowed is False
        assert denied.reason == control_pb2.AUTHORIZE_REASON_ROLE_DENIED
        assert _authorize(stub, server_id="lobby").allowed is True


def test_casdoor_outage_modes(config: Config, db: Database) -> None:
    dead = "http://127.0.0.1:1"
    with _running(config, db, _settings(endpoint=dead)) as (_handle, stub, _mod):
        _bind(stub)
        response = _authorize(stub)
        assert response.allowed is False
        assert response.reason == control_pb2.AUTHORIZE_REASON_CASDOOR_UNAVAILABLE

    with _running(config, db, _settings(endpoint=dead, fail_mode="allow")) as (_handle, stub, _mod):
        _bind(stub, request_id="bind-allow")
        response = _authorize(stub)
        assert response.allowed is True
        assert response.reason == control_pb2.AUTHORIZE_REASON_ALLOWED


# ---------------------------------------------------------------- 遥测与统计


def test_session_lifecycle_and_statistics(config: Config, db: Database) -> None:
    with _running(config, db, _settings()) as (_handle, stub, _mod):
        _bind(stub)
        started = _report(stub, request_id="ev-1", kind=control_pb2.PROXY_EVENT_KIND_SESSION_STARTED)
        assert started.success is True

        online = stub.ListOnlinePlayers(control_pb2.ListOnlinePlayersRequest())
        assert online.total == 1
        assert online.players[0].player_uuid == UUID
        assert online.players[0].server_id == "lobby"

        # 心跳只刷新 last_seen：不写事件表、不占幂等键。
        assert _count(db, "proxy_events") == 1
        before = _count(db, "idempotency")
        heartbeat = _report(stub, request_id="hb-1", kind=control_pb2.PROXY_EVENT_KIND_SESSION_HEARTBEAT)
        assert heartbeat.success is True
        assert _count(db, "proxy_events") == 1
        assert _count(db, "idempotency") == before

        assert _report(
            stub,
            request_id="ev-2",
            kind=control_pb2.PROXY_EVENT_KIND_SERVER_SWITCHED,
            server_id="survival",
            from_server_id="lobby",
        ).success
        switched = stub.ListOnlinePlayers(control_pb2.ListOnlinePlayersRequest())
        assert switched.players[0].server_id == "survival"

        assert _report(
            stub,
            request_id="ev-3",
            kind=control_pb2.PROXY_EVENT_KIND_SESSION_ENDED,
            server_id="survival",
            end_reason="quit",
        ).success
        assert stub.ListOnlinePlayers(control_pb2.ListOnlinePlayersRequest()).total == 0

        playtime = stub.GetPlayerPlaytime(control_pb2.GetPlayerPlaytimeRequest(player_uuid=UUID))
        assert playtime.found is True
        assert playtime.sessions == 1
        assert playtime.servers[0].server_id == "survival"

        from_time = Timestamp()
        from_time.FromSeconds(int(time.time()) - 3600)
        stats = stub.GetProxyStats(control_pb2.GetProxyStatsRequest(from_time=from_time))
        assert stats.unique_players == 1
        assert stats.sessions == 1
        assert stats.servers[0].peak_online == 1

        assert _count(db, "proxy_events") == 3


def test_report_is_idempotent_and_rejects_key_reuse(config: Config, db: Database) -> None:
    with _running(config, db, _settings()) as (_handle, stub, _mod):
        _report(stub, request_id="ev-1", kind=control_pb2.PROXY_EVENT_KIND_SESSION_STARTED)
        replay = _report(stub, request_id="ev-1", kind=control_pb2.PROXY_EVENT_KIND_SESSION_STARTED)
        assert replay.success is True
        assert _count(db, "proxy_events") == 1

        with pytest.raises(grpc.RpcError) as err:
            _report(
                stub,
                request_id="ev-1",
                kind=control_pb2.PROXY_EVENT_KIND_SESSION_ENDED,
                end_reason="quit",
            )
        assert err.value.code() == grpc.StatusCode.FAILED_PRECONDITION


def test_report_validates_required_fields(config: Config, db: Database) -> None:
    with _running(config, db, _settings()) as (_handle, stub, _mod):
        with pytest.raises(grpc.RpcError) as missing_server:
            _report(
                stub,
                request_id="ev-1",
                kind=control_pb2.PROXY_EVENT_KIND_SESSION_STARTED,
                server_id="",
            )
        assert missing_server.value.code() == grpc.StatusCode.INVALID_ARGUMENT

        with pytest.raises(grpc.RpcError) as missing_reason:
            _report(
                stub,
                request_id="ev-2",
                kind=control_pb2.PROXY_EVENT_KIND_LOGIN_DENIED,
                deny_reason="",
            )
        assert missing_reason.value.code() == grpc.StatusCode.INVALID_ARGUMENT

        with pytest.raises(grpc.RpcError) as bad_switch:
            _report(
                stub,
                request_id="ev-3",
                kind=control_pb2.PROXY_EVENT_KIND_SERVER_SWITCHED,
            )
        assert bad_switch.value.code() == grpc.StatusCode.INVALID_ARGUMENT

        unknown = _report(stub, request_id="hb-unknown", kind=control_pb2.PROXY_EVENT_KIND_SESSION_HEARTBEAT)
        assert unknown.success is False


def test_login_denied_events_feed_stats(config: Config, db: Database) -> None:
    with _running(config, db, _settings()) as (_handle, stub, _mod):
        _report(
            stub,
            request_id="deny-1",
            kind=control_pb2.PROXY_EVENT_KIND_LOGIN_DENIED,
            server_id="lobby",
            deny_reason="NOT_LINKED",
        )
        stats = stub.GetProxyStats(control_pb2.GetProxyStatsRequest())
        assert stats.login_failures == 1
        assert [(item.reason, item.count) for item in stats.denies] == [("NOT_LINKED", 1)]


# ---------------------------------------------------------------- 鉴权与 HTTP 边缘


def test_control_token_required(config: Config, db: Database) -> None:
    settings = _settings(tokens={"proxy": "s3cret"})
    with _running(config, db, settings) as (_handle, stub, _mod):
        with pytest.raises(grpc.RpcError) as missing:
            stub.ListOnlinePlayers(control_pb2.ListOnlinePlayersRequest())
        assert missing.value.code() == grpc.StatusCode.UNAUTHENTICATED

        with pytest.raises(grpc.RpcError) as wrong:
            stub.ListOnlinePlayers(
                control_pb2.ListOnlinePlayersRequest(),
                metadata=(("authorization", "Bearer nope"),),
            )
        assert wrong.value.code() == grpc.StatusCode.UNAUTHENTICATED

        ok = stub.ListOnlinePlayers(
            control_pb2.ListOnlinePlayersRequest(),
            metadata=(("authorization", "Bearer s3cret"),),
        )
        assert ok.total == 0


def test_http_edge_health_and_metrics(config: Config, db: Database) -> None:
    with _running(config, db, _settings()) as (handle, _stub, _mod):
        assert handle.http_edge is not None
        handle.http_edge.start()
        base = f"http://127.0.0.1:{handle.http_edge.port}"

        with urllib.request.urlopen(f"{base}/healthz", timeout=5) as response:
            assert response.status == 200
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["status"] == "ok"
            assert payload["database"] == "ok"

        with urllib.request.urlopen(f"{base}/metrics", timeout=5) as response:
            body = response.read().decode("utf-8")
            assert "ccnr_control_authorize_total" in body

        with pytest.raises(urllib.error.HTTPError) as not_found:
            urllib.request.urlopen(f"{base}/nope", timeout=5)
        assert not_found.value.code == 404


def test_duplicate_username_cannot_be_stolen(config: Config, db: Database) -> None:
    with _running(config, db, _settings()) as (_handle, stub, _mod):
        _bind(stub)
        with pytest.raises(grpc.RpcError) as err:
            _bind(stub, request_id="bind-2", player_uuid=UUID_2, username="Alice")
        assert err.value.code() == grpc.StatusCode.FAILED_PRECONDITION
