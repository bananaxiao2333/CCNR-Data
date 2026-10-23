# CCNR-Data · 常用工程命令
# 所有命令经 uv 在项目虚拟环境内执行，无需手动 activate。

.PHONY: help setup run proto db-upgrade db-revision db-adopt fmt lint type test check clean

help: ## 显示可用目标
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## 安装/同步依赖
	uv sync

run: ## 启动 gRPC 服务（地址/数据库走 CCNR_DATA_* 环境变量）
	uv run python -m ccnr_data

proto: ## 重新生成 moddata.v1 / control.v1 桩
	uv run python scripts/gen_proto.py

db-upgrade: ## 应用数据库迁移到最新版本
	uv run alembic upgrade head

db-revision: ## 生成迁移（m="说明"）
	uv run alembic revision --autogenerate -m "$(m)"

db-adopt: ## 旧版（schema_meta v1）库首次接入 Alembic
	uv run python scripts/adopt_legacy_db.py

fmt: ## 自动格式化 + 自动修复 lint
	uv run ruff format .
	uv run ruff check --fix .

lint: ## 门禁：lint + 格式检查（不改文件）
	uv run ruff check .
	uv run ruff format --check .

type: ## 门禁：类型检查
	uv run mypy

test: ## 单元/集成测试
	uv run pytest

check: ## 门禁一把梭（CI 等价）
	./scripts/check.sh

clean: ## 清理缓存产物
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov
