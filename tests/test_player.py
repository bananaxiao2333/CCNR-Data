# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""GetPlayer / ApplyExperience。"""

from __future__ import annotations

import sqlite3

import grpc
import pytest

from ccnr_data.db import Database
from dbutil import raw_connection
from moddata.v1 import moddata_pb2, moddata_pb2_grpc
from support import SERVER_ID, apply_request, new_uuid


def test_get_unknown_player_is_not_found(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    with pytest.raises(grpc.RpcError) as err:
        stub.GetPlayer(moddata_pb2.GetPlayerRequest(player_uuid=new_uuid(), server_id=SERVER_ID))
    assert err.value.code() == grpc.StatusCode.NOT_FOUND


def test_apply_experience_creates_player(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    player = new_uuid()
    response = stub.ApplyExperience(apply_request(player, 120, username="Steve", level=1))

    assert response.success
    assert (response.experience, response.level, response.version) == (120, 1, 1)

    fetched = stub.GetPlayer(moddata_pb2.GetPlayerRequest(player_uuid=player, server_id=SERVER_ID)).player
    assert (fetched.experience, fetched.level, fetched.username) == (120, 1, "Steve")
    assert fetched.roles == []
    assert fetched.updated_at.seconds > 0


def test_level_untouched_without_explicit_level(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    """权威端没给等级时不能自己推算——本服务不做等级曲线。"""
    player = new_uuid()
    stub.ApplyExperience(apply_request(player, 100, level=5))
    second = stub.ApplyExperience(apply_request(player, 50))
    assert (second.experience, second.level) == (150, 5)


def test_experience_clamped_at_zero(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    player = new_uuid()
    stub.ApplyExperience(apply_request(player, 10))
    assert stub.ApplyExperience(apply_request(player, -999)).experience == 0


def test_version_increments_per_write(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    player = new_uuid()
    versions = [stub.ApplyExperience(apply_request(player, 1)).version for _ in range(3)]
    assert versions == [1, 2, 3]


def test_username_kept_when_not_resupplied(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    """离线结算拿不到玩家名，不能因此把库里已有的名字抹掉。"""
    player = new_uuid()
    stub.ApplyExperience(apply_request(player, 1, username="Alex"))
    stub.ApplyExperience(apply_request(player, 1, username=""))
    fetched = stub.GetPlayer(moddata_pb2.GetPlayerRequest(player_uuid=player, server_id=SERVER_ID)).player
    assert fetched.username == "Alex"


def test_write_leaves_audit_and_change_rows(stub: moddata_pb2_grpc.ModDataServiceStub, db: Database) -> None:
    player = new_uuid()
    stub.ApplyExperience(apply_request(player, 7, reason="manual:test"))

    conn: sqlite3.Connection = raw_connection(db)
    audit = conn.execute("SELECT actor, action, target, after_json FROM audit_log").fetchall()
    assert len(audit) == 1
    assert audit[0]["action"] == "apply_experience"
    assert audit[0]["actor"] == SERVER_ID
    assert player in audit[0]["target"]

    changes = conn.execute("SELECT change_type, player_uuid, version FROM change_log").fetchall()
    assert [(c["change_type"], c["player_uuid"]) for c in changes] == [("player.experience", player)]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("server_id", "bad server"),
        ("server_id", ""),
        ("player_uuid", "not-a-uuid"),
        ("request_id", "has space"),
    ],
)
def test_bad_arguments_rejected(stub: moddata_pb2_grpc.ModDataServiceStub, field: str, value: str) -> None:
    request = apply_request(new_uuid(), 1)
    setattr(request, field, value)
    with pytest.raises(grpc.RpcError) as err:
        stub.ApplyExperience(request)
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_negative_level_rejected(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    with pytest.raises(grpc.RpcError) as err:
        stub.ApplyExperience(apply_request(new_uuid(), 1, level=-1))
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT
