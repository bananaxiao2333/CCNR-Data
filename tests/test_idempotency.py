# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""幂等：重放不重复落账，复用键不算重放。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import grpc
import pytest

from moddata.v1 import moddata_pb2, moddata_pb2_grpc
from support import SERVER_ID, apply_request, new_request_id, new_uuid


def test_replay_returns_same_response_and_applies_once(
    stub: moddata_pb2_grpc.ModDataServiceStub,
) -> None:
    player = new_uuid()
    request = apply_request(player, 40, request_id=new_request_id())

    first = stub.ApplyExperience(request)
    second = stub.ApplyExperience(request)

    assert first == second
    assert second.experience == 40  # 不是 80
    fetched = stub.GetPlayer(moddata_pb2.GetPlayerRequest(player_uuid=player, server_id=SERVER_ID)).player
    assert fetched.experience == 40
    assert fetched.version == 1


def test_same_key_different_payload_rejected(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    """宁可报错也不回放一个语义不同的结果。"""
    player = new_uuid()
    request_id = new_request_id()
    stub.ApplyExperience(apply_request(player, 40, request_id=request_id))

    with pytest.raises(grpc.RpcError) as err:
        stub.ApplyExperience(apply_request(player, 41, request_id=request_id))
    assert err.value.code() == grpc.StatusCode.FAILED_PRECONDITION


def test_same_key_across_methods_rejected(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    request_id = new_request_id()
    stub.ApplyExperience(apply_request(new_uuid(), 1, request_id=request_id))
    with pytest.raises(grpc.RpcError) as err:
        stub.SetRoleOverride(
            moddata_pb2.SetRoleOverrideRequest(
                request_id=request_id,
                player_uuid=new_uuid(),
                server_id=SERVER_ID,
                role="medic",
                enabled=True,
                source="admin",
            )
        )
    assert err.value.code() == grpc.StatusCode.FAILED_PRECONDITION


def test_concurrent_replay_applies_exactly_once(
    stub: moddata_pb2_grpc.ModDataServiceStub, channel: grpc.Channel
) -> None:
    """8 个线程同时用同一个 request_id —— 写锁串行化后只应生效一次。"""
    player = new_uuid()
    request = apply_request(player, 25, request_id=new_request_id())

    def send(_: int) -> int:
        local = moddata_pb2_grpc.ModDataServiceStub(channel)  # type: ignore[no-untyped-call]
        return local.ApplyExperience(request).experience

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(send, range(8)))

    assert results == [25] * 8
    fetched = stub.GetPlayer(moddata_pb2.GetPlayerRequest(player_uuid=player, server_id=SERVER_ID)).player
    assert fetched.experience == 25
    assert fetched.version == 1
