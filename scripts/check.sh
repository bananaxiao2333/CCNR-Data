#!/usr/bin/env bash
# CCNR-Data 全部门禁。CI 与本地跑的是同一份，不允许"CI 上另有一套"。
#
# 用法：./scripts/check.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# 统一入口：一律走 uv，不依赖激活的虚拟环境。
run() {
    echo "==> $*"
    uv run "$@"
}

# 1) 语法检查：把所有 .py 编译一遍，挡住语法错与编码问题。
echo "==> 语法检查（compileall）"
uv run python -m compileall -q src tests scripts

# 2) 许可头：每个自有 .py 必须带 SPDX 标识（生成桩除外）。
echo "==> 许可头检查"
missing=$(find src tests scripts -name '*.py' -not -path 'src/moddata/*' -print0 |
    xargs -0 grep -L 'SPDX-License-Identifier' || true)
if [ -n "$missing" ]; then
    echo "以下文件缺少 SPDX-License-Identifier 头：" >&2
    echo "$missing" >&2
    exit 1
fi

# 3) 风格：格式化必须已收敛。
run ruff format --check .

# 4) 静态检查。
run ruff check .

# 5) 类型：strict，生成桩排除在外。
run mypy

# 6) 契约一致性：改动 proto 后必须重新生成并提交，仓库内产物不得漂移。
run python scripts/gen_proto.py --check

# 7) 测试：全部走真实 gRPC 通道，没有 mock。
run pytest

echo "全部门禁通过。"
