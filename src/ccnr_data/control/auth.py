# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""control.v1 的 token 鉴权拦截器。

只保护控制面：模组侧 moddata.v1 是内网调用且已有部署边界，不在本轮加 token，
避免代理/模组两侧同时改。健康检查与反射不鉴权。
"""

from __future__ import annotations

from collections.abc import Callable

import grpc

__all__ = ["TokenInterceptor"]

PROTECTED_PREFIX = "/control.v1."
PUBLIC_PREFIXES = ("/grpc.health.v1.Health/", "/grpc.reflection.")


class TokenInterceptor(grpc.ServerInterceptor):  # type: ignore[misc]  # grpc 未随包发类型标注
    def __init__(self, tokens: dict[str, str]) -> None:
        self._tokens = {value for value in tokens.values() if value}

    def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], grpc.RpcMethodHandler | None],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler | None:
        if not self._tokens:
            return continuation(handler_call_details)
        method = handler_call_details.method or ""
        if not method.startswith(PROTECTED_PREFIX) or method.startswith(PUBLIC_PREFIXES):
            return continuation(handler_call_details)

        metadata = dict(handler_call_details.invocation_metadata or [])
        header = metadata.get("authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        if token in self._tokens:
            return continuation(handler_call_details)

        def deny(_request: object, context: grpc.ServicerContext) -> None:
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "缺少或错误的 control.v1 token")

        return grpc.unary_unary_rpc_method_handler(deny)
