# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""服务装配与进程入口。

装配三件事：业务服务、健康检查（供 Gate / K8s / HAProxy 探活）、反射
（供 grpcurl 等工具在排障时直接看到契约，省掉"把 proto 拷过去"这一步）。
"""

from __future__ import annotations

import logging
import signal
import threading
from concurrent import futures
from dataclasses import dataclass

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection

from ccnr_data.config import Config
from ccnr_data.db import Database
from ccnr_data.retention import RetentionPolicy, RetentionWorker
from ccnr_data.service import ModDataService
from moddata.v1 import moddata_pb2, moddata_pb2_grpc

__all__ = ["SERVICE_NAME", "ServerHandle", "build_server", "configure_logging", "serve"]

LOGGER = logging.getLogger(__name__)

SERVICE_NAME = moddata_pb2.DESCRIPTOR.services_by_name["ModDataService"].full_name

SHUTDOWN_GRACE_SECONDS = 5.0


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )


@dataclass(slots=True)
class ServerHandle:
    """装配好的服务：调用方负责 start()，停机走 stop()。"""

    server: grpc.Server
    port: int
    health_servicer: health.HealthServicer

    def stop(self, grace: float = SHUTDOWN_GRACE_SECONDS) -> None:
        """先摘健康检查（让负载均衡把流量挪走），再等正在处理的请求收尾。"""
        self.health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)
        self.health_servicer.set(SERVICE_NAME, health_pb2.HealthCheckResponse.NOT_SERVING)
        self.server.stop(grace=grace).wait(timeout=grace + 5)


def build_server(config: Config, db: Database) -> ServerHandle:
    """装配 gRPC 服务并绑定端口；端口写 0 时由内核分配，实际端口在返回值里。"""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=config.max_workers))
    # 生成桩没有类型标注（protoc 不为 *_pb2_grpc.py 出 .pyi），这个调用必然是"未类型化"。
    moddata_pb2_grpc.add_ModDataServiceServicer_to_server(  # type: ignore[no-untyped-call]
        ModDataService(db, watch_poll_ms=config.watch_poll_ms), server
    )

    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set(SERVICE_NAME, health_pb2.HealthCheckResponse.SERVING)

    reflection.enable_server_reflection(
        (SERVICE_NAME, health_pb2.DESCRIPTOR.services_by_name["Health"].full_name, reflection.SERVICE_NAME),
        server,
    )

    host, port = config.bind_host_port
    bound = server.add_insecure_port(f"{host}:{port}")
    if not bound:
        raise RuntimeError(f"无法绑定 {config.bind}：端口已被占用或地址不可用")
    return ServerHandle(server=server, port=bound, health_servicer=health_servicer)


def serve(config: Config) -> int:
    """跑服务直到收到 SIGINT / SIGTERM。"""
    db = Database(config.db_file)
    db.open()
    handle = build_server(config, db)
    handle.server.start()
    host, _ = config.bind_host_port
    LOGGER.info("CCNR-Data 已监听 %s:%d（数据库：%s）", host, handle.port, db.path)

    retention = RetentionWorker(db, RetentionPolicy.from_config(config))
    retention.start()

    stopping = threading.Event()

    def _on_signal(signum: int, _frame: object) -> None:
        LOGGER.info("收到信号 %s，开始优雅停机", signal.Signals(signum).name)
        stopping.set()

    previous = {sig: signal.signal(sig, _on_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        stopping.wait()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        retention.stop()
        handle.stop()
        db.close()
        LOGGER.info("CCNR-Data 已停止")
    return 0
