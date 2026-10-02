# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""gRPC 服务实现。

分层：本文件只做「校验 → 业务规则 → 调 repo 落库 → 组响应」，
SQL 全在 `repo`，连接与事务边界全在 `db`，字段校验全在 `validation`。

三条不变量（都有测试守着）：
  1. 幂等行与业务行**同事务**提交 —— 有幂等行就等于业务已生效。
  2. 每个写入 RPC 都落一条 `audit_log` 与一条 `change_log`（可观测、可对账）。
  3. 权威端给什么就存什么 —— 本服务不重算经验、不重算等级。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import Callable, Iterator
from typing import NoReturn, cast

import grpc
from google.protobuf import json_format
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp

from ccnr_data import repo, validation
from ccnr_data.clock import now_ms
from ccnr_data.config import DEFAULT_WATCH_POLL_MS
from ccnr_data.db import Database
from ccnr_data.errors import DataServiceError, invalid_argument, not_found, permission_denied
from moddata.v1 import moddata_pb2, moddata_pb2_grpc

__all__ = ["ModDataService"]

LOGGER = logging.getLogger(__name__)

ROLE_POLICY = moddata_pb2.RolePolicy
EVENT_KIND = moddata_pb2.EventKind

#: 角色策略的落库字面量（数据库里存文本，改 proto 枚举数值不会动到历史数据）。
_POLICY_TO_DB: dict[int, str] = {
    ROLE_POLICY.ROLE_POLICY_OPEN: "open",
    ROLE_POLICY.ROLE_POLICY_FROZEN: "frozen",
    ROLE_POLICY.ROLE_POLICY_FORCED_ON: "forced_on",
}
_DB_TO_POLICY: dict[str, int] = {name: value for value, name in _POLICY_TO_DB.items()}

DEFAULT_CONFIG_JSON = "{}"
DEFAULT_POLICY = ROLE_POLICY.ROLE_POLICY_OPEN

#: 结算行内标题 / rule id 的长度上限。
MAX_LINE_TEXT_LEN = 256


def _timestamp(ms: int) -> Timestamp:
    return Timestamp(seconds=ms // 1000, nanos=(ms % 1000) * 1000)


def _hash_payload(payload: dict[str, object]) -> str:
    """请求载荷指纹：键排序 + 紧凑分隔符，保证同一意图得到同一个指纹。"""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cache_response(conn: sqlite3.Connection, request_id: str, message: Message) -> None:
    repo.store_idempotency_response(
        conn, request_id, json_format.MessageToJson(message, sort_keys=True, indent=None)
    )


def _parse_cached[MsgT: Message](raw: str, out: MsgT) -> MsgT:
    # ignore_unknown_fields：新版本服务写下的缓存被旧版本读到时，不让多余字段炸掉重放。
    json_format.Parse(raw, out, ignore_unknown_fields=True)
    return out


def _abort(context: grpc.ServicerContext, code: grpc.StatusCode, detail: str) -> NoReturn:
    """`context.abort` 的本地封装。

    grpc 是无类型化依赖，它的 abort 在 mypy 眼里返回 Any，于是带 abort 的分支会被判成
    "可能落到函数末尾"。包一层并声明 NoReturn，让类型检查看到"这里不返回"。
    """
    context.abort(code, detail)
    raise AssertionError("context.abort 不应返回")  # pragma: no cover


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ModDataService(moddata_pb2_grpc.ModDataServiceServicer):
    """ModDataService 的同步实现（SQLite 驱动是阻塞的，线程池即并发模型）。"""

    def __init__(self, db: Database, *, watch_poll_ms: int = DEFAULT_WATCH_POLL_MS) -> None:
        self._db = db
        self._watch_poll_ms = watch_poll_ms

    # ------------------------------------------------------------ 错误映射

    def _handle[RespT: Message](
        self, context: grpc.ServicerContext, method: str, work: Callable[[], RespT]
    ) -> RespT:
        """把领域异常统一翻译成 gRPC 状态码。

        只有一个翻译点：否则同一个原因会在不同 RPC 上返回不同码，客户端没法写统一重试策略。
        """
        try:
            return work()
        except DataServiceError as err:
            LOGGER.info("%s 拒绝：%s（%s）", method, err.detail, err.code.name)
            _abort(context, err.code, err.detail)
        except sqlite3.Error as exc:
            LOGGER.exception("%s 数据库失败", method)
            _abort(context, grpc.StatusCode.INTERNAL, f"数据库错误：{exc}")
        except Exception as exc:  # noqa: BLE001 - 兜底：绝不让未捕获异常变成客户端看不懂的 UNKNOWN
            LOGGER.exception("%s 未预期失败", method)
            _abort(context, grpc.StatusCode.INTERNAL, f"服务内部错误：{type(exc).__name__}")

    # ------------------------------------------------------------ RPC

    def GetPlayer(
        self, request: moddata_pb2.GetPlayerRequest, context: grpc.ServicerContext
    ) -> moddata_pb2.GetPlayerResponse:
        return self._handle(context, "GetPlayer", lambda: self._get_player(request))

    def ApplyExperience(
        self, request: moddata_pb2.ApplyExperienceRequest, context: grpc.ServicerContext
    ) -> moddata_pb2.ApplyExperienceResponse:
        return self._handle(context, "ApplyExperience", lambda: self._apply_experience(request))

    def RecordSettlement(
        self, request: moddata_pb2.RecordSettlementRequest, context: grpc.ServicerContext
    ) -> moddata_pb2.RecordSettlementResponse:
        return self._handle(context, "RecordSettlement", lambda: self._record_settlement(request))

    def RecordEvent(
        self, request: moddata_pb2.RecordEventRequest, context: grpc.ServicerContext
    ) -> moddata_pb2.RecordEventResponse:
        return self._handle(context, "RecordEvent", lambda: self._record_event(request))

    def SetRoleOverride(
        self, request: moddata_pb2.SetRoleOverrideRequest, context: grpc.ServicerContext
    ) -> moddata_pb2.SetRoleOverrideResponse:
        return self._handle(context, "SetRoleOverride", lambda: self._set_role_override(request))

    def GetServerConfig(
        self, request: moddata_pb2.GetServerConfigRequest, context: grpc.ServicerContext
    ) -> moddata_pb2.GetServerConfigResponse:
        return self._handle(context, "GetServerConfig", lambda: self._get_server_config(request))

    def UpdateServerConfig(
        self, request: moddata_pb2.UpdateServerConfigRequest, context: grpc.ServicerContext
    ) -> moddata_pb2.UpdateServerConfigResponse:
        return self._handle(context, "UpdateServerConfig", lambda: self._update_server_config(request))

    def WatchChanges(
        self, request: moddata_pb2.WatchChangesRequest, context: grpc.ServicerContext
    ) -> Iterator[moddata_pb2.ChangeEvent]:
        try:
            yield from self._watch_changes(request, context)
        except DataServiceError as err:
            LOGGER.info("WatchChanges 中断：%s（%s）", err.detail, err.code.name)
            _abort(context, err.code, err.detail)
        except sqlite3.Error as exc:
            LOGGER.exception("WatchChanges 数据库失败")
            _abort(context, grpc.StatusCode.INTERNAL, f"数据库错误：{exc}")

    # ------------------------------------------------------------ 实现

    def _get_player(self, request: moddata_pb2.GetPlayerRequest) -> moddata_pb2.GetPlayerResponse:
        server_id = validation.identifier(request.server_id, "server_id")
        player_uuid = validation.player_uuid(request.player_uuid)

        conn = self._db.connection()
        row = repo.get_player(conn, player_uuid, server_id)
        if row is None:
            raise not_found(f"玩家档案不存在：{player_uuid} @ {server_id}")
        roles = repo.list_roles(conn, player_uuid, server_id)

        return moddata_pb2.GetPlayerResponse(
            player=moddata_pb2.PlayerData(
                player_uuid=str(row["player_uuid"]),
                server_id=str(row["server_id"]),
                username=str(row["username"]),
                experience=int(row["experience"]),
                level=int(row["level"]),
                roles=roles,
                version=int(row["version"]),
                updated_at=_timestamp(int(row["updated_at"])),
            )
        )

    def _apply_experience(
        self, request: moddata_pb2.ApplyExperienceRequest
    ) -> moddata_pb2.ApplyExperienceResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        server_id = validation.identifier(request.server_id, "server_id")
        player_uuid = validation.player_uuid(request.player_uuid)
        reason = (
            validation.require_text(
                request.reason, "reason", max_len=validation.MAX_REASON_LEN, allow_empty=True
            )
            or "unspecified"
        )
        username = validation.require_text(
            request.username, "username", max_len=validation.MAX_USERNAME_LEN, allow_empty=True
        )
        level = int(request.level) if request.HasField("level") else None
        if level is not None and level < 0:
            raise invalid_argument(f"level 不能为负：{level}")
        delta = int(request.delta)

        payload: dict[str, object] = {
            "player_uuid": player_uuid,
            "server_id": server_id,
            "delta": delta,
            "reason": reason,
            "level": level,
            "username": username,
        }

        with self._db.write() as conn:
            cached = repo.claim_idempotency(
                conn,
                request_id=request_id,
                method="ApplyExperience",
                request_hash=_hash_payload(payload),
                created_at=now_ms(),
            )
            if cached is not None:
                return _parse_cached(cached, moddata_pb2.ApplyExperienceResponse())

            row = repo.get_player(conn, player_uuid, server_id)
            stored_xp = int(row["experience"]) if row is not None else 0
            stored_level = int(row["level"]) if row is not None else 0
            # 与模组 UserService.addXp 同语义：结果钳制到 >= 0。
            new_xp = max(0, stored_xp + delta)
            new_level = level if level is not None else stored_level

            updated = repo.upsert_player(
                conn,
                player_uuid=player_uuid,
                server_id=server_id,
                username=username,
                experience=new_xp,
                level=new_level,
                updated_at=now_ms(),
            )
            version = int(updated["version"])
            response = moddata_pb2.ApplyExperienceResponse(
                success=True, experience=new_xp, level=new_level, version=version
            )
            self._record_write(
                conn,
                server_id=server_id,
                action="apply_experience",
                target=f"{player_uuid}@{server_id}",
                request_id=request_id,
                before={"experience": stored_xp, "level": stored_level},
                after={"experience": new_xp, "level": new_level, "reason": reason, "delta": delta},
                change_type="player.experience",
                change_player=player_uuid,
                change_version=version,
                change_payload={"experience": new_xp, "level": new_level, "delta": delta, "reason": reason},
            )
            _cache_response(conn, request_id, response)

        return response

    def _record_settlement(
        self, request: moddata_pb2.RecordSettlementRequest
    ) -> moddata_pb2.RecordSettlementResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        server_id = validation.identifier(request.server_id, "server_id")
        player_uuid = validation.player_uuid(request.player_uuid)
        match_id = validation.optional_identifier(
            request.match_id, "match_id", max_len=validation.MAX_MATCH_ID_LEN
        )
        reason = validation.require_text(request.reason, "reason", max_len=validation.MAX_REASON_LEN)
        username = validation.require_text(
            request.username, "username", max_len=validation.MAX_USERNAME_LEN, allow_empty=True
        )
        xp_before = int(request.xp_before)
        xp_after = int(request.xp_after)
        level_before = int(request.level_before)
        level_after = int(request.level_after)
        gain = int(request.gain)

        if xp_before < 0 or xp_after < 0:
            raise invalid_argument(f"经验不能为负：xp_before={xp_before}, xp_after={xp_after}")
        if level_before < 0 or level_after < 0:
            raise invalid_argument(f"等级不能为负：level_before={level_before}, level_after={level_after}")
        if gain != xp_after - xp_before:
            raise invalid_argument(
                f"gain 必须等于 xp_after - xp_before：gain={gain}, 差值={xp_after - xp_before}"
            )
        if len(request.lines) > validation.MAX_LINES:
            raise invalid_argument(f"明细条数上限 {validation.MAX_LINES}，实际 {len(request.lines)}")

        lines: list[tuple[str, str, int]] = []
        for index, line in enumerate(request.lines):
            rule_id = validation.require_text(
                line.rule_id, f"lines[{index}].rule_id", max_len=MAX_LINE_TEXT_LEN
            )
            title = validation.require_text(
                line.title, f"lines[{index}].title", max_len=MAX_LINE_TEXT_LEN, allow_empty=True
            )
            lines.append((rule_id, title, int(line.value)))

        lines_total = sum(value for _, _, value in lines)
        if lines and lines_total != gain:
            raise invalid_argument(
                f"明细合计 {lines_total} 与 gain {gain} 不一致；模组端 SettleSummary 保证二者相等"
            )
        if not lines and gain != 0:
            raise invalid_argument(f"没有明细时 gain 必须为 0，实际 {gain}")

        settled_at = validation.epoch_ms(request.settled_at, "settled_at")
        payload: dict[str, object] = {
            "player_uuid": player_uuid,
            "server_id": server_id,
            "match_id": match_id,
            "reason": reason,
            "xp_before": xp_before,
            "xp_after": xp_after,
            "level_before": level_before,
            "level_after": level_after,
            "gain": gain,
            "lines": lines,
        }

        with self._db.write() as conn:
            cached = repo.claim_idempotency(
                conn,
                request_id=request_id,
                method="RecordSettlement",
                request_hash=_hash_payload(payload),
                created_at=now_ms(),
            )
            if cached is not None:
                return _parse_cached(cached, moddata_pb2.RecordSettlementResponse())

            row = repo.get_player(conn, player_uuid, server_id)
            stored_xp_before = int(row["experience"]) if row is not None else 0
            diverged = stored_xp_before != xp_before

            settlement_id = repo.insert_settlement(
                conn,
                request_id=request_id,
                server_id=server_id,
                player_uuid=player_uuid,
                match_id=match_id,
                reason=reason,
                xp_before=xp_before,
                xp_after=xp_after,
                level_before=level_before,
                level_after=level_after,
                gain=gain,
                diverged=diverged,
                settled_at=settled_at,
                created_at=now_ms(),
            )
            repo.insert_settlement_lines(
                conn,
                settlement_id,
                [(index + 1, rule_id, title, value) for index, (rule_id, title, value) in enumerate(lines)],
            )
            updated = repo.upsert_player(
                conn,
                player_uuid=player_uuid,
                server_id=server_id,
                username=username,
                experience=xp_after,
                level=level_after,
                updated_at=settled_at,
            )
            version = int(updated["version"])
            response = moddata_pb2.RecordSettlementResponse(
                success=True,
                xp_after=xp_after,
                level_after=level_after,
                version=version,
                line_count=len(lines),
                xp_diverged=diverged,
                stored_xp_before=stored_xp_before,
            )
            if diverged:
                LOGGER.warning(
                    "结算前后端经验不一致：玩家=%s 服务器=%s 库内=%d 上报=%d（以权威端为准已覆盖）",
                    player_uuid,
                    server_id,
                    stored_xp_before,
                    xp_before,
                )
            self._record_write(
                conn,
                server_id=server_id,
                action="record_settlement",
                target=f"{player_uuid}@{server_id}",
                request_id=request_id,
                before={"experience": stored_xp_before},
                after={
                    "experience": xp_after,
                    "level": level_after,
                    "gain": gain,
                    "reason": reason,
                    "lines": len(lines),
                    "diverged": diverged,
                },
                change_type="player.settlement",
                change_player=player_uuid,
                change_version=version,
                change_payload={
                    "settlement_id": settlement_id,
                    "match_id": match_id,
                    "reason": reason,
                    "gain": gain,
                    "xp_after": xp_after,
                    "level_after": level_after,
                    "diverged": diverged,
                },
                occurred_at=settled_at,
            )
            _cache_response(conn, request_id, response)

        return response

    def _record_event(self, request: moddata_pb2.RecordEventRequest) -> moddata_pb2.RecordEventResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        server_id = validation.identifier(request.server_id, "server_id")
        kind = validation.event_kind(request.kind)
        match_id = validation.optional_identifier(
            request.match_id, "match_id", max_len=validation.MAX_MATCH_ID_LEN
        )
        phase_id = validation.optional_identifier(request.phase_id, "phase_id")
        previous_phase_id = validation.optional_identifier(request.previous_phase_id, "previous_phase_id")
        definition_id = validation.optional_identifier(request.definition_id, "definition_id")
        actor_uuid = validation.uuid_or_empty(request.actor_uuid, "actor_uuid")
        target_uuid = validation.uuid_or_empty(request.target_uuid, "target_uuid")
        payload_json = validation.json_object_text(request.payload_json, "payload_json")
        occurred_at = validation.epoch_ms(request.occurred_at, "occurred_at")
        # 幂等指纹里放**原始**时间戳：未提供记为 0。
        # 否则同一请求重放时，服务端各自补一次 now()，指纹不同 → 被误判成"同键不同载荷"。
        raw_occurred_at = (
            int(request.occurred_at.seconds) * 1000 + int(request.occurred_at.nanos) // 1_000_000
        )
        kind_name = EVENT_KIND.Name(kind)

        if kind == EVENT_KIND.EVENT_KIND_PHASE_ADVANCED and not phase_id:
            raise invalid_argument("EVENT_KIND_PHASE_ADVANCED 必须带 phase_id（推进到的目标阶段）")

        payload: dict[str, object] = {
            "server_id": server_id,
            "kind": kind_name,
            "match_id": match_id,
            "phase_id": phase_id,
            "previous_phase_id": previous_phase_id,
            "definition_id": definition_id,
            "actor_uuid": actor_uuid,
            "target_uuid": target_uuid,
            "payload_json": payload_json,
            "occurred_at": raw_occurred_at,
        }

        with self._db.write() as conn:
            cached = repo.claim_idempotency(
                conn,
                request_id=request_id,
                method="RecordEvent",
                request_hash=_hash_payload(payload),
                created_at=now_ms(),
            )
            if cached is not None:
                return _parse_cached(cached, moddata_pb2.RecordEventResponse())

            repo.insert_match_event(
                conn,
                request_id=request_id,
                server_id=server_id,
                kind=kind_name,
                match_id=match_id,
                phase_id=phase_id,
                previous_phase_id=previous_phase_id,
                definition_id=definition_id,
                actor_uuid=actor_uuid,
                target_uuid=target_uuid,
                payload_json=payload_json,
                occurred_at=occurred_at,
                created_at=now_ms(),
            )
            change_seq = repo.append_change(
                conn,
                change_type="match.event",
                server_id=server_id,
                player_uuid=target_uuid or actor_uuid,
                version=0,
                payload_json=_dumps(
                    {
                        "kind": kind_name,
                        "match_id": match_id,
                        "phase_id": phase_id,
                        "definition_id": definition_id,
                        "payload": json.loads(payload_json),
                    }
                ),
                occurred_at=occurred_at,
            )
            # 这里**刻意不写审计行**：match_events 本身就是那条不可变记录（谁/何时/何事/载荷全在），
            # 再落一条 audit_log 等于把事件流水翻倍，而事件正是本服务量最大的表。
            # audit_log 只服务于"状态变更的前后值"——经验、结算、角色、服务器策略。
            response = moddata_pb2.RecordEventResponse(success=True, seq=change_seq)
            _cache_response(conn, request_id, response)

        return response

    def _set_role_override(
        self, request: moddata_pb2.SetRoleOverrideRequest
    ) -> moddata_pb2.SetRoleOverrideResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        server_id = validation.identifier(request.server_id, "server_id")
        player_uuid = validation.player_uuid(request.player_uuid)
        role = validation.identifier(request.role, "role")
        enabled = bool(request.enabled)
        source = (
            validation.require_text(
                request.source, "source", max_len=validation.MAX_SOURCE_LEN, allow_empty=True
            )
            or "unspecified"
        )

        payload: dict[str, object] = {
            "player_uuid": player_uuid,
            "server_id": server_id,
            "role": role,
            "enabled": enabled,
            "source": source,
        }

        with self._db.write() as conn:
            cached = repo.claim_idempotency(
                conn,
                request_id=request_id,
                method="SetRoleOverride",
                request_hash=_hash_payload(payload),
                created_at=now_ms(),
            )
            if cached is not None:
                return _parse_cached(cached, moddata_pb2.SetRoleOverrideResponse())

            policy = self._role_policy(conn, server_id)
            if policy == ROLE_POLICY.ROLE_POLICY_FROZEN:
                raise permission_denied(f"服务器 {server_id} 的角色策略为 frozen，拒绝角色变更")
            if policy == ROLE_POLICY.ROLE_POLICY_FORCED_ON:
                enabled = True

            repo.upsert_role_override(
                conn,
                player_uuid=player_uuid,
                server_id=server_id,
                role=role,
                enabled=enabled,
                source=source,
                updated_at=now_ms(),
            )
            roles = repo.list_roles(conn, player_uuid, server_id)

            # 角色变更属于玩家档案聚合的一部分，同样推进 players.version，
            # 让 GetPlayer 的版本号能真实反映"这个聚合被写过几次"。
            row = repo.get_player(conn, player_uuid, server_id)
            updated = repo.upsert_player(
                conn,
                player_uuid=player_uuid,
                server_id=server_id,
                username="",
                experience=int(row["experience"]) if row is not None else 0,
                level=int(row["level"]) if row is not None else 0,
                updated_at=now_ms(),
            )
            version = int(updated["version"])
            response = moddata_pb2.SetRoleOverrideResponse(success=True, current_roles=roles, version=version)
            self._record_write(
                conn,
                server_id=server_id,
                action="set_role_override",
                target=f"{player_uuid}@{server_id}",
                request_id=request_id,
                before=None,
                after={"role": role, "enabled": enabled, "source": source, "roles": roles},
                change_type="role.override",
                change_player=player_uuid,
                change_version=version,
                change_payload={"role": role, "enabled": enabled, "source": source, "roles": roles},
            )
            _cache_response(conn, request_id, response)

        return response

    def _get_server_config(
        self, request: moddata_pb2.GetServerConfigRequest
    ) -> moddata_pb2.GetServerConfigResponse:
        server_id = validation.identifier(request.server_id, "server_id")
        row = repo.get_server_config(self._db.connection(), server_id)
        return self._config_response(server_id, row)

    def _update_server_config(
        self, request: moddata_pb2.UpdateServerConfigRequest
    ) -> moddata_pb2.UpdateServerConfigResponse:
        request_id = validation.identifier(
            request.request_id, "request_id", max_len=validation.MAX_REQUEST_ID_LEN
        )
        server_id = validation.identifier(request.server_id, "server_id")
        actor = (
            validation.require_text(
                request.actor, "actor", max_len=validation.MAX_SOURCE_LEN, allow_empty=True
            )
            or server_id
        )

        has_policy = request.HasField("role_policy")
        has_config = request.HasField("config_json")
        if not has_policy and not has_config:
            raise invalid_argument("role_policy 与 config_json 至少要改一项")

        policy_value = int(request.role_policy) if has_policy else None
        if policy_value is not None and policy_value not in _POLICY_TO_DB:
            raise invalid_argument(f"role_policy 不能是 ROLE_POLICY_UNSPECIFIED（{policy_value}）")
        config_json = validation.json_object_text(request.config_json, "config_json") if has_config else None

        payload: dict[str, object] = {
            "server_id": server_id,
            "role_policy": policy_value,
            "config_json": config_json,
            "actor": actor,
        }

        with self._db.write() as conn:
            cached = repo.claim_idempotency(
                conn,
                request_id=request_id,
                method="UpdateServerConfig",
                request_hash=_hash_payload(payload),
                created_at=now_ms(),
            )
            if cached is not None:
                return _parse_cached(cached, moddata_pb2.UpdateServerConfigResponse())

            current = repo.get_server_config(conn, server_id)
            current_policy = (
                str(current["role_policy"]) if current is not None else _POLICY_TO_DB[DEFAULT_POLICY]
            )
            current_config = str(current["config_json"]) if current is not None else DEFAULT_CONFIG_JSON
            new_policy = _POLICY_TO_DB[policy_value] if policy_value is not None else current_policy
            new_config = config_json if config_json is not None else current_config

            row = repo.upsert_server_config(
                conn,
                server_id=server_id,
                role_policy=new_policy,
                config_json=new_config,
                updated_at=now_ms(),
            )
            version = int(row["version"])
            response = moddata_pb2.UpdateServerConfigResponse(
                success=True, config=self._config_response(server_id, row)
            )
            self._record_write(
                conn,
                server_id=server_id,
                action="update_server_config",
                target=f"config@{server_id}",
                request_id=request_id,
                before={"role_policy": current_policy, "config_json": current_config},
                after={"role_policy": new_policy, "config_json": new_config, "actor": actor},
                change_type="server.config",
                change_player="",
                change_version=version,
                change_payload={"role_policy": new_policy, "config_json": json.loads(new_config)},
            )
            _cache_response(conn, request_id, response)

        return response

    def _watch_changes(
        self, request: moddata_pb2.WatchChangesRequest, context: grpc.ServicerContext
    ) -> Iterator[moddata_pb2.ChangeEvent]:
        server_id = validation.optional_identifier(
            request.server_id, "server_id", max_len=validation.MAX_ID_LEN
        )
        since_seq = int(request.since_seq)
        if since_seq < 0:
            raise invalid_argument(f"since_seq 不能为负：{since_seq}")

        conn = self._db.connection()
        oldest = repo.oldest_change_seq(conn)
        if since_seq > 0 and oldest > 0 and since_seq < oldest - 1:
            # 日志轮换已经把中间那段删了。不报错（订阅方仍能继续收），但必须让它知道有洞。
            LOGGER.warning(
                "订阅游标 %d 早于变更流最早保留的 %d：中间事件已被日志轮换清除，订阅方需要重新全量对账",
                since_seq,
                oldest,
            )
        cursor = since_seq
        # ponytail: 轮询式订阅，每个订阅常驻一个线程池槽位；
        # 订阅数接近 max_workers 时必须改用 SQLite 更新钩子或换 PostgreSQL 的 LISTEN/NOTIFY。
        while context.is_active():
            rows = repo.fetch_changes(conn, server_id=server_id, since_seq=cursor)
            if not rows:
                time.sleep(self._watch_poll_ms / 1000.0)
                continue
            for row in rows:
                cursor = int(row["seq"])
                yield moddata_pb2.ChangeEvent(
                    seq=cursor,
                    change_type=str(row["change_type"]),
                    server_id=str(row["server_id"]),
                    player_uuid=str(row["player_uuid"]),
                    version=int(row["version"]),
                    payload_json=str(row["payload_json"]),
                    occurred_at=_timestamp(int(row["occurred_at"])),
                )

    # ------------------------------------------------------------ 内部工具

    def _role_policy(self, conn: sqlite3.Connection, server_id: str) -> int:
        row = repo.get_server_config(conn, server_id)
        if row is None:
            return DEFAULT_POLICY
        name = str(row["role_policy"])
        if name not in _DB_TO_POLICY:
            raise invalid_argument(f"服务器 {server_id} 的角色策略无法识别：{name!r}")
        return _DB_TO_POLICY[name]

    def _config_response(
        self, server_id: str, row: sqlite3.Row | None
    ) -> moddata_pb2.GetServerConfigResponse:
        if row is None:
            # 无记录 = 从未被写过：返回默认策略，且不设置 updated_at（proto3 presence 表示"没写过"）。
            return moddata_pb2.GetServerConfigResponse(
                server_id=server_id,
                role_policy=DEFAULT_POLICY,
                config_json=DEFAULT_CONFIG_JSON,
                version=0,
            )
        name = str(row["role_policy"])
        if name not in _DB_TO_POLICY:
            raise invalid_argument(f"服务器 {server_id} 的角色策略无法识别：{name!r}")
        return moddata_pb2.GetServerConfigResponse(
            server_id=str(row["server_id"]),
            role_policy=cast("moddata_pb2.RolePolicy", _DB_TO_POLICY[name]),
            config_json=str(row["config_json"]),
            version=int(row["version"]),
            updated_at=_timestamp(int(row["updated_at"])),
        )

    def _record_write(
        self,
        conn: sqlite3.Connection,
        *,
        server_id: str,
        action: str,
        target: str,
        request_id: str,
        before: dict[str, object] | None,
        after: dict[str, object],
        change_type: str,
        change_player: str,
        change_version: int,
        change_payload: dict[str, object],
        occurred_at: int | None = None,
    ) -> None:
        """每次业务写入都落审计 + 变更流：前者给合规，后者给订阅方。

        两个时间戳语义不同，不能混用：
          * 审计 `created_at` = **本服务写入的时刻**（权威端补报的历史数据也要按"何时入账"记）。
          * 变更流 `occurred_at` = **业务发生的时刻**，订阅方要按它还原时间线。
        """
        repo.audit(
            conn,
            actor=server_id,
            action=action,
            target=target,
            request_id=request_id,
            before_json=None if before is None else _dumps(before),
            after_json=_dumps(after),
            created_at=now_ms(),
        )
        repo.append_change(
            conn,
            change_type=change_type,
            server_id=server_id,
            player_uuid=change_player,
            version=change_version,
            payload_json=_dumps(change_payload),
            occurred_at=occurred_at if occurred_at is not None else now_ms(),
        )
