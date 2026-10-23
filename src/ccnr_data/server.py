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
from ccnr_data.control.auth import TokenInterceptor
from ccnr_data.control.device_login import DeviceLoginPoller
from ccnr_data.control.http_edge import HttpEdge
from ccnr_data.control.maintenance import SessionReaper
from ccnr_data.control.service import ControlService
from ccnr_data.control.settings import ControlSettings
from ccnr_data.db import Database
from ccnr_data.retention import RetentionPolicy, RetentionWorker
from ccnr_data.service import ModDataService
from control.v1 import control_pb2, control_pb2_grpc
from moddata.v1 import moddata_pb2, moddata_pb2_grpc

__all__ = [
    "CONTROL_SERVICE_NAME",
    "SERVICE_NAME",
    "ServerHandle",
    "build_server",
    "configure_logging",
    "serve",
]

LOGGER = logging.getLogger(__name__)

SERVICE_NAME = moddata_pb2.DESCRIPTOR.services_by_name["ModDataService"].full_name
CONTROL_SERVICE_NAME = control_pb2.DESCRIPTOR.services_by_name["ControlService"].full_name

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
    control: ControlService | None = None
    http_edge: HttpEdge | None = None
    reaper: SessionReaper | None = None
    device_poller: DeviceLoginPoller | None = None

    def stop(self, grace: float = SHUTDOWN_GRACE_SECONDS) -> None:
        """先摘健康检查（让负载均衡把流量挪走），再等正在处理的请求收尾。"""
        for name in ("", SERVICE_NAME, CONTROL_SERVICE_NAME):
            self.health_servicer.set(name, health_pb2.HealthCheckResponse.NOT_SERVING)
        if self.device_poller is not None:
            self.device_poller.stop()
        if self.reaper is not None:
            self.reaper.stop()
        if self.http_edge is not None:
            self.http_edge.stop()
        if self.control is not None:
            self.control.close()
        self.server.stop(grace=grace).wait(timeout=grace + 5)


def build_server(config: Config, db: Database, control: ControlSettings | None = None) -> ServerHandle:
    """装配 gRPC 服务并绑定端口；端口写 0 时由内核分配，实际端口在返回值里。

    control 为空时只跑数据面（测试与模组内网部署）；给了配置才装配控制面、
    token 拦截器、HTTP 边缘与会话收尾线程。
    """
    interceptors: list[grpc.ServerInterceptor] = []
    if control is not None:
        interceptors.append(TokenInterceptor(control.client_tokens))
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=config.max_workers),
        interceptors=interceptors,
    )
    # 生成桩没有类型标注（protoc 不为 *_pb2_grpc.py 出 .pyi），这个调用必然是"未类型化"。
    moddata_pb2_grpc.add_ModDataServiceServicer_to_server(  # type: ignore[no-untyped-call]
        ModDataService(db, watch_poll_ms=config.watch_poll_ms), server
    )

    control_service: ControlService | None = None
    http_edge: HttpEdge | None = None
    reaper: SessionReaper | None = None
    device_poller: DeviceLoginPoller | None = None
    if control is not None:
        control_service = ControlService(db, control)
        control_pb2_grpc.add_ControlServiceServicer_to_server(  # type: ignore[no-untyped-call]
            control_service, server
        )
        http_edge = HttpEdge(control.http_bind, db, control)
        reaper = SessionReaper(db, idle_seconds=control.heartbeat_ttl_s)
        device_poller = DeviceLoginPoller(db, control_service.casdoor)

    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set(SERVICE_NAME, health_pb2.HealthCheckResponse.SERVING)
    if control is not None:
        health_servicer.set(CONTROL_SERVICE_NAME, health_pb2.HealthCheckResponse.SERVING)

    services = [
        SERVICE_NAME,
        health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,
        reflection.SERVICE_NAME,
    ]
    if control is not None:
        services.append(CONTROL_SERVICE_NAME)
    reflection.enable_server_reflection(tuple(services), server)

    host, port = config.bind_host_port
    bound = server.add_insecure_port(f"{host}:{port}")
    if not bound:
        raise RuntimeError(f"无法绑定 {config.bind}：端口已被占用或地址不可用")
    return ServerHandle(
        server=server,
        port=bound,
        health_servicer=health_servicer,
        control=control_service,
        http_edge=http_edge,
        reaper=reaper,
        device_poller=device_poller,
    )


def serve(config: Config) -> int:
    """跑服务直到收到 SIGINT / SIGTERM。"""
    control = ControlSettings.resolve()
    db = Database(config.db_file)
    db.open()
    handle = build_server(config, db, control)
    handle.server.start()
    host, _ = config.bind_host_port
    LOGGER.info("CCNR-Data 已监听 %s:%d（数据库：%s）", host, handle.port, db.path)
    if handle.http_edge is not None:
        handle.http_edge.start()
        LOGGER.info("HTTP 边缘已监听 %s", control.http_bind)
    if handle.reaper is not None:
        handle.reaper.start()
    if handle.device_poller is not None:
        handle.device_poller.start()

    retention = RetentionWorker(db, RetentionPolicy.from_config(config, control))
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
