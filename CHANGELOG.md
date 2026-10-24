# CHANGELOG

## 0.1.0

首个可运行版本：Gate 代理集群背后的统一数据服务，承接 CCNR-RP 模组上报的事件与玩家结算。

### 协议（`proto/moddata/v1/moddata.proto`）

- `ModDataService`：`GetPlayer` / `ApplyExperience` / `RecordSettlement` / `RecordEvent` /
  `SetRoleOverride` / `GetServerConfig` / `UpdateServerConfig` / `WatchChanges`。
- 契约规则：字段编号永不复用、删除必 `reserved`、枚举 0 值必 `UNSPECIFIED`、破坏性变更开新包。
- 与方案草图的差异（`flags` 删除、`RolePolicy` 单枚举替代两个布尔量、`since_seq` 命名、
  事件种类用枚举等）逐条记录在 [docs/02](docs/02-协议契约.md) §5。

### 服务

- 幂等：幂等行与业务行同事务提交，重放原样回放；同键不同载荷报 `FAILED_PRECONDITION`。
- 审计 + 变更流：状态变更（经验/结算/角色/策略）落 `audit_log` 与 `change_log`。
- 信任边界校验：UUID / 标识符字符集 / JSON 对象 / 时间戳窗口 / 明细条数，统一在 `validation.py`。
- 结算一致性：`gain == xp_after - xp_before`、`Σ lines == gain`、无明细时 `gain == 0`。
- 经验漂移：以权威端为准覆盖，同时回报 `xp_diverged` 与 `stored_xp_before`。
- 日志轮换：`match_events` / `change_log` / `audit_log` / `idempotency` 按天清理，
  业务表永不自动清除；后台线程每小时一轮，启动时先补一轮。
- 标准 gRPC 健康检查 + 服务反射；停机先置 `NOT_SERVING` 再 drain。

### 控制面

- 设备码登录区分 `GAME` / `LINK`；`LINK` 批准后写 `account_links`，不写身份投影。
- `BeginDeviceLogin` 支持 `expected_casdoor_user_id`：只允许指定账号完成本次验证，
  轮询与短码批准都会拒绝其他账号；只填用户名时按默认组织补全。
- 新增 `GetAccountLink` / `BindAccountLink` / `DeleteAccountLink`，bot 不再本地存绑定。
- 绑定冲突、重复绑定、账号不一致统一返回 `DENIED` / `INVALID_ARGUMENT`。

### 工程

- 门禁 `scripts/check.sh`：语法检查 / 许可头 / ruff format / ruff check / mypy strict /
  proto 桩一致性 / pytest，本地与 CI 同源。
- 148 项测试，全部走真实 gRPC 通道，无 mock；`pytest-timeout` 让挂死变成失败。
- Dockerfile + compose：入口自动执行 Alembic，数据目录挂载到 `/data`。
- tag 发布工作流：门禁 → `uv build` → GitHub Release 附带 wheel/sdist。
- 工具：`scripts/gen_proto.py`（生成 + 漂移校验）、`scripts/smoke.py`（对外部实例冒烟）、
  `scripts/loadtest.py`（压测 + 容量预估 + `dbstat` 空间分解）。

### 压测结论

场景（24 小时 × 30 分钟一局 × 30 人 × 200 条日志/人）：878,400 行/天、233 B/行、195 MiB/天。

- 不清理：一年 69.5 GiB。
- 开启默认轮换：稳态 ≈ **3.2 GiB 封顶**。
- 吞吐 2,221 事件/秒（真实负载约 3–30/秒），瓶颈不在吞吐而在保留策略。

压测过程中发现并修掉的三处结构性浪费：每事件一条审计行、`idempotency` 永不清理、
两条无人使用的索引。见 [docs/05](docs/05-部署与运维.md) §4.5。
