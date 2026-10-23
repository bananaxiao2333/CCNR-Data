#!/usr/bin/env bash
# 门禁：业务代码不得出现裸 SQL / 手写 DDL。
# 允许的唯一例外是 db.py 里的连接级 PRAGMA 与 BEGIN IMMEDIATE。
set -euo pipefail
cd "$(dirname "$0")/.."

hits=$(grep -rnE 'import sqlite3|from sqlite3|exec_driver_sql|executescript\(|\btext\(|CREATE TABLE|DROP TABLE|ALTER TABLE' \
    src/ccnr_data --include='*.py' | grep -v '^src/ccnr_data/db.py:' || true)

if [ -n "$hits" ]; then
    echo "❌ 业务代码出现裸 SQL / 手写 DDL（只允许 db.py 的 PRAGMA/BEGIN IMMEDIATE）：" >&2
    echo "$hits" >&2
    exit 1
fi

echo "✅ 无裸 SQL（db.py 的 PRAGMA / BEGIN IMMEDIATE 例外）"
