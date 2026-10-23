# 0002. 持久化改用 SQLAlchemy 2.0 + Alembic，禁止裸 SQL

- 状态：已接受
- 日期：2026-10-24
- 相关：[docs/03](../03-数据模型.md)、[docs/01](../01-工程规范.md)

## 背景

当前数据层是 `schema.sql` + `repo.py` 里 17 处手写 SQL + `db.py` 里的 `schema_meta`
版本校验。它跑得很好，但：

- 新增控制面要加 5 张表、十几个查询，手写 SQL 的重复与漂移风险快速上升；
- schema 没有迁移台阶，加列只能人工改库；
- 另一个仓库（ccnr_adm）已经用 SQLAlchemy 2.0 + Alembic，两边风格分裂；
- 类型检查（mypy strict）对 `sqlite3.Row` 的列名没有保护，拼错只会在运行时炸。

## 决策

1. 全部表用 SQLAlchemy 2.0 声明式模型（`src/ccnr_data/models.py`），业务代码禁止裸 SQL。
2. 数据访问收敛到 `src/ccnr_data/repositories/`，函数只接收 `Session`，不 commit。
3. schema 由 Alembic 管理：`alembic/versions/0001_baseline.py` 复刻现有 10 张表，
   `0002_control_plane.py` 加控制面 5 张表；`schema.sql` 与 `schema_meta` 删除。
4. 启动时校验 `alembic_version` 是否等于 head，不一致拒绝启动（保持原有严格性）。
5. **Engine 用同步 `create_engine`**：gRPC handler 是同步线程池，异步 SQLAlchemy 需要
   把整个服务改成 `grpc.aio`，属于另一次重写。
6. 只有两处允许原生命令，且集中在 `db.py`：连接级 PRAGMA、写事务的 `BEGIN IMMEDIATE`。
   门禁 `scripts/check-no-raw-sql.sh` 保证其它地方不出现 `sqlite3` / `exec_driver_sql` / `text()`。

## 后果

### 正面

- 表结构与查询有类型、有单一来源；加列必须走迁移；
- 与 ccnr_adm 的工程形态一致，迁移与测试经验可以复用；
- 未来换 PostgreSQL 只需换 URL 与少量方言处理。

### 负面 / 代价

- 一次性改造 `repo.py` / `service.py` / `db.py`，回归风险集中在现有 7 组测试；
- ORM 的属性访问替换了 `row["col"]`，service 层要跟着改；
- Alembic 引入 `alembic_version` 表，旧库必须走一次 `db-adopt`；
- 同步 Session 在线程池里每 RPC 一个连接，SQLite 下仍是「多读一写」，性能与现在同级。

## 备选方案

| 方案 | 为什么不选 |
| --- | --- |
| 继续手写 SQL，只加迁移脚本 | 新表/新查询会继续复制粘贴，类型仍无保护 |
| SQLAlchemy Core（Table）而非 ORM | 能用，但与 bot 的 ORM 风格不一致，模型复用差 |
| 异步 SQLAlchemy + `grpc.aio` | 收益是并发模型，代价是全部 RPC 与测试重写；当前 QPS 不需要 |
| 保留 `schema.sql` 双轨 | 两个 schema 来源必然漂移 |

## 何时重新评估

- 单实例 QPS 逼近 SQLite 写锁上限，需要 PostgreSQL 或异步 IO；
- 控制面独立部署、需要连接池与多副本；
- SQLAlchemy 版本出现破坏性变更且 Alembic 迁移成本过高。
