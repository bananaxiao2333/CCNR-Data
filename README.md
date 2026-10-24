# CCNR-Data · 统一数据与控制服务

CCNR 服务器集群的 **中枢**：一个 gRPC 服务，同时承担数据面与控制面。

- **数据面**：承接 **CCNR-RP 模组服务端**（Forge 1.20.1，权威端）上报的 **事件** 与 **玩家结算**，
  以及各版本 MC 后端服务器的玩家档案（经验 / 等级 / 角色覆盖）读写与审计；
- **控制面**：Casdoor 身份投影、Velocity 登录准入、会话统计（在线 / 时长 / 登录失败）、给 bot 的查询；
- **Gate 代理集群**（Go）与 **Velocity 插件** 通过 gRPC 接入。

```
玩家客户端 → Velocity + ccnr-control ─┐
                                      ├─ gRPC ─► [本服务] ─► SQL（SQLite / PostgreSQL）
CCNR-RP 模组服务端（权威端）──────────┘
Bot ──────────────────────────────────┘
```

**职责边界**：Gate/Velocity 做数据面动作（连接 / 转服 / 踢人），本服务只做**存储 + 业务规则 + 审计 + 准入决策**；
等级这类游戏内数值由 **模组服务端（权威端）** 计算后上报，本服务**原样持久化**，不重复实现等级曲线；
身份以 **Casdoor** 为准，本服务只存投影，不读 Casdoor 数据库。

## 快速开始

```bash
cd CCNR-Data
uv sync                                                  # 安装依赖（含生成的 protobuf 桩）
uv run python scripts/gen_proto.py                       # 重新生成桩（改动 proto 后必跑）
make db-upgrade                                          # 建表 / 升级到最新 schema
uv run python -m ccnr_data --db var/ccnr-data.db --bind 127.0.0.1:8081
```

另开一个终端跑冒烟（真实 gRPC 往返，非模拟）：

```bash
uv run python scripts/smoke.py --target 127.0.0.1:8081
```

### Docker

```bash
cp .env.example .env          # 填 Casdoor / client tokens（可留空，但控制面不可用）
docker compose up -d --build
```

容器入口会先 `alembic upgrade head` 再启动服务；数据库落在挂载的 `./var`，
gRPC / HTTP 分别映射到宿主机 `127.0.0.1:8081` / `8082`。

## 门禁

一条命令跑全部门禁（CI 与本地同源）：

```bash
./scripts/check.sh
```

| # | 门禁 | 说明 |
|---|------|------|
| 1 | 语法检查 | `python -m compileall` 全量编译 `src` / `tests` / `scripts` |
| 2 | 许可头 | 每个 `.py` 必须含 `SPDX-License-Identifier` 头（与 CCNR 系列一致） |
| 3 | 风格 | `ruff format --check .` |
| 4 | 静态检查 | `ruff check .` |
| 5 | 类型 | `mypy`（strict，生成桩除外） |
| 6 | 桩一致性 | 重新生成 proto 桩，与仓库内文件逐字节比对，有漂移即失败 |
| 7 | 迁移一致性 | `alembic check`（模型与迁移不得漂移） |
| 8 | 无裸 SQL | `scripts/check-no-raw-sql.sh`（`sqlite3` / `exec_driver_sql` / `text()` 只能出现在 `db.py`） |
| 9 | 单元/集成测试 | `pytest`（真实 gRPC 通道往返，无 mock，单测挂死按超时失败） |

CI：`.github/workflows/ci.yml`，push / PR 触发，跑同一套 `scripts/check.sh`。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `CCNR_DATA_DATABASE_URL` | 由 `DB_FILE` 推导 | SQLAlchemy URL；控制面与 Alembic 共用 |
| `CCNR_DATA_DB_FILE` | `var/ccnr-data.db` | SQLite 文件；目录不存在会自动创建 |
| `CCNR_DATA_BIND` | `127.0.0.1:8081` | gRPC 监听地址（`host:port`） |
| `CCNR_DATA_WATCH_POLL_MS` | `500` | `WatchChanges` 轮询间隔，100–5000；越界启动失败，不静默钳制 |
| `CCNR_DATA_MAX_WORKERS` | `16` | gRPC 线程池大小，1–256 |
| `CCNR_DATA_LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR / CRITICAL |
| `CCNR_DATA_EVENT_RETENTION_DAYS` | `30` | 事件流水保留天数，**0 = 永久** |
| `CCNR_DATA_CHANGE_RETENTION_DAYS` | `7` | 变更流保留天数，0 = 永久；订阅方落后超过该窗口会丢事件（会告警） |
| `CCNR_DATA_AUDIT_RETENTION_DAYS` | `365` | 审计日志保留天数，0 = 永久 |
| `CCNR_DATA_IDEMPOTENCY_RETENTION_DAYS` | `30` | 幂等键保留天数，0 = 永久；必须远长于任何重试窗口 |
| `CCNR_DATA_HTTP_BIND` | `127.0.0.1:8082` | 控制面 HTTP 边缘（`/healthz` / `/metrics`） |
| `CCNR_DATA_CLIENT_TOKENS` | 空 = 不鉴权 | JSON `{"proxy":"..."}`，control.v1 的 Bearer token |
| `CCNR_DATA_CASDOOR_ENDPOINT` | 空 | Casdoor 根地址；与 ID / SECRET 同时给或同时留空 |
| `CCNR_DATA_CASDOOR_CLIENT_ID` / `_SECRET` | 空 | Casdoor M2M 凭据 |
| `CCNR_DATA_CASDOOR_ORGANIZATION` | `ccnr` | 用户所属组织 |
| `CCNR_DATA_CASDOOR_TIMEOUT_MS` / `_CACHE_TTL_S` | `2000` / `60` | Casdoor 超时与用户缓存 |
| `CCNR_DATA_AUTH_FAIL_MODE` | `deny` | Casdoor 故障时冷用户策略：`deny` / `allow` |
| `CCNR_DATA_ROLE_MAP` | 空 | JSON，Casdoor 角色名 → 内部角色 |
| `CCNR_DATA_HEARTBEAT_TTL_S` | `180` | 在线判定窗口与会话收尾阈值 |
| `CCNR_DATA_PROXY_EVENT_RETENTION_DAYS` | `30` | 代理事件轮换，0 = 永久 |
| `CCNR_DATA_SESSION_RETENTION_DAYS` | `365` | 已结束会话轮换，0 = 永久 |

命令行参数优先于环境变量（`--event-retention-days` 等同名参数），全量清单见 `uv run python -m ccnr_data --help`。

## 压测与容量

```bash
# 一局 30 人 × 每人 200 条事件、24 小时 48 局
uv run python scripts/loadtest.py
```

在 16 并发、SQLite 3.53 下的实测（macOS / Apple Silicon，单机同进程回环）：

| 指标 | 结果 |
|---|---|
| 单发延迟（并发=1） | 读档 p50 0.15ms · 事件 p50 0.19ms · 结算 p50 0.22ms |
| 并发吞吐 | 读档 6.2k ops/s · 事件 2.2k ops/s · 结算 1.6k ops/s |
| 单行成本 | 233 B/行（含全部索引，实测增量） |
| 场景日增行数 | 878,400 行/天 → 195 MiB/天 |
| 不清理 | 1 月 5.7 GiB · 1 年 69.5 GiB |
| **开启轮换后稳态** | **≈ 3.2 GiB 封顶**（事件 30 天 / 变更流 7 天 / 审计 365 天 / 幂等键 30 天） |

真实负载约 3–30 事件/秒，上面 2,200 ops/s 的余量在两个数量级以上；瓶颈不在吞吐，在**保留策略**。细节与推导见 [docs/05](docs/05-部署与运维.md) §4。

## 目录

| 路径 | 内容 |
|---|---|
| `proto/moddata/v1/moddata.proto` | **协议契约**（唯一权威，见 [docs/02](docs/02-协议契约.md)） |
| `src/ccnr_data/models.py` | SQLAlchemy 2.0 模型（全部表） |
| `src/ccnr_data/repositories/` | 数据访问（只收 `Session`，不写业务规则、不写裸 SQL） |
| `src/ccnr_data/control/` | `control.v1` 实现：准入、身份、Casdoor、HTTP 边缘 |
| `src/ccnr_data/` | 服务实现 |
| `alembic/` | 数据库迁移（`0001_baseline` … `0006_device_login_expected_account`） |
| `src/moddata/`、`src/control/` | protobuf / gRPC 生成桩（**禁止手改**，由 `scripts/gen_proto.py` 产出） |
| `tests/` | 自动化测试 |
| `scripts/` | 桩生成（`gen_proto.py`）、冒烟（`smoke.py`）、压测（`loadtest.py`）、门禁（`check.sh`） |
| `docs/` | 工程文档 |

## 文档

| 文档 | 内容 |
|---|---|
| [docs/00-总览.md](docs/00-总览.md) | 架构定位、组件分工、数据流 |
| [docs/01-工程规范.md](docs/01-工程规范.md) | 分层、命名、门禁、测试、文档规范 |
| [docs/02-协议契约.md](docs/02-协议契约.md) | RPC 清单、字段编号规则、错误码、兼容性 |
| [docs/03-数据模型.md](docs/03-数据模型.md) | 表结构、不变量、索引、迁移 |
| [docs/04-对接说明.md](docs/04-对接说明.md) | Gate 配置、模组端接入（等级显示迁移） |
| [docs/05-部署与运维.md](docs/05-部署与运维.md) | 部署、健康检查、备份、容量与压测、排障 |
| [docs/06-控制面与统计.md](docs/06-控制面与统计.md) | 准入策略、身份投影、统计口径、失败模式 |
| [docs/07-发布.md](docs/07-发布.md) | 版本、打包、Docker、tag 发布 |
| [docs/adr/](docs/adr/README.md) | 架构决策记录（控制面 / SQLAlchemy / Velocity 插件） |
| [AGENTS.md](AGENTS.md) | 在这个仓库里工作的硬性约定 |

## License

MIT —— 见 [LICENSE](LICENSE)。
