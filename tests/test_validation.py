# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""信任边界校验的单元测试。"""

from __future__ import annotations

import json

import pytest
from google.protobuf.timestamp_pb2 import Timestamp

from ccnr_data import validation
from ccnr_data.clock import now_ms
from ccnr_data.errors import DataServiceError
from moddata.v1 import moddata_pb2


def test_player_uuid_normalized() -> None:
    assert (
        validation.player_uuid("AABBCCDD-EEFF-0011-2233-445566778899")
        == "aabbccdd-eeff-0011-2233-445566778899"
    )


@pytest.mark.parametrize("raw", ["", "not-a-uuid", "12345"])
def test_bad_player_uuid_rejected(raw: str) -> None:
    with pytest.raises(DataServiceError):
        validation.player_uuid(raw)


@pytest.mark.parametrize("raw", ["server-1", "srv_2", "a.b:c-1", "s1"])
def test_identifier_accepts_documented_charset(raw: str) -> None:
    assert validation.identifier(raw, "server_id") == raw


@pytest.mark.parametrize("raw", ["", "-lead", "has space", "has/slash", "带中文"])
def test_identifier_rejects_other_charset(raw: str) -> None:
    with pytest.raises(DataServiceError):
        validation.identifier(raw, "server_id")


def test_identifier_length_cap() -> None:
    assert validation.identifier("a" * 64, "server_id") == "a" * 64
    with pytest.raises(DataServiceError):
        validation.identifier("a" * 65, "server_id")


def test_optional_identifier_allows_empty() -> None:
    assert validation.optional_identifier("  ", "match_id") == ""
    assert validation.optional_identifier("m-1", "match_id") == "m-1"


def test_require_text_allows_empty_when_asked() -> None:
    assert validation.require_text("", "title", max_len=10, allow_empty=True) == ""
    with pytest.raises(DataServiceError):
        validation.require_text("", "title", max_len=10)


def test_json_object_text_canonicalizes() -> None:
    assert validation.json_object_text('{"b":1,"a":2}', "p") == '{"a":2,"b":1}'
    assert validation.json_object_text("", "p") == "{}"
    assert validation.json_object_text("", "p", default='{"x":1}') == '{"x":1}'


@pytest.mark.parametrize("raw", ["[]", '"text"', "1", "{bad json}"])
def test_json_object_rejects_non_objects(raw: str) -> None:
    with pytest.raises(DataServiceError):
        validation.json_object_text(raw, "p")


def test_json_object_size_cap() -> None:
    oversized = json.dumps({"k": "x" * (validation.MAX_PAYLOAD_BYTES + 1)})
    with pytest.raises(DataServiceError):
        validation.json_object_text(oversized, "p")


def test_epoch_ms_unset_uses_now() -> None:
    before = now_ms()
    assert validation.epoch_ms(Timestamp(), "t") >= before


def test_epoch_ms_rejects_zero_value() -> None:
    with pytest.raises(DataServiceError):
        validation.epoch_ms(Timestamp(seconds=1), "t")


def test_epoch_ms_rejects_far_future() -> None:
    with pytest.raises(DataServiceError):
        validation.epoch_ms(Timestamp(seconds=now_ms() // 1000 + 3 * 24 * 3600), "t")


def test_epoch_ms_round_trips_millis() -> None:
    stamp = Timestamp(seconds=1_700_000_000, nanos=123_000_000)
    assert validation.epoch_ms(stamp, "t") == 1_700_000_000_123


def test_event_kind_rejects_unspecified_and_unknown() -> None:
    with pytest.raises(DataServiceError):
        validation.event_kind(moddata_pb2.EVENT_KIND_UNSPECIFIED)
    with pytest.raises(DataServiceError):
        validation.event_kind(9999)
    assert validation.event_kind(moddata_pb2.EVENT_KIND_ROUND_ENDED) == moddata_pb2.EVENT_KIND_ROUND_ENDED
