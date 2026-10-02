# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""对局事件上报。"""

from __future__ import annotations

import json
import sqlite3

import grpc
import pytest

from ccnr_data.db import Database
from moddata.v1 import moddata_pb2, moddata_pb2_grpc
from support import SERVER_ID, event_request, new_request_id, new_uuid

KIND = moddata_pb2.EventKind


def test_phase_advanced_round_trip(stub: moddata_pb2_grpc.ModDataServiceStub, db: Database) -> None:
    response = stub.RecordEvent(
        event_request(
            KIND.EVENT_KIND_PHASE_ADVANCED,
            match_id="match-1",
            phase_id="phase_2",
            previous_phase_id="phase_1",
        )
    )
    assert response.success
    assert response.seq > 0

    conn: sqlite3.Connection = db.connection()
    row = conn.execute("SELECT * FROM match_events").fetchone()
    assert row["kind"] == "EVENT_KIND_PHASE_ADVANCED"
    assert (row["phase_id"], row["previous_phase_id"], row["match_id"]) == ("phase_2", "phase_1", "match-1")


def test_event_payload_is_canonicalized_json(stub: moddata_pb2_grpc.ModDataServiceStub, db: Database) -> None:
    actor, target = new_uuid(), new_uuid()
    stub.RecordEvent(
        event_request(
            KIND.EVENT_KIND_CHARACTER_KILL,
            actor_uuid=actor,
            target_uuid=target,
            payload_json='{"victimRelation":"hostile","victimType":"player"}',
        )
    )
    conn: sqlite3.Connection = db.connection()
    row = conn.execute("SELECT actor_uuid, target_uuid, payload_json FROM match_events").fetchone()
    assert (row["actor_uuid"], row["target_uuid"]) == (actor, target)
    assert json.loads(row["payload_json"]) == {"victimRelation": "hostile", "victimType": "player"}


def test_phase_advanced_requires_phase_id(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    with pytest.raises(grpc.RpcError) as err:
        stub.RecordEvent(event_request(KIND.EVENT_KIND_PHASE_ADVANCED))
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_unspecified_kind_rejected(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    with pytest.raises(grpc.RpcError) as err:
        stub.RecordEvent(event_request(KIND.EVENT_KIND_UNSPECIFIED))
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.parametrize("payload", ["[]", "not json", '{"a":'])
def test_bad_payload_rejected(stub: moddata_pb2_grpc.ModDataServiceStub, payload: str) -> None:
    with pytest.raises(grpc.RpcError) as err:
        stub.RecordEvent(event_request(KIND.EVENT_KIND_ROUND_ENDED, payload_json=payload))
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_bad_actor_uuid_rejected(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    with pytest.raises(grpc.RpcError) as err:
        stub.RecordEvent(event_request(KIND.EVENT_KIND_CHARACTER_DEATH, actor_uuid="nope"))
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_empty_actor_and_target_allowed(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    assert stub.RecordEvent(event_request(KIND.EVENT_KIND_ROUND_ENDED)).success


def test_event_replay_does_not_duplicate(stub: moddata_pb2_grpc.ModDataServiceStub, db: Database) -> None:
    request = event_request(KIND.EVENT_KIND_GAME_OVER, request_id=new_request_id())
    first = stub.RecordEvent(request)
    second = stub.RecordEvent(request)
    assert first == second
    conn: sqlite3.Connection = db.connection()
    assert conn.execute("SELECT COUNT(*) AS n FROM match_events").fetchone()["n"] == 1


def test_event_uses_global_change_sequence(stub: moddata_pb2_grpc.ModDataServiceStub, db: Database) -> None:
    """RecordEvent 返回的 seq 就是 WatchChanges 的游标。"""
    first = stub.RecordEvent(event_request(KIND.EVENT_KIND_ROUND_ENDED))
    second = stub.RecordEvent(event_request(KIND.EVENT_KIND_ROUND_ENDED, server_id=SERVER_ID))
    assert second.seq == first.seq + 1
    conn: sqlite3.Connection = db.connection()
    rows = conn.execute("SELECT change_type FROM change_log ORDER BY seq").fetchall()
    assert [r["change_type"] for r in rows] == ["match.event", "match.event"]
