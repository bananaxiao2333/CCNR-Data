# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""测试用请求构造器与断言工具。"""

from __future__ import annotations

import uuid

from google.protobuf.timestamp_pb2 import Timestamp

from moddata.v1 import moddata_pb2

SERVER_ID = "test-server"


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return f"req-{uuid.uuid4().hex}"


def at(epoch_ms: int) -> Timestamp:
    """把 epoch 毫秒转成 protobuf Timestamp。"""
    return Timestamp(seconds=epoch_ms // 1000, nanos=(epoch_ms % 1000) * 1000)


def apply_request(
    player_uuid: str,
    delta: int,
    *,
    request_id: str | None = None,
    server_id: str = SERVER_ID,
    reason: str = "manual:/rp xp add",
    username: str = "",
    level: int | None = None,
) -> moddata_pb2.ApplyExperienceRequest:
    request = moddata_pb2.ApplyExperienceRequest(
        request_id=request_id or new_request_id(),
        player_uuid=player_uuid,
        server_id=server_id,
        delta=delta,
        reason=reason,
        username=username,
    )
    if level is not None:
        request.level = level
    return request


def settlement_request(
    player_uuid: str,
    *,
    request_id: str | None = None,
    server_id: str = SERVER_ID,
    match_id: str = "",
    reason: str = "command",
    xp_before: int = 0,
    xp_after: int = 0,
    level_before: int = 0,
    level_after: int = 0,
    lines: list[tuple[str, str, int]] | None = None,
    username: str = "",
    settled_at: int | None = None,
) -> moddata_pb2.RecordSettlementRequest:
    """按模组 SettleSummary 的形状造请求：gain 恒等于 xp_after - xp_before。"""
    entries = lines if lines is not None else []
    request = moddata_pb2.RecordSettlementRequest(
        request_id=request_id or new_request_id(),
        server_id=server_id,
        player_uuid=player_uuid,
        match_id=match_id,
        reason=reason,
        xp_before=xp_before,
        xp_after=xp_after,
        level_before=level_before,
        level_after=level_after,
        gain=xp_after - xp_before,
        username=username,
    )
    for rule_id, title, value in entries:
        request.lines.add(rule_id=rule_id, title=title, value=value)
    if settled_at is not None:
        request.settled_at.CopyFrom(at(settled_at))
    return request


def event_request(
    kind: moddata_pb2.EventKind,
    *,
    request_id: str | None = None,
    server_id: str = SERVER_ID,
    match_id: str = "",
    phase_id: str = "",
    previous_phase_id: str = "",
    definition_id: str = "",
    actor_uuid: str = "",
    target_uuid: str = "",
    payload_json: str = "",
    occurred_at: int | None = None,
) -> moddata_pb2.RecordEventRequest:
    request = moddata_pb2.RecordEventRequest(
        request_id=request_id or new_request_id(),
        server_id=server_id,
        kind=kind,
        match_id=match_id,
        phase_id=phase_id,
        previous_phase_id=previous_phase_id,
        definition_id=definition_id,
        actor_uuid=actor_uuid,
        target_uuid=target_uuid,
        payload_json=payload_json,
    )
    if occurred_at is not None:
        request.occurred_at.CopyFrom(at(occurred_at))
    return request


def role_request(
    player_uuid: str,
    role: str,
    enabled: bool,
    *,
    request_id: str | None = None,
    server_id: str = SERVER_ID,
    source: str = "admin",
) -> moddata_pb2.SetRoleOverrideRequest:
    return moddata_pb2.SetRoleOverrideRequest(
        request_id=request_id or new_request_id(),
        player_uuid=player_uuid,
        server_id=server_id,
        role=role,
        enabled=enabled,
        source=source,
    )
