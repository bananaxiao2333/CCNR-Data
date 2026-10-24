#!/bin/sh
# 容器入口：先把库升到最新 schema，再启动 gRPC 服务。
set -eu

alembic upgrade head
exec python -m ccnr_data
