# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""角色覆盖与服务器策略。"""

from __future__ import annotations

import grpc
import pytest

from moddata.v1 import moddata_pb2, moddata_pb2_grpc
from support import SERVER_ID, new_request_id, new_uuid, role_request

POLICY = moddata_pb2.RolePolicy


def get_player(stub: moddata_pb2_grpc.ModDataServiceStub, player: str) -> moddata_pb2.PlayerData:
    return stub.GetPlayer(moddata_pb2.GetPlayerRequest(player_uuid=player, server_id=SERVER_ID)).player


def set_policy(
    stub: moddata_pb2_grpc.ModDataServiceStub, policy: int, server_id: str = SERVER_ID
) -> moddata_pb2.UpdateServerConfigResponse:
    return stub.UpdateServerConfig(
        moddata_pb2.UpdateServerConfigRequest(
            request_id=new_request_id(), server_id=server_id, role_policy=policy, actor="console"
        )
    )


def test_roles_accumulate_and_disable(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    player = new_uuid()
    assert stub.SetRoleOverride(role_request(player, "medic", True)).current_roles == ["medic"]
    assert stub.SetRoleOverride(role_request(player, "engineer", True)).current_roles == [
        "engineer",
        "medic",
    ]
    assert stub.SetRoleOverride(role_request(player, "medic", False)).current_roles == ["engineer"]
    assert get_player(stub, player).roles == ["engineer"]


def test_role_change_bumps_player_version(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    player = new_uuid()
    first = stub.SetRoleOverride(role_request(player, "medic", True))
    second = stub.SetRoleOverride(role_request(player, "engineer", True))
    assert (first.version, second.version) == (1, 2)
    assert get_player(stub, player).version == 2


def test_frozen_policy_denies_changes(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    player = new_uuid()
    stub.SetRoleOverride(role_request(player, "medic", True))
    set_policy(stub, POLICY.ROLE_POLICY_FROZEN)

    with pytest.raises(grpc.RpcError) as err:
        stub.SetRoleOverride(role_request(player, "engineer", True))
    assert err.value.code() == grpc.StatusCode.PERMISSION_DENIED

    # 冻结只挡写，不挡读。
    assert get_player(stub, player).roles == ["medic"]


def test_forced_on_policy_ignores_disable(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    player = new_uuid()
    set_policy(stub, POLICY.ROLE_POLICY_FORCED_ON)
    response = stub.SetRoleOverride(role_request(player, "commander", False))
    assert response.current_roles == ["commander"]


def test_policy_is_per_server(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    player = new_uuid()
    set_policy(stub, POLICY.ROLE_POLICY_FROZEN, server_id="srv-a")
    # srv-b 未设策略 → 默认 OPEN
    assert stub.SetRoleOverride(role_request(player, "medic", True, server_id="srv-b")).current_roles == [
        "medic"
    ]


def test_default_config_when_never_written(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    response = stub.GetServerConfig(moddata_pb2.GetServerConfigRequest(server_id=SERVER_ID))
    assert response.role_policy == POLICY.ROLE_POLICY_OPEN
    assert response.config_json == "{}"
    assert response.version == 0
    assert not response.HasField("updated_at")  # 没写过就不谎报时间


def test_update_server_config_partial_and_versioned(
    stub: moddata_pb2_grpc.ModDataServiceStub,
) -> None:
    first = stub.UpdateServerConfig(
        moddata_pb2.UpdateServerConfigRequest(
            request_id=new_request_id(), server_id=SERVER_ID, config_json='{"b":2,"a":1}', actor="console"
        )
    )
    assert first.config.config_json == '{"a":1,"b":2}'
    assert first.config.role_policy == POLICY.ROLE_POLICY_OPEN  # 未指定的项不动
    assert first.config.version == 1
    assert first.config.HasField("updated_at")

    second = stub.UpdateServerConfig(
        moddata_pb2.UpdateServerConfigRequest(
            request_id=new_request_id(), server_id=SERVER_ID, role_policy=POLICY.ROLE_POLICY_FROZEN
        )
    )
    assert second.config.config_json == '{"a":1,"b":2}'  # 上一轮写的配置还在
    assert second.config.role_policy == POLICY.ROLE_POLICY_FROZEN
    assert second.config.version == 2


def test_update_requires_at_least_one_field(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    with pytest.raises(grpc.RpcError) as err:
        stub.UpdateServerConfig(
            moddata_pb2.UpdateServerConfigRequest(request_id=new_request_id(), server_id=SERVER_ID)
        )
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_update_rejects_unspecified_policy(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    with pytest.raises(grpc.RpcError) as err:
        stub.UpdateServerConfig(
            moddata_pb2.UpdateServerConfigRequest(
                request_id=new_request_id(), server_id=SERVER_ID, role_policy=POLICY.ROLE_POLICY_UNSPECIFIED
            )
        )
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_update_rejects_non_object_config(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    with pytest.raises(grpc.RpcError) as err:
        stub.UpdateServerConfig(
            moddata_pb2.UpdateServerConfigRequest(
                request_id=new_request_id(), server_id=SERVER_ID, config_json="[1,2]"
            )
        )
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_update_is_idempotent(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    request = moddata_pb2.UpdateServerConfigRequest(
        request_id=new_request_id(), server_id=SERVER_ID, role_policy=POLICY.ROLE_POLICY_FROZEN
    )
    first = stub.UpdateServerConfig(request)
    second = stub.UpdateServerConfig(request)
    assert first == second
    assert second.config.version == 1
