# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""错误模型：领域异常 → gRPC 状态码。

服务实现只抛 `DataServiceError`；到状态码的翻译集中在 `service._unary` / `_stream`，
不让每个 RPC 各写一份映射（否则迟早出现同一个原因在不同 RPC 上返回不同码）。
"""

from __future__ import annotations

import grpc

__all__ = [
    "DataServiceError",
    "failed_precondition",
    "internal",
    "invalid_argument",
    "not_found",
    "permission_denied",
    "unavailable",
]


class DataServiceError(Exception):
    """带 gRPC 状态码的领域错误。"""

    __slots__ = ("code", "detail")

    def __init__(self, code: grpc.StatusCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def invalid_argument(detail: str) -> DataServiceError:
    """请求参数不合法（信任边界校验失败）。"""
    return DataServiceError(grpc.StatusCode.INVALID_ARGUMENT, detail)


def not_found(detail: str) -> DataServiceError:
    """目标不存在。"""
    return DataServiceError(grpc.StatusCode.NOT_FOUND, detail)


def permission_denied(detail: str) -> DataServiceError:
    """被服务器策略拒绝（如角色策略冻结）。"""
    return DataServiceError(grpc.StatusCode.PERMISSION_DENIED, detail)


def failed_precondition(detail: str) -> DataServiceError:
    """前置条件不满足（如 request_id 被复用于不同载荷）。"""
    return DataServiceError(grpc.StatusCode.FAILED_PRECONDITION, detail)


def internal(detail: str) -> DataServiceError:
    """服务端自身状态异常。"""
    return DataServiceError(grpc.StatusCode.INTERNAL, detail)


def unavailable(detail: str) -> DataServiceError:
    """依赖不可用（如数据库无法打开）。"""
    return DataServiceError(grpc.StatusCode.UNAVAILABLE, detail)
