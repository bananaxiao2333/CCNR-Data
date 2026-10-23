# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""控制面指标（Prometheus）。

只做进程内计数；/metrics 由 HTTP 边缘暴露。
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

__all__ = [
    "AUTHORIZE_LATENCY",
    "AUTHORIZE_TOTAL",
    "CASDOOR_CIRCUIT_OPEN",
    "CASDOOR_REQUESTS",
    "REPORTS_TOTAL",
    "SESSIONS_ONLINE",
]

AUTHORIZE_TOTAL = Counter("ccnr_control_authorize_total", "准入决策次数", ["decision", "reason"])
AUTHORIZE_LATENCY = Histogram(
    "ccnr_control_authorize_latency_seconds", "准入决策耗时", buckets=(0.005, 0.01, 0.05, 0.1, 0.5, 1.0)
)
REPORTS_TOTAL = Counter("ccnr_control_reports_total", "代理事件上报次数", ["kind"])
SESSIONS_ONLINE = Gauge("ccnr_control_sessions_online", "当前在线会话数")
CASDOOR_REQUESTS = Counter("ccnr_casdoor_requests_total", "Casdoor 请求结果", ["result"])
CASDOOR_CIRCUIT_OPEN = Gauge("ccnr_casdoor_circuit_open", "Casdoor 熔断是否打开（1=打开）")
