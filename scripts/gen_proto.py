#!/usr/bin/env python
# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""生成（或校验）protobuf / gRPC Python 桩代码。

用法：
    python scripts/gen_proto.py            # 生成到 src/
    python scripts/gen_proto.py --check    # 生成到临时目录并与仓库内文件比对，漂移则退出码 1

契约与桩的对应关系见 docs/02-协议契约.md：
    proto/moddata/v1/moddata.proto  ->  src/moddata/v1/moddata_pb2.py
                                        src/moddata/v1/moddata_pb2_grpc.py
    proto/control/v1/control.proto  ->  src/control/v1/control_pb2.py
                                        src/control/v1/control_pb2_grpc.py

生成根目录是 src/ 而非 src/ccnr_data/：protoc 按 proto 的文件路径决定 Python 模块路径，
只有把生成根挂到 src/ 才能让产物成为顶层包 `moddata`，从而让 _pb2_grpc.py 内部的
`from moddata.v1 import moddata_pb2` 正常解析（见 docs/02 §4）。
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = ROOT / "proto"
OUT_ROOT = ROOT / "src"

# 生成的顶层包（wheel 打包与 mypy/ruff 排除都按它来）。
GENERATED_PACKAGES = ("moddata", "control")

# 每个生成目录都必须有 __init__.py，否则不是包、无法 import。
INIT_MODULES = ("moddata", "moddata/v1", "control", "control/v1")


def _grpc_tools_include() -> Path:
    """grpcio-tools 自带的 well-known types（google/protobuf/*.proto）所在目录。"""
    import grpc_tools  # noqa: PLC0415  — 仅此脚本需要，不污染运行时依赖

    include = Path(grpc_tools.__file__).resolve().parent / "_proto"
    if not include.is_dir():
        raise SystemExit(f"grpc_tools 内置 proto 目录缺失：{include}")
    return include


def _proto_files() -> list[Path]:
    files = sorted(PROTO_DIR.rglob("*.proto"))
    if not files:
        raise SystemExit(f"未找到任何 .proto：{PROTO_DIR}")
    return files


def generate(out_root: Path) -> None:
    """把 proto/moddata/v1/*.proto 生成到 out_root 下。"""
    out_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{PROTO_DIR}",
        f"-I{_grpc_tools_include()}",
        f"--python_out={out_root}",
        f"--grpc_python_out={out_root}",
        f"--pyi_out={out_root}",
        *(str(p) for p in _proto_files()),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)

    # protoc 会顺带生成中间目录，但不会补 __init__.py。
    for rel in INIT_MODULES:
        init = out_root / rel / "__init__.py"
        init.parent.mkdir(parents=True, exist_ok=True)
        init.touch(exist_ok=True)


def _generated_paths(out_root: Path) -> list[Path]:
    paths: list[Path] = []
    for package in GENERATED_PACKAGES:
        paths.extend((out_root / package).rglob("*.py"))
    return sorted(paths)


def check() -> int:
    """生成到临时目录，与仓库内产物逐文件比对；有差异即返回 1。"""
    repo_paths = _generated_paths(OUT_ROOT)
    if not repo_paths:
        print(f"[gen_proto] 仓库内没有生成产物：{OUT_ROOT}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="ccnr-data-proto-") as tmp:
        fresh_root = Path(tmp) / "src"
        generate(fresh_root)
        fresh_paths = _generated_paths(fresh_root)

        drift: list[str] = []
        repo_rel = {p.relative_to(OUT_ROOT) for p in repo_paths}
        fresh_rel = {p.relative_to(fresh_root) for p in fresh_paths}
        for rel in sorted(repo_rel ^ fresh_rel):
            drift.append(f"{rel} (只存在于一方)")
        for rel in sorted(repo_rel & fresh_rel):
            if not filecmp.cmp(OUT_ROOT / rel, fresh_root / rel, shallow=False):
                drift.append(f"{rel} (内容不同)")

        if drift:
            print(
                "[gen_proto] 生成桩与仓库不一致，请运行 `uv run python scripts/gen_proto.py`：",
                file=sys.stderr,
            )
            for line in drift:
                print(f"  - {line}", file=sys.stderr)
            return 1

    print(f"[gen_proto] 一致，共 {len(repo_paths)} 个生成文件")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="只校验漂移，不写仓库")
    parser.add_argument("--clean", action="store_true", help="先删除已生成的包再生成")
    args = parser.parse_args()

    if args.check:
        return check()

    if args.clean:
        for package in GENERATED_PACKAGES:
            target = OUT_ROOT / package
            if target.exists():
                shutil.rmtree(target)

    generate(OUT_ROOT)
    print(f"[gen_proto] 已生成到 {OUT_ROOT}（{' / '.join(GENERATED_PACKAGES)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
