# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""WatchChanges 变更流。"""

from __future__ import annotations

import threading
import time

import grpc
import pytest

from ccnr_data import repositories as repo
from ccnr_data.db import Database
from dbutil import raw_connection
from moddata.v1 import moddata_pb2, moddata_pb2_grpc
from support import apply_request, event_request, new_uuid

KIND = moddata_pb2.EventKind


def drain(
    stub: moddata_pb2_grpc.ModDataServiceStub, *, since_seq: int = 0, server_id: str = "", limit: int = 3
) -> list[moddata_pb2.ChangeEvent]:
    """取到 limit 条就取消订阅（服务端流是长连接，测试里必须主动停）。"""
    stream = stub.WatchChanges(moddata_pb2.WatchChangesRequest(since_seq=since_seq, server_id=server_id))
    out: list[moddata_pb2.ChangeEvent] = []
    try:
        for change in stream:
            out.append(change)
            if len(out) >= limit:
                break
    finally:
        stream.cancel()
    return out


def test_stream_replays_from_cursor(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    player = new_uuid()
    stub.ApplyExperience(apply_request(player, 10, reason="first"))
    stub.RecordEvent(event_request(KIND.EVENT_KIND_ROUND_ENDED))

    changes = drain(stub, limit=2)
    assert [c.change_type for c in changes] == ["player.experience", "match.event"]
    assert changes[0].player_uuid == player
    assert changes[0].seq < changes[1].seq

    # 从第一条之后开始：必须从第二条续上，不重不漏。
    tail = drain(stub, since_seq=changes[0].seq, limit=1)
    assert [c.seq for c in tail] == [changes[1].seq]


def test_server_filter(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    stub.ApplyExperience(apply_request(new_uuid(), 1, server_id="srv-a"))
    stub.ApplyExperience(apply_request(new_uuid(), 1, server_id="srv-b"))
    changes = drain(stub, server_id="srv-b", limit=1)
    assert [c.server_id for c in changes] == ["srv-b"]


def test_change_payload_is_json(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    import json

    player = new_uuid()
    stub.ApplyExperience(apply_request(player, 42, reason="manual:test"))
    change = drain(stub, limit=1)[0]
    payload = json.loads(change.payload_json)
    assert payload["experience"] == 42
    assert payload["delta"] == 42
    assert change.occurred_at.seconds > 0


def test_negative_cursor_rejected(stub: moddata_pb2_grpc.ModDataServiceStub) -> None:
    with pytest.raises(grpc.RpcError) as err:
        next(iter(stub.WatchChanges(moddata_pb2.WatchChangesRequest(since_seq=-1))))
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_stream_waits_and_delivers_later_changes(
    stub: moddata_pb2_grpc.ModDataServiceStub,
) -> None:
    """订阅先于数据建立：轮询循环必须把后到的变更推出来，而不是立刻结束。"""
    stub.ApplyExperience(apply_request(new_uuid(), 1))
    cursor = drain(stub, limit=1)[0].seq  # 先追平到当前末尾

    def produce() -> None:
        time.sleep(0.3)
        stub.ApplyExperience(apply_request(new_uuid(), 2))

    producer = threading.Thread(target=produce)
    producer.start()
    try:
        delivered = drain(stub, since_seq=cursor, limit=1)
    finally:
        producer.join(timeout=5)

    assert [c.seq for c in delivered] == [cursor + 1]


def test_gap_from_retention_does_not_kill_the_subscription(
    stub: moddata_pb2_grpc.ModDataServiceStub, db: Database
) -> None:
    """游标落在保留窗口之前：只告警，订阅方仍要能继续收到当前数据。

    日志轮换按时间整批删，没法只删"中间那几条"；这里直接改库来构造这个场景。
    """
    for _ in range(3):
        stub.ApplyExperience(apply_request(new_uuid(), 1))
    conn = raw_connection(db)
    try:
        conn.execute("DELETE FROM change_log WHERE seq <= 2")
        conn.commit()
    finally:
        conn.close()
    with db.read() as session:
        assert repo.oldest_change_seq(session) == 3

    def produce() -> None:
        time.sleep(0.3)
        stub.ApplyExperience(apply_request(new_uuid(), 5))

    producer = threading.Thread(target=produce)
    producer.start()
    try:
        delivered = drain(stub, since_seq=1, limit=2)
    finally:
        producer.join(timeout=5)

    # 断档之后的现存变更（seq=3）与新到的变更（seq=4）都要照常推出，不能因为断档就罢工。
    assert [c.seq for c in delivered] == [3, 4]
