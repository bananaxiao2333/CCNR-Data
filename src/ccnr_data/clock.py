# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""时间基准。

库里所有时间列都是 **UTC epoch 毫秒整数**（`INTEGER`）：可排序、无时区歧义、
跨 SQLite / PostgreSQL 语义一致（PostgreSQL 侧对应 `BIGINT`）。
"""

from __future__ import annotations

import time

__all__ = ["now_ms"]

#: 允许接受的最早时间戳（2020-01-01T00:00:00Z）。比它更早的一律视为脏数据。
MIN_EPOCH_MS = 1_577_836_800_000

#: 允许接受的最晚时间戳相对当前的宽限（24 小时），用于容忍权威端与本服务的时钟偏差。
MAX_CLOCK_SKEW_MS = 24 * 60 * 60 * 1000


def now_ms() -> int:
    """当前 UTC 时间的 epoch 毫秒。"""
    return int(time.time() * 1000)
