# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""玩家结算上报：`ExperienceService.settleUser()` 的落库路径。"""

from __future__ import annotations

import sqlite3

import grpc
import pytest

from ccnr_data.db import Database
from ccnr_data.validation import MAX_LINES
from moddata.v1 import moddata_pb2, moddata_pb2_grpc
from support import SERVER_ID, new_request_id, new_uuid, settlement_request

LINES = [
    ("character_kill", "击杀敌方", 30),
    ("duty_time", "值班时长", 12),
    ("manual:疏散完成", "疏散完成", -5),
]


def test_settlement_persists_header_lines_and_player(
    stub: moddata_pb2_grpc.ModDataServiceStub, db: Database
) -> None:
    player = new_uuid()
    request = settlement_request(
        player,
        match_id="match-1",
        reason="round_end",
        xp_before=100,
        xp_after=137,
        level_before=1,
        level_after=1,
        lines=LINES,
        username="Alex",
    )
    response = stub.RecordSettlement(request)

    assert response.success
    assert (response.xp_after, response.level_after, response.line_count) == (137, 1, 3)
    assert response.stored_xp_before == 0
    assert response.xp_diverged  # 库里原本没有这个玩家

    conn: sqlite3.Connection = db.connection()
    row = conn.execute("SELECT * FROM settlements").fetchone()
    assert (row["match_id"], row["reason"], row["gain"]) == ("match-1", "round_end", 37)

    lines = conn.execute(
        "SELECT line_no, rule_id, title, value FROM settlement_lines ORDER BY line_no"
    ).fetchall()
    assert [(r["line_no"], r["rule_id"], r["value"]) for r in lines] == [
        (1, "character_kill", 30),
        (2, "duty_time", 12),
        (3, "manual:疏散完成", -5),
    ]

    fetched = stub.GetPlayer(moddata_pb2.GetPlayerRequest(player_uuid=player, server_id=SERVER_ID)).player
    assert (fetched.experience, fetched.level, fetched.username) == (137, 1, "Alex")


def test_no_divergence_when_server_matches(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    player = new_uuid()
    stub.RecordSettlement(
        settlement_request(player, xp_before=0, xp_after=10, lines=[("duty_time", "值班", 10)])
    )
    second = stub.RecordSettlement(
        settlement_request(player, xp_before=10, xp_after=18, lines=[("duty_time", "值班", 8)])
    )
    assert not second.xp_diverged
    assert second.stored_xp_before == 10


def test_divergence_reported_and_authority_wins(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    """模组端才是权威：库里值不同则覆盖，但要把差异回报出去。"""
    player = new_uuid()
    stub.RecordSettlement(settlement_request(player, xp_before=0, xp_after=100, lines=[("a", "a", 100)]))
    response = stub.RecordSettlement(
        settlement_request(player, xp_before=40, xp_after=60, lines=[("b", "b", 20)])
    )

    assert response.xp_diverged
    assert response.stored_xp_before == 100
    fetched = stub.GetPlayer(moddata_pb2.GetPlayerRequest(player_uuid=player, server_id=SERVER_ID)).player
    assert fetched.experience == 60


def test_empty_settlement_is_allowed(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    response = stub.RecordSettlement(settlement_request(new_uuid(), xp_before=5, xp_after=5))
    assert (response.success, response.line_count, response.xp_after) == (True, 0, 5)


def test_replay_applies_once(stub: moddata_pb2_grpc.ModDataServiceStub, db: Database) -> None:
    player = new_uuid()
    request = settlement_request(player, xp_before=0, xp_after=9, lines=[("duty_time", "值班", 9)])
    first = stub.RecordSettlement(request)
    second = stub.RecordSettlement(request)

    assert first == second
    conn: sqlite3.Connection = db.connection()
    assert conn.execute("SELECT COUNT(*) AS n FROM settlements").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM settlement_lines").fetchone()["n"] == 1


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"xp_before": 10, "xp_after": 20, "lines": [("a", "a", 5)]}, "明细合计与 gain 不一致"),
        ({"xp_before": 10, "xp_after": 20}, "无明细但 gain 非 0"),
        ({"xp_before": -1, "xp_after": 5, "lines": [("a", "a", 6)]}, "经验为负"),
        ({"xp_before": 0, "xp_after": 5, "level_after": -2, "lines": [("a", "a", 5)]}, "等级为负"),
        ({"xp_before": 0, "xp_after": 5, "match_id": "bad id", "lines": [("a", "a", 5)]}, "match_id 含空格"),
        ({"xp_before": 0, "xp_after": 5, "reason": "", "lines": [("a", "a", 5)]}, "reason 为空"),
    ],
)
def test_invalid_settlements_rejected(
    stub: moddata_pb2_grpc.ModDataServiceStub, kwargs: dict[str, object], reason: str
) -> None:
    with pytest.raises(grpc.RpcError) as err:
        stub.RecordSettlement(settlement_request(new_uuid(), **kwargs))  # type: ignore[arg-type]
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT, reason


def test_too_many_lines_rejected(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    lines = [("r", "t", 1) for _ in range(MAX_LINES + 1)]
    with pytest.raises(grpc.RpcError) as err:
        stub.RecordSettlement(settlement_request(new_uuid(), xp_before=0, xp_after=len(lines), lines=lines))
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_settlement_time_out_of_window_rejected(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    with pytest.raises(grpc.RpcError) as err:
        stub.RecordSettlement(settlement_request(new_uuid(), settled_at=1))
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_request_id_reuse_with_different_totals_rejected(
    stub: moddata_pb2_grpc.ModDataServiceStub,
) -> None:
    request_id = new_request_id()
    player = new_uuid()
    stub.RecordSettlement(
        settlement_request(player, request_id=request_id, xp_before=0, xp_after=5, lines=[("a", "a", 5)])
    )
    with pytest.raises(grpc.RpcError) as err:
        stub.RecordSettlement(
            settlement_request(player, request_id=request_id, xp_before=0, xp_after=6, lines=[("a", "a", 6)])
        )
    assert err.value.code() == grpc.StatusCode.FAILED_PRECONDITION
