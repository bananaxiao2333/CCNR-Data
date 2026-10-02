#!/usr/bin/env python
# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""压测 + 容量预估。

在**本进程内**拉起一台真实服务（真实 gRPC 回环 + 真实 SQLite），按模组的上报形状
打流量，测出：

  * 单发延迟分位（p50 / p95 / p99）
  * 并发吞吐（ops/s）
  * 每行数据的实际占用（含索引），据此推算长期容量

用法：
    uv run python scripts/loadtest.py
    uv run python scripts/loadtest.py --players 30 --events-per-player 200 --rounds 48
    uv run python scripts/loadtest.py --db-file var/loadtest.db     # 保留库自己查看

口径说明（与 CCNN-RP 的真实调用一一对应）：
    事件 = EventManager 的一个生命周期节点（阶段推进/事件触发/结局/阵亡/击杀/部署…）
    结算 = ExperienceService.settleUser() 的一次 SettleSummary
    经验 = /rp xp add 这类零星增量
    读档 = GetPlayer（等级显示取数）
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import grpc

from ccnr_data.config import Config
from ccnr_data.db import Database
from ccnr_data.server import build_server, configure_logging
from moddata.v1 import moddata_pb2, moddata_pb2_grpc

SERVER_ID = "loadtest"
MATCH_ID = "match-loadtest"
KIND = moddata_pb2.EventKind

#: 一局里事件种类按真实分布抽样（阶段推进与事件触发最频繁）。
KIND_MIX = (
    KIND.EVENT_KIND_PHASE_ADVANCED,
    KIND.EVENT_KIND_CONFIG_EVENT_TRIGGERED,
    KIND.EVENT_KIND_CHARACTER_DEPLOYED,
    KIND.EVENT_KIND_CHARACTER_KILL,
    KIND.EVENT_KIND_CHARACTER_DEATH,
    KIND.EVENT_KIND_CHARACTER_DEPLOYED,
    KIND.EVENT_KIND_EVENT_ENDED,
)

TABLES = (
    "players",
    "role_overrides",
    "server_configs",
    "settlements",
    "settlement_lines",
    "match_events",
    "idempotency",
    "audit_log",
    "change_log",
)

#: 每个写入 RPC 固定产生 1 行审计 + 1 行变更流（见 service._record_write）。
ROWS_PER_APPLY = 2
ROWS_PER_EVENT = 1
ROWS_PER_SETTLEMENT = 1

MS_PER_DAY = 24 * 60 * 60 * 1000


# --------------------------------------------------------------------------- 工具


def rid() -> str:
    return f"req-{uuid.uuid4().hex}"


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def human_bytes(size: float) -> str:
    if size < 1024:
        return f"{size:.0f} B"
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        size /= 1024
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TiB"


@dataclass
class Latencies:
    """一次压测的延迟样本。"""

    name: str
    samples: list[float] = field(default_factory=list)
    elapsed: float = 0.0

    def add(self, seconds: float) -> None:
        self.samples.append(seconds * 1000)

    def add_all(self, millis: list[float]) -> None:
        self.samples.extend(millis)

    def report(self) -> str:
        if not self.samples:
            return f"  {self.name:<18} 无样本"
        throughput = f"{len(self.samples) / self.elapsed:>9.0f} ops/s" if self.elapsed > 0 else " " * 15
        return (
            f"  {self.name:<18} n={len(self.samples):<7} {throughput}  "
            f"p50={percentile(self.samples, 50):>7.2f}ms  "
            f"p95={percentile(self.samples, 95):>7.2f}ms  "
            f"p99={percentile(self.samples, 99):>7.2f}ms  "
            f"max={max(self.samples):>8.2f}ms"
        )


class ChannelPool:
    """每个工作线程一条 channel：共享 channel 会掩盖服务端的排队行为。"""

    def __init__(self, target: str, size: int) -> None:
        self._channels = [grpc.insecure_channel(target) for _ in range(size)]
        self._stubs = [
            moddata_pb2_grpc.ModDataServiceStub(channel)  # type: ignore[no-untyped-call]
            for channel in self._channels
        ]
        for channel in self._channels:
            grpc.channel_ready_future(channel).result(timeout=10)

    def stub(self, index: int) -> moddata_pb2_grpc.ModDataServiceStub:
        return self._stubs[index % len(self._stubs)]

    def close(self) -> None:
        for channel in self._channels:
            channel.close()


# --------------------------------------------------------------------------- 请求形状


def make_event(player: str, index: int) -> moddata_pb2.RecordEventRequest:
    kind = KIND_MIX[index % len(KIND_MIX)]
    request = moddata_pb2.RecordEventRequest(
        request_id=rid(),
        server_id=SERVER_ID,
        kind=kind,
        match_id=MATCH_ID,
        phase_id="phase_2" if kind == KIND.EVENT_KIND_PHASE_ADVANCED else "",
        previous_phase_id="phase_1" if kind == KIND.EVENT_KIND_PHASE_ADVANCED else "",
        definition_id="event_supply_drop" if kind == KIND.EVENT_KIND_CONFIG_EVENT_TRIGGERED else "",
        actor_uuid=player
        if kind in (KIND.EVENT_KIND_CHARACTER_KILL, KIND.EVENT_KIND_CHARACTER_DEATH)
        else "",
        target_uuid=player if kind == KIND.EVENT_KIND_CHARACTER_DEPLOYED else "",
    )
    if kind == KIND.EVENT_KIND_CHARACTER_KILL:
        request.payload_json = '{"victimType":"player","victimRelation":"hostile","victimName":"Bravo"}'
    return request


def make_settlement(player: str, lines: int) -> moddata_pb2.RecordSettlementRequest:
    """按 SettleSummary 形状造：gain 恒等于明细合计。"""
    entries = [(f"rule_{i}", f"结算规则 {i}", (i + 1) * 3) for i in range(lines)]
    total = sum(value for _, _, value in entries)
    request = moddata_pb2.RecordSettlementRequest(
        request_id=rid(),
        server_id=SERVER_ID,
        player_uuid=player,
        match_id=MATCH_ID,
        reason="round_end",
        xp_before=0,
        xp_after=total,
        level_before=0,
        level_after=3,
        gain=total,
        username="Bravo",
    )
    for rule_id, title, value in entries:
        request.lines.add(rule_id=rule_id, title=title, value=value)
    return request


def make_apply(player: str, delta: int) -> moddata_pb2.ApplyExperienceRequest:
    return moddata_pb2.ApplyExperienceRequest(
        request_id=rid(),
        player_uuid=player,
        server_id=SERVER_ID,
        delta=delta,
        reason="manual:loadtest",
        level=4,
    )


# --------------------------------------------------------------------------- 压测


def bench_events(pool: ChannelPool, players: list[str], total: int, workers: int) -> tuple[Latencies, float]:
    latencies = Latencies("事件 RecordEvent")
    per_worker = max(1, total // workers)
    lock = threading.Lock()

    def work(worker: int) -> None:
        stub = pool.stub(worker)
        local: list[float] = []
        for index in range(per_worker):
            request = make_event(players[worker % len(players)], worker * per_worker + index)
            start = time.perf_counter()
            stub.RecordEvent(request)
            local.append((time.perf_counter() - start) * 1000)
        with lock:
            latencies.add_all(local)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(work, range(workers)))
    return latencies, time.perf_counter() - started


def bench_settlements(
    pool: ChannelPool, players: list[str], total: int, workers: int, lines: int
) -> tuple[Latencies, float]:
    latencies = Latencies("结算 RecordSettlement")
    per_worker = max(1, total // workers)
    lock = threading.Lock()

    def work(worker: int) -> None:
        stub = pool.stub(worker)
        local: list[float] = []
        for _ in range(per_worker):
            request = make_settlement(players[worker % len(players)], lines)
            start = time.perf_counter()
            stub.RecordSettlement(request)
            local.append((time.perf_counter() - start) * 1000)
        with lock:
            latencies.add_all(local)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(work, range(workers)))
    return latencies, time.perf_counter() - started


def bench_apply(pool: ChannelPool, players: list[str], total: int, workers: int) -> tuple[Latencies, float]:
    latencies = Latencies("经验 ApplyXP")
    per_worker = max(1, total // workers)
    lock = threading.Lock()

    def work(worker: int) -> None:
        stub = pool.stub(worker)
        local: list[float] = []
        for _ in range(per_worker):
            request = make_apply(players[worker % len(players)], 7)
            start = time.perf_counter()
            stub.ApplyExperience(request)
            local.append((time.perf_counter() - start) * 1000)
        with lock:
            latencies.add_all(local)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(work, range(workers)))
    return latencies, time.perf_counter() - started


def bench_get_player(pool: ChannelPool, player: str, rounds: int, workers: int) -> tuple[Latencies, float]:
    """读档是链路上唯一的热路径（等级显示每次都要取），单独测。

    并发读走同一批 channel；SQLite 在 WAL 下允许多读一写，这里验证它确实不串行。
    """
    latencies = Latencies("读档 GetPlayer")
    per_worker = max(1, rounds // workers)
    lock = threading.Lock()
    request = moddata_pb2.GetPlayerRequest(player_uuid=player, server_id=SERVER_ID)

    def work(worker: int) -> None:
        stub = pool.stub(worker)
        local: list[float] = []
        for _ in range(per_worker):
            start = time.perf_counter()
            stub.GetPlayer(request)
            local.append((time.perf_counter() - start) * 1000)
        with lock:
            latencies.add_all(local)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(work, range(workers)))
    return latencies, time.perf_counter() - started


# --------------------------------------------------------------------------- 容量观测


def db_bytes(db: Database) -> int:
    """库的逻辑大小（页数 × 页大小），含 WAL 里尚未 checkpoint 的部分。"""
    conn = db.connection()
    pages = int(conn.execute("PRAGMA page_count").fetchone()[0])
    page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    return pages * page_size


def table_rows(db: Database) -> dict[str, int]:
    conn = db.connection()
    return {
        table: int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])  # noqa: S608
        for table in TABLES
    }


def space_breakdown(db: Database) -> list[tuple[str, int]]:
    """按表/索引列空间占用（dbstat 虚拟表）。用来回答"涨的到底是哪一部分"。

    dbstat 需要 SQLite 编译时带 ENABLE_DBSTAT_VTAB；缺失时返回空表，不影响其它报告。
    """
    try:
        rows = (
            db.connection()
            .execute("SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name ORDER BY bytes DESC")
            .fetchall()
        )
    except sqlite3.OperationalError:
        return []
    return [(str(r["name"]), int(r["bytes"])) for r in rows]


def sqlite_version(db: Database) -> str:
    return str(db.connection().execute("SELECT sqlite_version() AS v").fetchone()["v"])


# --------------------------------------------------------------------------- 主流程


def main() -> int:  # noqa: PLR0915 - 压测主流程，展开写比拆成回调更好读
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--players", type=int, default=30, help="一局玩家数（默认 30）")
    parser.add_argument("--rounds", type=int, default=48, help="24 小时内的局数（默认 48 = 30 分钟一局）")
    parser.add_argument("--events-per-player", type=int, default=200, help="每玩家每局上报事件数（默认 200）")
    parser.add_argument("--settlement-lines", type=int, default=6, help="一次结算携带的明细条数（默认 6）")
    parser.add_argument("--workers", type=int, default=16, help="并发客户端数（默认 16）")
    parser.add_argument("--bench-events", type=int, default=20000, help="实际写入的事件条数（默认 20000）")
    parser.add_argument("--db-file", default="", help="压测库路径（默认临时目录，跑完删除）")
    args = parser.parse_args()

    tmpdir: tempfile.TemporaryDirectory[str] | None = None
    if args.db_file:
        db_path = Path(args.db_file)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)
    else:
        tmpdir = tempfile.TemporaryDirectory(prefix="ccnr-data-loadtest-")
        db_path = Path(tmpdir.name) / "loadtest.db"

    configure_logging("ERROR")

    config = Config.resolve(
        db_file=str(db_path),
        bind="127.0.0.1:0",
        watch_poll_ms=500,
        max_workers=args.workers + 4,
        # 压测数据是合成的（结算的 xp_before 对不上库里的值），
        # 一致性告警在这个脚本里只是噪音，真正的一致性验证在 pytest 里。
        log_level="ERROR",
    )
    db = Database(db_path)
    db.open()
    handle = build_server(config, db)
    handle.server.start()
    pool = ChannelPool(f"127.0.0.1:{handle.port}", args.workers)

    events_per_round = args.players * args.events_per_player
    events_per_day = args.rounds * events_per_round
    settles_per_day = args.rounds * args.players

    print("=" * 108)
    print(
        f"CCNR-Data 压测 · gRPC 127.0.0.1:{handle.port} · SQLite {sqlite_version(db)} · 并发 {args.workers}"
    )
    print(f"库文件：{db_path}")
    print("=" * 108)
    print("\n【场景】")
    print(
        f"  一局：{args.players} 玩家 × 每玩家 {args.events_per_player} 条事件 = {events_per_round:,} 条事件/局"
    )
    print(
        f"  一天：{args.rounds} 局（每局 30 分钟） → 事件 {events_per_day:,} 条/天，"
        f"结算 {settles_per_day:,} 次/天"
    )

    players = [str(uuid.uuid4()) for _ in range(args.players)]

    # 预热：先建好玩家档案，别把首次写入的开销算进基线。
    warm = pool.stub(0)
    for player in players:
        warm.ApplyExperience(make_apply(player, 0))

    print("\n【延迟】单发（并发=1，看真实往返 + 落盘成本）")
    single_read = Latencies("读档 GetPlayer")
    for _ in range(300):
        start = time.perf_counter()
        warm.GetPlayer(moddata_pb2.GetPlayerRequest(player_uuid=players[0], server_id=SERVER_ID))
        single_read.add(time.perf_counter() - start)
    print(single_read.report())

    single_event = Latencies("事件 RecordEvent")
    for index in range(300):
        start = time.perf_counter()
        warm.RecordEvent(make_event(players[index % len(players)], index))
        single_event.add(time.perf_counter() - start)
    print(single_event.report())

    single_settle = Latencies("结算 RecordSettlement")
    for _ in range(200):
        start = time.perf_counter()
        warm.RecordSettlement(make_settlement(players[0], args.settlement_lines))
        single_settle.add(time.perf_counter() - start)
    print(single_settle.report())

    print("\n【吞吐】并发（看服务端在压力下的分位）")
    read_lat, read_elapsed = bench_get_player(pool, players[0], 4000, args.workers)
    read_lat.elapsed = read_elapsed
    print(read_lat.report())

    before_bytes = db_bytes(db)
    before_rows = table_rows(db)

    event_lat, event_elapsed = bench_events(pool, players, args.bench_events, args.workers)
    event_lat.elapsed = event_elapsed
    print(event_lat.report())

    settle_lat, settle_elapsed = bench_settlements(
        pool, players, args.players * 20, args.workers, args.settlement_lines
    )
    settle_lat.elapsed = settle_elapsed
    print(settle_lat.report())

    apply_lat, apply_elapsed = bench_apply(pool, players, args.players * 40, args.workers)
    apply_lat.elapsed = apply_elapsed
    print(apply_lat.report())

    # 让 WAL 落盘后再量增长，否则会漏掉还在 WAL 里的页。
    # 必须在自动提交下跑：checkpoint 不能在已打开的写事务里执行。
    checkpoint = db.connection().execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if checkpoint and int(checkpoint[0]) != 0:
        print(f"  （WAL checkpoint 未完成：busy={int(checkpoint[0])}，测量值略偏小）")
    grown = db_bytes(db) - before_bytes
    after_rows = table_rows(db)

    written_events = after_rows["match_events"] - before_rows["match_events"]
    written_settles = after_rows["settlements"] - before_rows["settlements"]
    written_lines = after_rows["settlement_lines"] - before_rows["settlement_lines"]
    written_changes = after_rows["change_log"] - before_rows["change_log"]
    written_audit = after_rows["audit_log"] - before_rows["audit_log"]
    written_idem = after_rows["idempotency"] - before_rows["idempotency"]
    written_rows = (
        written_events + written_settles + written_lines + written_changes + written_audit + written_idem
    )
    bytes_per_row = grown / written_rows if written_rows else 0.0

    print("\n【单行成本】实测（库增长 ÷ 写入行数，含全部索引）")
    print(
        f"  事件 {written_events:,} 行 · 结算 {written_settles:,} 行 · 明细 {written_lines:,} 行 · "
        f"变更流 {written_changes:,} 行 · 审计 {written_audit:,} 行 · 幂等键 {written_idem:,} 行"
    )
    print(f"  共写 {written_rows:,} 行，库增长 {human_bytes(grown)} → {bytes_per_row:.0f} B/行")

    # 一天的行数：
    #   事件 → match_events 1 行 + change_log 1 行（事件不写 audit_log，见 service._record_event）
    #   结算 → settlements 1 行 + settlement_lines N 行 + change_log 1 行 + audit_log 1 行
    event_rows = events_per_day * ROWS_PER_EVENT
    settle_write_rows = settles_per_day * ROWS_PER_SETTLEMENT
    settle_line_rows = settles_per_day * args.settlement_lines
    audit_rows = settles_per_day  # 只有状态变更写审计
    change_rows = events_per_day + settles_per_day
    # 每个写入 RPC 留一行幂等键（默认保留 30 天）。
    idempotency_rows = events_per_day + settles_per_day
    daily_rows = (
        event_rows + settle_write_rows + settle_line_rows + audit_rows + change_rows + idempotency_rows
    )
    daily_bytes = bytes_per_row * daily_rows

    print("\n【空间构成】各表/索引占用（含索引，含尚未复用的空闲页）")
    for name, size in space_breakdown(db):
        share = size / db_bytes(db) * 100 if db_bytes(db) else 0
        print(f"  {name:<44} {human_bytes(size):>10}  {share:>5.1f}%")

    print("\n【容量预估】按实测 B/行外推（不含文件系统碎片）")
    print(f"  每天新增约 {daily_rows:,} 行 → 约 {human_bytes(daily_bytes)}/天")
    print("  不做清理时：")
    for days, label in ((1, "1 天"), (7, "1 周"), (30, "1 月"), (90, "3 月"), (365, "1 年")):
        print(f"    · {label:<5} 累计 ≈ {human_bytes(daily_bytes * days)}")

    print("\n【开启日志轮换后】事件留 30 天 · 变更流留 7 天 · 审计留 365 天（结算是业务记录，永久保留）")
    steady_rows = (
        event_rows * 30 + change_rows * 7 + audit_rows * 365 + (settle_write_rows + settle_line_rows) * 365
    )
    steady_bytes = bytes_per_row * steady_rows
    print(f"  稳态行数 ≈ {steady_rows:,} 行 → 稳态体积 ≈ {human_bytes(steady_bytes)}")
    print("  曲线：前 30 天持续上涨，之后事件层进出平衡（SQLite 空闲页被复用），体积封顶在稳态值。")

    pool.close()
    handle.stop(grace=0)
    db.close()

    if tmpdir is not None:
        if args.db_file:
            print(f"\n压测库保留在：{db_path}")
        else:
            tmpdir.cleanup()
    else:
        print(f"\n压测库保留在：{db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
