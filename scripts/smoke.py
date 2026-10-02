#!/usr/bin/env python
# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""冒烟：对着一台**已经在跑**的服务做一轮真实往返。

和 `pytest` 的区别：这里连的是外部进程/远端，用来验收真实部署
（systemd / docker / K8s 起来的那一份），顺便确认健康检查与反射可用。

用法：
    uv run python scripts/smoke.py --target 127.0.0.1:8081
"""

from __future__ import annotations

import argparse
import sys
import uuid

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

from moddata.v1 import moddata_pb2, moddata_pb2_grpc

SERVER_ID = "smoke"
KIND = moddata_pb2.EventKind

PASS = "  [ok]  "
FAIL = "  [!!]  "


def rid() -> str:
    return f"smoke-{uuid.uuid4().hex}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="127.0.0.1:8081", help="gRPC 目标 host:port")
    parser.add_argument("--timeout", type=float, default=10.0, help="单次调用超时秒数")
    args = parser.parse_args()

    channel = grpc.insecure_channel(args.target)
    try:
        grpc.channel_ready_future(channel).result(timeout=args.timeout)
    except grpc.FutureTimeoutError:
        print(f"{FAIL}连不上 {args.target}", file=sys.stderr)
        return 1

    stub = moddata_pb2_grpc.ModDataServiceStub(channel)  # type: ignore[no-untyped-call]
    health = health_pb2_grpc.HealthStub(channel)  # type: ignore[no-untyped-call]
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"{PASS if ok else FAIL}{label}{'' if not detail else f'：{detail}'}")
        if not ok:
            failures += 1

    status = health.Check(health_pb2.HealthCheckRequest(), timeout=args.timeout).status
    check(
        "健康检查 SERVING",
        status == health_pb2.HealthCheckResponse.SERVING,
        health_pb2.HealthCheckResponse.ServingStatus.Name(status),
    )

    player = str(uuid.uuid4())
    apply_request = moddata_pb2.ApplyExperienceRequest(
        request_id=rid(),
        player_uuid=player,
        server_id=SERVER_ID,
        delta=50,
        reason="smoke",
        level=2,
        username="SmokeTester",
    )
    apply_response = stub.ApplyExperience(apply_request, timeout=args.timeout)
    check("经验写入", apply_response.experience == 50, f"experience={apply_response.experience}")

    # 同一个 request_id 再发一次：必须原样回放，不能变成 +100。
    replay = stub.ApplyExperience(apply_request, timeout=args.timeout)
    check(
        "幂等重放",
        replay.experience == 50 and replay.version == apply_response.version,
        f"experience={replay.experience}, version={replay.version}",
    )

    fetched = stub.GetPlayer(
        moddata_pb2.GetPlayerRequest(player_uuid=player, server_id=SERVER_ID), timeout=args.timeout
    ).player
    check(
        "读档一致",
        (fetched.experience, fetched.level, fetched.username) == (50, 2, "SmokeTester"),
        f"{fetched.experience} / {fetched.level} / {fetched.username}",
    )

    settle = stub.RecordSettlement(
        moddata_pb2.RecordSettlementRequest(
            request_id=rid(),
            server_id=SERVER_ID,
            player_uuid=player,
            match_id="smoke-match",
            reason="round_end",
            xp_before=50,
            xp_after=68,
            level_before=2,
            level_after=2,
            gain=18,
            lines=[
                moddata_pb2.SettlementLine(rule_id="duty_time", title="值班时长", value=12),
                moddata_pb2.SettlementLine(rule_id="character_kill", title="击杀敌方", value=6),
            ],
            username="SmokeTester",
        ),
        timeout=args.timeout,
    )
    check(
        "结算上报",
        settle.success and settle.line_count == 2 and not settle.xp_diverged,
        f"xp_after={settle.xp_after}, lines={settle.line_count}, diverged={settle.xp_diverged}",
    )

    event = stub.RecordEvent(
        moddata_pb2.RecordEventRequest(
            request_id=rid(),
            server_id=SERVER_ID,
            kind=KIND.EVENT_KIND_PHASE_ADVANCED,
            match_id="smoke-match",
            phase_id="phase_2",
            previous_phase_id="phase_1",
        ),
        timeout=args.timeout,
    )
    check("事件上报", event.success and event.seq > 0, f"seq={event.seq}")

    role = stub.SetRoleOverride(
        moddata_pb2.SetRoleOverrideRequest(
            request_id=rid(),
            player_uuid=player,
            server_id=SERVER_ID,
            role="medic",
            enabled=True,
            source="smoke",
        ),
        timeout=args.timeout,
    )
    check("角色覆盖", role.current_roles == ["medic"], f"roles={list(role.current_roles)}")

    config = stub.GetServerConfig(
        moddata_pb2.GetServerConfigRequest(server_id=SERVER_ID), timeout=args.timeout
    )
    check("服务器策略可读", config.role_policy == moddata_pb2.ROLE_POLICY_OPEN)

    stream = stub.WatchChanges(moddata_pb2.WatchChangesRequest(since_seq=event.seq - 1), timeout=5)
    try:
        first = next(iter(stream))
        check("变更流可用", first.seq >= event.seq, f"seq={first.seq}")
    except (StopIteration, grpc.RpcError) as exc:
        check("变更流可用", False, repr(exc))
    finally:
        stream.cancel()

    channel.close()
    print()
    if failures:
        print(f"冒烟失败：{failures} 项未通过")
        return 1
    print("冒烟全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
