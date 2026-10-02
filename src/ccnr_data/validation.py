# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""信任边界校验。

本服务的调用方（模组服务端、Gate 插件、管理脚本）都在主机边界之外，
**任何进入持久层的值都必须先过这里**。规则统一、报错带字段名，
不允许各 RPC 自己写一份宽松版。
"""

from __future__ import annotations

import json
import re
import uuid

from google.protobuf.timestamp_pb2 import Timestamp

from ccnr_data.clock import MAX_CLOCK_SKEW_MS, MIN_EPOCH_MS, now_ms
from ccnr_data.errors import invalid_argument
from moddata.v1 import moddata_pb2

__all__ = [
    "MAX_LINES",
    "MAX_PAYLOAD_BYTES",
    "epoch_ms",
    "event_kind",
    "identifier",
    "json_object_text",
    "optional_identifier",
    "player_uuid",
    "require_text",
    "uuid_or_empty",
]

#: 单次结算允许携带的明细条数上限。防止一次请求塞爆事务。
MAX_LINES = 512

#: 自由载荷（payload_json / config_json）字节上限。
MAX_PAYLOAD_BYTES = 64 * 1024

MAX_ID_LEN = 64
MAX_REQUEST_ID_LEN = 128
MAX_MATCH_ID_LEN = 128
MAX_USERNAME_LEN = 64
MAX_REASON_LEN = 128
MAX_SOURCE_LEN = 128
MAX_TITLE_LEN = 256

#: 标识符字符集：模组侧 server id / role / rule id 都落在这个范围内。
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*\Z")


def require_text(raw: str, field: str, *, max_len: int, allow_empty: bool = False) -> str:
    """去空白后按长度校验的普通文本。"""
    value = (raw or "").strip()
    if not value:
        if allow_empty:
            return ""
        raise invalid_argument(f"{field} 不能为空")
    if len(value) > max_len:
        raise invalid_argument(f"{field} 长度上限 {max_len}，实际 {len(value)}")
    return value


def identifier(raw: str, field: str, *, max_len: int = MAX_ID_LEN) -> str:
    """标识符：非空、限定字符集、限定长度。"""
    value = require_text(raw, field, max_len=max_len)
    if not _ID_RE.fullmatch(value):
        raise invalid_argument(f"{field} 只允许字母、数字与 _ . : -，且必须以字母或数字开头：{value!r}")
    return value


def optional_identifier(raw: str, field: str, *, max_len: int = MAX_ID_LEN) -> str:
    """可空标识符：空串合法（表示"未提供"），非空时按标识符校验。"""
    if raw is None or not raw.strip():
        return ""
    return identifier(raw, field, max_len=max_len)


def player_uuid(raw: str, field: str = "player_uuid") -> str:
    """玩家 UUID，规范化为小写带连字符的标准形式后作为主键使用。"""
    value = require_text(raw, field, max_len=64)
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise invalid_argument(f"{field} 不是合法 UUID：{raw!r}") from exc


def uuid_or_empty(raw: str, field: str) -> str:
    """可空 UUID：空串表示"本次事件不涉及该主体"，非空时必须能被解析。"""
    if raw is None or not raw.strip():
        return ""
    return player_uuid(raw, field)


def json_object_text(raw: str, field: str, *, default: str = "{}") -> str:
    """校验为 JSON **对象**，返回键排序后的紧凑文本（落库形态稳定，便于逐字节比对）。"""
    value = (raw or "").strip()
    if not value:
        return default
    if len(value.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise invalid_argument(f"{field} 超过 {MAX_PAYLOAD_BYTES} 字节上限")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise invalid_argument(f"{field} 不是合法 JSON：{exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise invalid_argument(f"{field} 必须是 JSON 对象")
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def epoch_ms(stamp: Timestamp, field: str) -> int:
    """把 protobuf Timestamp 转成 epoch 毫秒。

    只有**整为零**的时间戳算"未提供"（取当前时间）。
    只要有值就按 [2020-01-01, now+24h] 校验——否则 `seconds=0, nanos=1e6`
    这类"看着像零值其实不是"的脏数据会被静默当成当前时间收下。
    """
    if stamp is None or (int(stamp.seconds) == 0 and int(stamp.nanos) == 0):
        return now_ms()
    seconds = int(stamp.seconds)
    value = seconds * 1000 + (int(stamp.nanos) // 1_000_000)
    if value < MIN_EPOCH_MS:
        raise invalid_argument(f"{field} 早于 2020-01-01，疑似零值或脏数据：{value}ms")
    latest = now_ms() + MAX_CLOCK_SKEW_MS
    if value > latest:
        raise invalid_argument(f"{field} 超出当前时间 24 小时以上，疑似时钟异常：{value}ms")
    return value


def event_kind(value: int, field: str = "kind") -> int:
    """事件种类：必须是 EventKind 里已定义且非 UNSPECIFIED 的值。"""
    if value == moddata_pb2.EVENT_KIND_UNSPECIFIED:
        raise invalid_argument(f"{field} 不能是 EVENT_KIND_UNSPECIFIED")
    try:
        moddata_pb2.EventKind.Name(value)
    except ValueError as exc:
        raise invalid_argument(f"{field} 不是已定义的 EventKind：{value}") from exc
    return int(value)
