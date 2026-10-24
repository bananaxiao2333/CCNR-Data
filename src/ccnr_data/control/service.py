# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""control.v1 实现：准入、身份、会话统计与查询。

与 ModDataService 的分层一致：校验 → 规则 → repositories → 组响应。
本文件不写 SQL，事务边界由 Database.read()/write() 决定。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from typing import NoReturn

import grpc
from google.protobuf import json_format
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ccnr_data import repositories as repo
from ccnr_data import validation
from ccnr_data.clock import now_ms
from ccnr_data.control import authorize
from ccnr_data.control.casdoor import CasdoorClient
from ccnr_data.control.metrics import (
    AUTHORIZE_LATENCY,
    AUTHORIZE_TOTAL,
    REPORTS_TOTAL,
    SESSIONS_ONLINE,
)
from ccnr_data.control.settings import ControlSettings
from ccnr_data.db import Database
from ccnr_data.errors import DataServiceError, invalid_argument, not_found
from control.v1 import control_pb2, control_pb2_grpc

__all__ = ["ControlService"]

LOGGER = logging.getLogger(__name__)

#: 在线列表默认/最大条数。
DEFAULT_ONLINE_LIMIT = 500
MAX_ONLINE_LIMIT = 5000

#: 聚合统计的峰值桶宽（5 分钟）。
PEAK_BUCKET_MS = 5 * 60 * 1000

#: occurred_at 允许的客户端时钟偏移：往前 24 小时、往后 5 分钟。
OCCURRED_BACK_MS = 24 * 60 * 60 * 1000
OCCURRED_AHEAD_MS = 5 * 60 * 1000

_REASONS = {
    "ALLOWED": control_pb2.AuthorizeReason.AUTHORIZE_REASON_ALLOWED,
    "NOT_LINKED": control_pb2.AuthorizeReason.AUTHORIZE_REASON_NOT_LINKED,
    "EMAIL_UNVERIFIED": control_pb2.AuthorizeReason.AUTHORIZE_REASON_EMAIL_UNVERIFIED,
    "BANNED": control_pb2.AuthorizeReason.AUTHORIZE_REASON_BANNED,
    "WHITELIST_ONLY": control_pb2.AuthorizeReason.AUTHORIZE_REASON_WHITELIST_ONLY,
    "ROLE_DENIED": control_pb2.AuthorizeReason.AUTHORIZE_REASON_ROLE_DENIED,
    "CASDOOR_UNAVAILABLE": control_pb2.AuthorizeReason.AUTHORIZE_REASON_CASDOOR_UNAVAILABLE,
    "POLICY_ERROR": control_pb2.AuthorizeReason.AUTHORIZE_REASON_POLICY_ERROR,
}

_SUBJECT_TYPES = {
    "PLAYER_UUID": control_pb2.SubjectType.SUBJECT_TYPE_PLAYER_UUID,
    "USERNAME": control_pb2.SubjectType.SUBJECT_TYPE_USERNAME,
    "CASDOOR_USER": control_pb2.SubjectType.SUBJECT_TYPE_CASDOOR_USER,
}
_EFFECTS = {
    "ALLOW": control_pb2.RuleEffect.RULE_EFFECT_ALLOW,
    "DENY": control_pb2.RuleEffect.RULE_EFFECT_DENY,
}
_KINDS = {
    "SESSION_STARTED": control_pb2.ProxyEventKind.PROXY_EVENT_KIND_SESSION_STARTED,
    "SESSION_HEARTBEAT": control_pb2.ProxyEventKind.PROXY_EVENT_KIND_SESSION_HEARTBEAT,
    "SERVER_SWITCHED": control_pb2.ProxyEventKind.PROXY_EVENT_KIND_SERVER_SWITCHED,
    "SESSION_ENDED": control_pb2.ProxyEventKind.PROXY_EVENT_KIND_SESSION_ENDED,
    "LOGIN_DENIED": control_pb2.ProxyEventKind.PROXY_EVENT_KIND_LOGIN_DENIED,
}
_MODES = {
    "OPEN": control_pb2.ACCESS_MODE_OPEN,
    "WHITELIST": control_pb2.ACCESS_MODE_WHITELIST,
}
_SOURCES = {
    "ADMIN": control_pb2.IdentitySource.IDENTITY_SOURCE_ADMIN,
    "BOT": control_pb2.IdentitySource.IDENTITY_SOURCE_BOT,
    "SKIN": control_pb2.IdentitySource.IDENTITY_SOURCE_SKIN,
    "IMPORT": control_pb2.IdentitySource.IDENTITY_SOURCE_IMPORT,
    "PASS": control_pb2.IdentitySource.IDENTITY_SOURCE_PASS,
}
_DEVICE_STATUS = {
    "PENDING": control_pb2.DEVICE_LOGIN_STATUS_PENDING,
    "APPROVED": control_pb2.DEVICE_LOGIN_STATUS_APPROVED,
    "DENIED": control_pb2.DEVICE_LOGIN_STATUS_DENIED,
    "EXPIRED": control_pb2.DEVICE_LOGIN_STATUS_EXPIRED,
}


def _ts(ms: int) -> Timestamp:
    return Timestamp(seconds=ms // 1000, nanos=(ms % 1000) * 1000)


def _ms(stamp: Timestamp) -> int:
    if int(stamp.seconds) == 0 and int(stamp.nanos) == 0:
        return 0
    return int(stamp.seconds) * 1000 + int(stamp.nanos) // 1_000_000


def _hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _enum_name(value: int, mapping: Mapping[str, object], field: str) -> str:
    for name, number in mapping.items():
        if number == value:
            return name
    raise invalid_argument(f"{field} 不是已定义的值：{value}")


def _rule_message(row: RowMapping) -> control_pb2.AccessRule:
    rule = control_pb2.AccessRule(
        id=int(row["id"]),
        subject_type=_SUBJECT_TYPES[str(row["subject_type"])],
        subject=str(row["subject"]),
        effect=_EFFECTS[str(row["effect"])],
        scope=str(row["scope"]),
        reason=str(row["reason"]),
        actor=str(row["actor"]),
        created_at=_ts(int(row["created_at"])),
    )
    if row["expires_at"] is not None:
        rule.expires_at.CopyFrom(_ts(int(row["expires_at"])))
    return rule


def _account_link_message(row: RowMapping) -> control_pb2.AccountLink:
    return control_pb2.AccountLink(
        user_id=str(row["user_id"]),
        casdoor_user_id=str(row["casdoor_user_id"]),
        source=str(row["source"]),
        linked_at=_ts(int(row["linked_at"])),
    )


def _policy_message(row: RowMapping) -> control_pb2.AccessPolicy:
    return control_pb2.AccessPolicy(
        scope=str(row["scope"]),
        mode=_MODES[str(row["mode"]).upper()],
        updated_at=_ts(int(row["updated_at"])),
    )


def _parse_cached[MsgT: Message](raw: str, out: MsgT) -> MsgT:
    json_format.Parse(raw, out, ignore_unknown_fields=True)
    return out


def _abort(context: grpc.ServicerContext, code: grpc.StatusCode, detail: str) -> NoReturn:
    context.abort(code, detail)
    raise AssertionError("context.abort 不应返回")  # pragma: no cover


def _occurred(value: int, now: int) -> int:
    """把客户端时间夹进可接受窗口，避免坏时钟把统计踢出时间轴。"""
    return min(max(value, now - OCCURRED_BACK_MS), now + OCCURRED_AHEAD_MS)


def _clip_seconds(row: RowMapping, from_ms: int, to_ms: int) -> int:
    start = int(row["started_at"])
    end = int(row["ended_at"] if row["ended_at"] is not None else row["last_seen_at"])
    start = max(start, from_ms) if from_ms > 0 else start
    end = min(end, to_ms) if to_ms > 0 else end
    return max(0, end - start) // 1000


class ControlService(control_pb2_grpc.ControlServiceServicer):
    """控制面实现（同步；线程池即并发模型）。"""

    def __init__(self, db: Database, settings: ControlSettings, casdoor: CasdoorClient | None = None) -> None:
        self._db = db
        self._settings = settings
        self._owns_casdoor = casdoor is None
        self._casdoor = casdoor or CasdoorClient(settings)

    @property
    def casdoor(self) -> CasdoorClient:
        """与 DeviceLoginPoller 共用一个客户端（token/用户缓存、熔断共享）。"""
        return self._casdoor

    def close(self) -> None:
        if self._owns_casdoor:
            self._casdoor.close()

    # ------------------------------------------------------------ 错误映射

    def _handle[RespT: Message](
        self, context: grpc.ServicerContext, method: str, work: Callable[[], RespT]
    ) -> RespT:
        try:
            return work()
        except DataServiceError as err:
            LOGGER.info("%s 拒绝：%s（%s）", method, err.detail, err.code.name)
            _abort(context, err.code, err.detail)
        except SQLAlchemyError as exc:
            LOGGER.exception("%s 数据库失败", method)
            _abort(context, grpc.StatusCode.INTERNAL, f"数据库错误：{exc}")
        except Exception as exc:  # noqa: BLE001 - 兜底，绝不把未捕获异常变成 UNKNOWN
            LOGGER.exception("%s 未预期失败", method)
            _abort(context, grpc.StatusCode.INTERNAL, f"服务内部错误：{type(exc).__name__}")

    # ------------------------------------------------------------ RPC

    def AuthorizePlayer(
        self, request: control_pb2.AuthorizePlayerRequest, context: grpc.ServicerContext
    ) -> control_pb2.AuthorizePlayerResponse:
        return self._handle(context, "AuthorizePlayer", lambda: self._authorize(request))

    def ReportProxyEvent(
        self, request: control_pb2.ReportProxyEventRequest, context: grpc.ServicerContext
    ) -> control_pb2.ReportProxyEventResponse:
        return self._handle(context, "ReportProxyEvent", lambda: self._report(request))

    def ListOnlinePlayers(
        self, request: control_pb2.ListOnlinePlayersRequest, context: grpc.ServicerContext
    ) -> control_pb2.ListOnlinePlayersResponse:
        return self._handle(context, "ListOnlinePlayers", lambda: self._list_online(request))

    def GetPlayerPlaytime(
        self, request: control_pb2.GetPlayerPlaytimeRequest, context: grpc.ServicerContext
    ) -> control_pb2.GetPlayerPlaytimeResponse:
        return self._handle(context, "GetPlayerPlaytime", lambda: self._playtime(request))

    def GetProxyStats(
        self, request: control_pb2.GetProxyStatsRequest, context: grpc.ServicerContext
    ) -> control_pb2.GetProxyStatsResponse:
        return self._handle(context, "GetProxyStats", lambda: self._stats(request))

    def ResolvePlayer(
        self, request: control_pb2.ResolvePlayerRequest, context: grpc.ServicerContext
    ) -> control_pb2.ResolvePlayerResponse:
        return self._handle(context, "ResolvePlayer", lambda: self._resolve(request))

    def BindPlayerIdentity(
        self, request: control_pb2.BindPlayerIdentityRequest, context: grpc.ServicerContext
    ) -> control_pb2.BindPlayerIdentityResponse:
        return self._handle(context, "BindPlayerIdentity", lambda: self._bind(request))

    def SetAccessRule(
        self, request: control_pb2.SetAccessRuleRequest, context: grpc.ServicerContext
    ) -> control_pb2.SetAccessRuleResponse:
        return self._handle(context, "SetAccessRule", lambda: self._set_rule(request))

    def ListAccessRules(
        self, request: control_pb2.ListAccessRulesRequest, context: grpc.ServicerContext
    ) -> control_pb2.ListAccessRulesResponse:
        return self._handle(context, "ListAccessRules", lambda: self._list_rules(request))

    def DeleteAccessRule(
        self, request: control_pb2.DeleteAccessRuleRequest, context: grpc.ServicerContext
    ) -> control_pb2.DeleteAccessRuleResponse:
        return self._handle(context, "DeleteAccessRule", lambda: self._delete_rule(request))

    def SetAccessPolicy(
        self, request: control_pb2.SetAccessPolicyRequest, context: grpc.ServicerContext
    ) -> control_pb2.SetAccessPolicyResponse:
        return self._handle(context, "SetAccessPolicy", lambda: self._set_policy(request))

    def ListAccessPolicies(
        self, request: control_pb2.ListAccessPoliciesRequest, context: grpc.ServicerContext
    ) -> control_pb2.ListAccessPoliciesResponse:
        return self._handle(context, "ListAccessPolicies", lambda: self._list_policies())

    def BeginDeviceLogin(
        self, request: control_pb2.BeginDeviceLoginRequest, context: grpc.ServicerContext
    ) -> control_pb2.BeginDeviceLoginResponse:
        return self._handle(context, "BeginDeviceLogin", lambda: self._begin_device_login(request))

    def GetDeviceLoginStatus(
        self, request: control_pb2.GetDeviceLoginStatusRequest, context: grpc.ServicerContext
    ) -> control_pb2.GetDeviceLoginStatusResponse:
        return self._handle(context, "GetDeviceLoginStatus", lambda: self._device_status(request))

    def ApproveDeviceLogin(
        self, request: control_pb2.ApproveDeviceLoginRequest, context: grpc.ServicerContext
    ) -> control_pb2.ApproveDeviceLoginResponse:
        return self._handle(context, "ApproveDeviceLogin", lambda: self._approve_device(request))

    def GetAccountLink(
        self, request: control_pb2.GetAccountLinkRequest, context: grpc.ServicerContext
    ) -> control_pb2.GetAccountLinkResponse:
        return self._handle(context, "GetAccountLink", lambda: self._get_account_link(request))

    def BindAccountLink(
        self, request: control_pb2.BindAccountLinkRequest, context: grpc.ServicerContext
    ) -> control_pb2.BindAccountLinkResponse:
        return self._handle(context, "BindAccountLink", lambda: self._bind_account_link(request))

    def DeleteAccountLink(
        self, request: control_pb2.DeleteAccountLinkRequest, context: grpc.ServicerContext
    ) -> control_pb2.DeleteAccountLinkResponse:
        return self._handle(context, "DeleteAccountLink", lambda: self._delete_account_link(request))

    # ------------------------------------------------------------ 实现

    def _authorize(self, request: control_pb2.AuthorizePlayerRequest) -> control_pb2.AuthorizePlayerResponse:
        player_uuid = validation.player_uuid(request.player_uuid)
        username = validation.require_text(request.username, "username", max_len=validation.MAX_USERNAME_LEN)
        server_id = validation.optional_identifier(request.server_id, "server_id")
        started = time.monotonic()
        with self._db.read() as session:
            decision = authorize.decide(
                session,
                self._settings,
                self._casdoor,
                player_uuid=player_uuid,
                username=username,
                scope=server_id,
                now=now_ms(),
            )
        AUTHORIZE_LATENCY.observe(time.monotonic() - started)
        AUTHORIZE_TOTAL.labels(decision="allow" if decision.allowed else "deny", reason=decision.reason).inc()
        return control_pb2.AuthorizePlayerResponse(
            allowed=decision.allowed,
            reason=_REASONS[decision.reason],
            message=decision.message,
            roles=list(decision.roles),
            casdoor_user_id=decision.casdoor_user_id,
            cache_ttl_seconds=decision.cache_ttl_seconds,
        )

    def _report(self, request: control_pb2.ReportProxyEventRequest) -> control_pb2.ReportProxyEventResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        kind = _enum_name(int(request.kind), _KINDS, "kind")
        session_id = validation.optional_identifier(request.session_id, "session_id")
        player_uuid = validation.uuid_or_empty(request.player_uuid, "player_uuid")
        username = validation.require_text(
            request.username, "username", max_len=validation.MAX_USERNAME_LEN, allow_empty=True
        )
        server_id = validation.optional_identifier(request.server_id, "server_id")
        from_server_id = validation.optional_identifier(request.from_server_id, "from_server_id")
        proxy_id = validation.optional_identifier(request.proxy_id, "proxy_id")
        end_reason = validation.require_text(request.end_reason, "end_reason", max_len=64, allow_empty=True)
        deny_reason = validation.require_text(
            request.deny_reason, "deny_reason", max_len=64, allow_empty=True
        )
        if kind == "LOGIN_DENIED":
            if not deny_reason:
                raise invalid_argument("LOGIN_DENIED 必须带 deny_reason")
        else:
            if not session_id:
                raise invalid_argument(f"{kind} 必须带 session_id")
            if not player_uuid:
                raise invalid_argument(f"{kind} 必须带 player_uuid")
            if not server_id:
                raise invalid_argument(f"{kind} 必须带 server_id")
            if kind == "SERVER_SWITCHED" and not from_server_id:
                raise invalid_argument("SERVER_SWITCHED 必须带 from_server_id")

        now = now_ms()
        occurred_at = _occurred(validation.epoch_ms(request.occurred_at, "occurred_at"), now)

        # 心跳不写事件、也不占幂等键：100 人在线 = 1.7 次/秒的 UPDATE，
        # 而不是每分钟 100 行幂等记录。
        if kind == "SESSION_HEARTBEAT":
            with self._db.write() as session:
                success = repo.proxy.heartbeat(session, session_id, occurred_at)
            return control_pb2.ReportProxyEventResponse(success=success, server_time=_ts(now))

        payload: dict[str, object] = {
            "kind": kind,
            "session_id": session_id,
            "player_uuid": player_uuid,
            "server_id": server_id,
            "from_server_id": from_server_id,
            # 用客户端原值做哈希：缺省时服务端补 now 会让同一意图的重试变成"不同载荷"。
            "occurred_at": _ms(request.occurred_at),
        }
        with self._db.write() as session:
            cached = repo.claim_idempotency(
                session,
                request_id=request_id,
                method="ReportProxyEvent",
                request_hash=_hash(payload),
                created_at=now,
            )
            if cached is not None:
                return _parse_cached(cached, control_pb2.ReportProxyEventResponse())

            success = True
            if kind == "SESSION_STARTED":
                repo.proxy.start_session(
                    session,
                    session_id=session_id,
                    player_uuid=player_uuid,
                    username=username,
                    proxy_id=proxy_id,
                    server_id=server_id,
                    client_version=validation.require_text(
                        request.client_version, "client_version", max_len=64, allow_empty=True
                    ),
                    protocol_version=int(request.protocol_version),
                    now=occurred_at,
                )
            elif kind == "SERVER_SWITCHED":
                success = repo.proxy.switch_server(session, session_id, server_id, occurred_at)
            elif kind == "SESSION_ENDED":
                success = repo.proxy.end_session(session, session_id, occurred_at, end_reason or "unknown")

            repo.proxy.insert_proxy_event(
                session,
                request_id=request_id,
                kind=kind,
                session_id=session_id,
                player_uuid=player_uuid,
                username=username,
                server_id=server_id,
                from_server_id=from_server_id,
                occurred_at=occurred_at,
                received_at=now,
                end_reason=end_reason,
                deny_reason=deny_reason,
            )
            REPORTS_TOTAL.labels(kind=kind).inc()
            response = control_pb2.ReportProxyEventResponse(success=success, server_time=_ts(now))
            repo.store_idempotency_response(
                session,
                request_id,
                json_format.MessageToJson(response, sort_keys=True, indent=None),
            )
        return response

    def _list_online(
        self, request: control_pb2.ListOnlinePlayersRequest
    ) -> control_pb2.ListOnlinePlayersResponse:
        server_id = validation.optional_identifier(request.server_id, "server_id")
        limit = int(request.limit) or DEFAULT_ONLINE_LIMIT
        if limit > MAX_ONLINE_LIMIT:
            raise invalid_argument(f"limit 上限 {MAX_ONLINE_LIMIT}，实际 {limit}")
        cutoff = now_ms() - self._settings.heartbeat_ttl_s * 1000
        with self._db.read() as session:
            rows = repo.proxy.list_online(session, cutoff=cutoff, server_id=server_id, limit=limit)
            total = repo.proxy.count_online(session, cutoff=cutoff, server_id=server_id)
        if not server_id:
            SESSIONS_ONLINE.set(total)
        return control_pb2.ListOnlinePlayersResponse(
            players=[
                control_pb2.OnlinePlayer(
                    player_uuid=str(row["player_uuid"]),
                    username=str(row["username"]),
                    server_id=str(row["server_id"]),
                    proxy_id=str(row["proxy_id"]),
                    session_id=str(row["session_id"]),
                    started_at=_ts(int(row["started_at"])),
                    last_seen_at=_ts(int(row["last_seen_at"])),
                )
                for row in rows
            ],
            total=total,
        )

    def _playtime(
        self, request: control_pb2.GetPlayerPlaytimeRequest
    ) -> control_pb2.GetPlayerPlaytimeResponse:
        from_ms = _ms(request.from_time)
        to_ms = _ms(request.to_time)
        with self._db.read() as session:
            identity = self._resolve_identity(session, request)
            if identity is None:
                return control_pb2.GetPlayerPlaytimeResponse(found=False)
            player_uuid = str(identity["player_uuid"])
            rows = repo.proxy.sessions_between(
                session, server_id="", player_uuid=player_uuid, from_ms=from_ms, to_ms=to_ms
            )
        total = 0
        by_server: dict[str, list[int]] = {}
        last_seen = 0
        for row in rows:
            seconds = _clip_seconds(row, from_ms, to_ms)
            total += seconds
            bucket = by_server.setdefault(str(row["server_id"]), [0, 0])
            bucket[0] += seconds
            bucket[1] += 1
            seen = int(row["ended_at"] if row["ended_at"] is not None else row["last_seen_at"])
            last_seen = max(last_seen, seen)
        return control_pb2.GetPlayerPlaytimeResponse(
            found=True,
            player_uuid=player_uuid,
            username=str(identity["username"]),
            total_seconds=total,
            sessions=len(rows),
            servers=[
                control_pb2.ServerPlaytime(server_id=name, seconds=value[0], sessions=value[1])
                for name, value in sorted(by_server.items())
            ],
            last_seen_at=_ts(last_seen) if last_seen else Timestamp(),
        )

    def _stats(self, request: control_pb2.GetProxyStatsRequest) -> control_pb2.GetProxyStatsResponse:
        server_id = validation.optional_identifier(request.server_id, "server_id")
        from_ms = _ms(request.from_time)
        to_ms = _ms(request.to_time)
        with self._db.read() as session:
            rows = repo.proxy.sessions_between(session, server_id=server_id, from_ms=from_ms, to_ms=to_ms)
            denies = repo.proxy.deny_stats(session, server_id=server_id, from_ms=from_ms, to_ms=to_ms)
        unique: set[str] = set()
        total_seconds = 0
        players_by_server: dict[str, set[str]] = {}
        sessions_by_server: dict[str, int] = {}
        seconds_by_server: dict[str, int] = {}
        buckets: dict[str, dict[int, int]] = {}
        for row in rows:
            uuid = str(row["player_uuid"])
            unique.add(uuid)
            seconds = _clip_seconds(row, from_ms, to_ms)
            total_seconds += seconds
            name = str(row["server_id"])
            players_by_server.setdefault(name, set()).add(uuid)
            sessions_by_server[name] = sessions_by_server.get(name, 0) + 1
            seconds_by_server[name] = seconds_by_server.get(name, 0) + seconds

            start = int(row["started_at"])
            end = int(row["ended_at"] if row["ended_at"] is not None else row["last_seen_at"])
            start = max(start, from_ms) if from_ms > 0 else start
            end = min(end, to_ms) if to_ms > 0 else end
            if end > start:
                series = buckets.setdefault(name, {})
                first = start // PEAK_BUCKET_MS
                last = end // PEAK_BUCKET_MS
                series[first] = series.get(first, 0) + 1
                series[last + 1] = series.get(last + 1, 0) - 1

        def peak(series: dict[int, int]) -> int:
            current = 0
            maximum = 0
            for key in sorted(series):
                current += series[key]
                maximum = max(maximum, current)
            return maximum

        login_failures = sum(int(row["count"]) for row in denies)
        return control_pb2.GetProxyStatsResponse(
            unique_players=len(unique),
            sessions=len(rows),
            total_seconds=total_seconds,
            login_failures=login_failures,
            servers=[
                control_pb2.ServerStats(
                    server_id=name,
                    unique_players=len(players_by_server[name]),
                    sessions=sessions_by_server[name],
                    seconds=seconds_by_server[name],
                    peak_online=peak(buckets.get(name, {})),
                )
                for name in sorted(players_by_server)
            ],
            denies=[
                control_pb2.DenyStats(reason=str(row["deny_reason"]), count=int(row["count"]))
                for row in denies
            ],
        )

    def _resolve_identity(
        self,
        session: Session,
        request: control_pb2.ResolvePlayerRequest | control_pb2.GetPlayerPlaytimeRequest,
    ) -> RowMapping | None:
        kind = request.WhichOneof("subject")
        if kind is None:
            raise invalid_argument("必须提供 player_uuid / username / casdoor_user_id 之一")
        if kind == "player_uuid":
            return repo.identities.get_by_uuid(session, validation.player_uuid(request.player_uuid))
        if kind == "username":
            username = validation.require_text(
                request.username, "username", max_len=validation.MAX_USERNAME_LEN
            )
            return repo.identities.get_by_username(session, username)
        casdoor_user_id = validation.require_text(request.casdoor_user_id, "casdoor_user_id", max_len=64)
        return repo.identities.get_by_casdoor(session, casdoor_user_id)

    def _resolve(self, request: control_pb2.ResolvePlayerRequest) -> control_pb2.ResolvePlayerResponse:
        with self._db.read() as session:
            row = self._resolve_identity(session, request)
        if row is None:
            return control_pb2.ResolvePlayerResponse(found=False)
        return control_pb2.ResolvePlayerResponse(
            found=True,
            player_uuid=str(row["player_uuid"]),
            username=str(row["username"]),
            casdoor_user_id=str(row["casdoor_user_id"]),
            source=str(row["source"]),
            linked_at=_ts(int(row["linked_at"])),
        )

    def _bind(self, request: control_pb2.BindPlayerIdentityRequest) -> control_pb2.BindPlayerIdentityResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        player_uuid = validation.player_uuid(request.player_uuid)
        username = validation.require_text(request.username, "username", max_len=validation.MAX_USERNAME_LEN)
        casdoor_user_id = validation.require_text(request.casdoor_user_id, "casdoor_user_id", max_len=64)
        source = _enum_name(int(request.source), _SOURCES, "source")
        actor = validation.require_text(request.actor, "actor", max_len=64, allow_empty=True) or "system"
        now = now_ms()
        payload = {
            "player_uuid": player_uuid,
            "username": username,
            "casdoor_user_id": casdoor_user_id,
            "source": source,
            "overwrite": bool(request.overwrite),
        }
        with self._db.write() as session:
            cached = repo.claim_idempotency(
                session,
                request_id=request_id,
                method="BindPlayerIdentity",
                request_hash=_hash(payload),
                created_at=now,
            )
            if cached is not None:
                return _parse_cached(cached, control_pb2.BindPlayerIdentityResponse())
            before = repo.identities.get_by_uuid(session, player_uuid)
            row, created = repo.identities.upsert(
                session,
                player_uuid=player_uuid,
                username=username,
                casdoor_user_id=casdoor_user_id,
                source=source,
                now=now,
                overwrite=bool(request.overwrite),
            )
            repo.audit(
                session,
                actor=actor,
                action="bind_identity",
                target=player_uuid,
                request_id=request_id,
                before_json=None
                if before is None
                else _dumps(
                    {
                        "username": str(before["username"]),
                        "casdoor_user_id": str(before["casdoor_user_id"]),
                    }
                ),
                after_json=_dumps({"username": username, "casdoor_user_id": casdoor_user_id}),
                created_at=now,
            )
            response = control_pb2.BindPlayerIdentityResponse(
                success=True,
                created=created,
                player_uuid=str(row["player_uuid"]),
                casdoor_user_id=str(row["casdoor_user_id"]),
            )
            repo.store_idempotency_response(
                session, request_id, json_format.MessageToJson(response, sort_keys=True, indent=None)
            )
        return response

    def _set_rule(self, request: control_pb2.SetAccessRuleRequest) -> control_pb2.SetAccessRuleResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        subject_type = _enum_name(int(request.subject_type), _SUBJECT_TYPES, "subject_type")
        subject = validation.require_text(request.subject, "subject", max_len=128)
        effect = _enum_name(int(request.effect), _EFFECTS, "effect")
        scope = validation.optional_identifier(request.scope, "scope")
        expires_at = _ms(request.expires_at) or None
        reason = validation.require_text(request.reason, "reason", max_len=256, allow_empty=True)
        actor = validation.require_text(request.actor, "actor", max_len=64, allow_empty=True) or "system"
        now = now_ms()
        payload: dict[str, object] = {
            "subject_type": subject_type,
            "subject": subject,
            "effect": effect,
            "scope": scope,
            "expires_at": expires_at,
        }
        with self._db.write() as session:
            cached = repo.claim_idempotency(
                session,
                request_id=request_id,
                method="SetAccessRule",
                request_hash=_hash(payload),
                created_at=now,
            )
            if cached is not None:
                return _parse_cached(cached, control_pb2.SetAccessRuleResponse())
            row = repo.access.upsert_rule(
                session,
                subject_type=subject_type,
                subject=subject,
                effect=effect,
                scope=scope,
                expires_at=expires_at,
                reason=reason,
                actor=actor,
                now=now,
            )
            repo.audit(
                session,
                actor=actor,
                action="set_access_rule",
                target=f"{subject_type}:{subject}@{scope or '*'}",
                request_id=request_id,
                before_json=None,
                after_json=_dumps(payload),
                created_at=now,
            )
            response = control_pb2.SetAccessRuleResponse(rule=_rule_message(row))
            repo.store_idempotency_response(
                session, request_id, json_format.MessageToJson(response, sort_keys=True, indent=None)
            )
        return response

    def _list_rules(self, request: control_pb2.ListAccessRulesRequest) -> control_pb2.ListAccessRulesResponse:
        subject_type = (
            None
            if int(request.subject_type) == 0
            else _enum_name(int(request.subject_type), _SUBJECT_TYPES, "subject_type")
        )
        subject = validation.require_text(request.subject, "subject", max_len=128, allow_empty=True)
        scope = validation.optional_identifier(request.scope, "scope")
        with self._db.read() as session:
            rows = repo.access.list_rules(
                session,
                subject_type=subject_type,
                subject=subject,
                scope=scope,
                include_expired=bool(request.include_expired),
                now=now_ms(),
            )
        return control_pb2.ListAccessRulesResponse(rules=[_rule_message(row) for row in rows])

    def _delete_rule(
        self, request: control_pb2.DeleteAccessRuleRequest
    ) -> control_pb2.DeleteAccessRuleResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        rule_id = int(request.id)
        if rule_id <= 0:
            raise invalid_argument(f"rule id 必须为正：{rule_id}")
        now = now_ms()
        with self._db.write() as session:
            cached = repo.claim_idempotency(
                session,
                request_id=request_id,
                method="DeleteAccessRule",
                request_hash=_hash({"id": rule_id}),
                created_at=now,
            )
            if cached is not None:
                return _parse_cached(cached, control_pb2.DeleteAccessRuleResponse())
            removed = repo.access.delete_rule(session, rule_id)
            if not removed:
                raise not_found(f"规则不存在：{rule_id}")
            repo.audit(
                session,
                actor="system",
                action="delete_access_rule",
                target=str(rule_id),
                request_id=request_id,
                before_json=_dumps({"id": rule_id}),
                after_json=None,
                created_at=now,
            )
            response = control_pb2.DeleteAccessRuleResponse(success=True)
            repo.store_idempotency_response(
                session, request_id, json_format.MessageToJson(response, sort_keys=True, indent=None)
            )
        return response

    def _set_policy(self, request: control_pb2.SetAccessPolicyRequest) -> control_pb2.SetAccessPolicyResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        scope = validation.optional_identifier(request.scope, "scope")
        mode = _enum_name(int(request.mode), _MODES, "mode")
        actor = validation.require_text(request.actor, "actor", max_len=64, allow_empty=True) or "system"
        now = now_ms()
        payload: dict[str, object] = {"scope": scope, "mode": mode}
        with self._db.write() as session:
            cached = repo.claim_idempotency(
                session,
                request_id=request_id,
                method="SetAccessPolicy",
                request_hash=_hash(payload),
                created_at=now,
            )
            if cached is not None:
                return _parse_cached(cached, control_pb2.SetAccessPolicyResponse())
            repo.access.set_policy(session, scope=scope, mode=mode.lower(), now=now)
            repo.audit(
                session,
                actor=actor,
                action="set_access_policy",
                target=scope or "*",
                request_id=request_id,
                before_json=None,
                after_json=_dumps(payload),
                created_at=now,
            )
            row = repo.access.get_policy_row(session, scope)
            if row is None:  # pragma: no cover - set_policy 刚写过
                raise not_found(f"策略写入后读不到：{scope or '*'}")
            response = control_pb2.SetAccessPolicyResponse(policy=_policy_message(row))
            repo.store_idempotency_response(
                session, request_id, json_format.MessageToJson(response, sort_keys=True, indent=None)
            )
        return response

    def _begin_device_login(
        self, request: control_pb2.BeginDeviceLoginRequest
    ) -> control_pb2.BeginDeviceLoginResponse:
        purpose = (request.purpose or "GAME").strip().upper()
        if purpose not in ("GAME", "LINK"):
            raise invalid_argument(f"purpose 只能是 GAME / LINK：{request.purpose}")
        player_uuid = (
            validation.player_uuid(request.player_uuid)
            if purpose == "GAME"
            else validation.uuid_or_empty(request.player_uuid, "player_uuid")
        )
        username = validation.require_text(request.username, "username", max_len=validation.MAX_USERNAME_LEN)
        proxy_id = validation.optional_identifier(request.proxy_id, "proxy_id")
        expected_casdoor_user_id = validation.require_text(
            request.expected_casdoor_user_id,
            "expected_casdoor_user_id",
            max_len=64,
            allow_empty=True,
        )
        # 允许直接填用户名：Casdoor 里同一组织下 owner/name 才唯一，这里补上默认组织。
        if expected_casdoor_user_id and "/" not in expected_casdoor_user_id:
            expected_casdoor_user_id = f"{self._settings.casdoor_organization}/{expected_casdoor_user_id}"
        auth = self._casdoor.start_device_authorization()
        now = now_ms()
        login_id = str(uuid.uuid4())
        with self._db.write() as session:
            repo.device_logins.create(
                session,
                login_id=login_id,
                device_code=auth.device_code,
                user_code=auth.user_code,
                player_uuid=player_uuid,
                username=username,
                proxy_id=proxy_id,
                purpose=purpose,
                interval_s=auth.interval,
                created_at=now,
                expires_at=now + auth.expires_in * 1000,
                expected_casdoor_user_id=expected_casdoor_user_id,
            )
        return control_pb2.BeginDeviceLoginResponse(
            login_id=login_id,
            user_code=auth.user_code,
            verification_uri=auth.verification_uri,
            expires_in=auth.expires_in,
            interval=auth.interval,
        )

    def _device_status(
        self, request: control_pb2.GetDeviceLoginStatusRequest
    ) -> control_pb2.GetDeviceLoginStatusResponse:
        login_id = validation.identifier(request.login_id, "login_id", max_len=validation.MAX_REQUEST_ID_LEN)
        with self._db.read() as session:
            row = repo.device_logins.get(session, login_id)
        if row is None:
            raise not_found(f"登录会话不存在：{login_id}")
        status = str(row["status"])
        message = str(row["message"])
        if status == repo.device_logins.PENDING and int(row["expires_at"]) <= now_ms():
            with self._db.write() as session:
                repo.device_logins.mark(session, login_id, repo.device_logins.EXPIRED, message="登录码已过期")
            status = repo.device_logins.EXPIRED
            message = "登录码已过期"
        return control_pb2.GetDeviceLoginStatusResponse(
            status=_DEVICE_STATUS[status],
            player_uuid=str(row["player_uuid"]),
            casdoor_user_id=str(row["casdoor_user_id"]),
            message=message,
        )

    def _approve_device(
        self, request: control_pb2.ApproveDeviceLoginRequest
    ) -> control_pb2.ApproveDeviceLoginResponse:
        user_code = validation.identifier(request.user_code, "user_code", max_len=32)
        casdoor_user_id = validation.require_text(request.casdoor_user_id, "casdoor_user_id", max_len=128)
        actor = validation.require_text(request.actor, "actor", max_len=64, allow_empty=True) or "bot"
        player_uuid, username = self.approve_device_login_by_code(user_code, casdoor_user_id, actor)
        return control_pb2.ApproveDeviceLoginResponse(
            success=True, player_uuid=player_uuid, username=username
        )

    def approve_device_login_by_code(
        self, user_code: str, casdoor_user_id: str, actor: str
    ) -> tuple[str, str]:
        """可信调用方（bot）用已确认的 Casdoor 身份批准短码。"""
        now = now_ms()
        with self._db.write() as session:
            row = repo.device_logins.get_pending_by_user_code(session, user_code, now=now)
            if row is None:
                raise not_found(f"登录码不存在或已过期：{user_code}")
            expected = str(row["expected_casdoor_user_id"])
            if expected and casdoor_user_id != expected:
                repo.device_logins.mark(
                    session,
                    str(row["id"]),
                    repo.device_logins.DENIED,
                    message=f"登录的账号是 {casdoor_user_id}，与指定的 CCNR 账号不一致",
                    now=now,
                )
                raise invalid_argument(f"登录的账号是 {casdoor_user_id}，与指定的 CCNR 账号不一致")
            player_uuid = str(row["player_uuid"])
            username = str(row["username"])
            try:
                repo.identities.upsert(
                    session,
                    player_uuid=player_uuid,
                    username=username,
                    casdoor_user_id=casdoor_user_id,
                    source="PASS",
                    now=now,
                    overwrite=False,
                )
            except DataServiceError as exc:
                repo.device_logins.mark(
                    session,
                    str(row["id"]),
                    repo.device_logins.DENIED,
                    message=exc.detail,
                )
                raise
            repo.device_logins.mark(
                session,
                str(row["id"]),
                repo.device_logins.APPROVED,
                casdoor_user_id=casdoor_user_id,
                now=now,
            )
            repo.audit(
                session,
                actor=actor,
                action="approve_device_login",
                target=user_code,
                request_id="",
                before_json=None,
                after_json=_dumps({"player_uuid": player_uuid, "casdoor_user_id": casdoor_user_id}),
                created_at=now,
            )
        LOGGER.info("device login 由 %s 批准：%s（%s）", actor, username, casdoor_user_id)
        return player_uuid, username

    def _get_account_link(
        self, request: control_pb2.GetAccountLinkRequest
    ) -> control_pb2.GetAccountLinkResponse:
        user_id = validation.require_text(request.user_id, "user_id", max_len=64)
        with self._db.read() as session:
            row = repo.account_links.get(session, user_id)
        if row is None:
            return control_pb2.GetAccountLinkResponse(found=False)
        return control_pb2.GetAccountLinkResponse(found=True, link=_account_link_message(row))

    def _bind_account_link(
        self, request: control_pb2.BindAccountLinkRequest
    ) -> control_pb2.BindAccountLinkResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        user_id = validation.require_text(request.user_id, "user_id", max_len=64)
        casdoor_user_id = validation.require_text(request.casdoor_user_id, "casdoor_user_id", max_len=64)
        source = validation.require_text(request.source, "source", max_len=16).upper()
        actor = validation.require_text(request.actor, "actor", max_len=64, allow_empty=True) or "system"
        now = now_ms()
        payload = {
            "user_id": user_id,
            "casdoor_user_id": casdoor_user_id,
            "source": source,
            "overwrite": bool(request.overwrite),
        }
        with self._db.write() as session:
            cached = repo.claim_idempotency(
                session,
                request_id=request_id,
                method="BindAccountLink",
                request_hash=_hash(payload),
                created_at=now,
            )
            if cached is not None:
                return _parse_cached(cached, control_pb2.BindAccountLinkResponse())
            before = repo.account_links.get(session, user_id)
            row, created = repo.account_links.upsert(
                session,
                user_id=user_id,
                casdoor_user_id=casdoor_user_id,
                source=source,
                now=now,
                overwrite=bool(request.overwrite),
            )
            repo.audit(
                session,
                actor=actor,
                action="bind_account_link",
                target=user_id,
                request_id=request_id,
                before_json=None
                if before is None
                else _dumps({"casdoor_user_id": str(before["casdoor_user_id"])}),
                after_json=_dumps({"casdoor_user_id": casdoor_user_id, "source": source}),
                created_at=now,
            )
            response = control_pb2.BindAccountLinkResponse(
                success=True, created=created, link=_account_link_message(row)
            )
            repo.store_idempotency_response(
                session, request_id, json_format.MessageToJson(response, sort_keys=True, indent=None)
            )
        return response

    def _delete_account_link(
        self, request: control_pb2.DeleteAccountLinkRequest
    ) -> control_pb2.DeleteAccountLinkResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        user_id = validation.require_text(request.user_id, "user_id", max_len=64)
        actor = validation.require_text(request.actor, "actor", max_len=64, allow_empty=True) or "system"
        now = now_ms()
        with self._db.write() as session:
            cached = repo.claim_idempotency(
                session,
                request_id=request_id,
                method="DeleteAccountLink",
                request_hash=_hash({"user_id": user_id}),
                created_at=now,
            )
            if cached is not None:
                return _parse_cached(cached, control_pb2.DeleteAccountLinkResponse())
            before = repo.account_links.get(session, user_id)
            removed = repo.account_links.remove(session, user_id)
            if removed:
                repo.audit(
                    session,
                    actor=actor,
                    action="delete_account_link",
                    target=user_id,
                    request_id=request_id,
                    before_json=_dumps({"casdoor_user_id": str(before["casdoor_user_id"])} if before else {}),
                    after_json=None,
                    created_at=now,
                )
            response = control_pb2.DeleteAccountLinkResponse(success=removed)
            repo.store_idempotency_response(
                session, request_id, json_format.MessageToJson(response, sort_keys=True, indent=None)
            )
        return response

    def _list_policies(self) -> control_pb2.ListAccessPoliciesResponse:
        with self._db.read() as session:
            rows = repo.access.list_policies(session)
        return control_pb2.ListAccessPoliciesResponse(policies=[_policy_message(row) for row in rows])
