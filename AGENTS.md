# AGENTS.md · 在本仓库工作的硬性约定

面向在本仓库里改代码的 agent 与人。**规范全文见 [docs/01-工程规范](docs/01-工程规范.md)**，这里只列最容易踩的。

## 命令

```bash
uv sync
uv run python scripts/gen_proto.py     # 改了 proto 必须跑
./scripts/check.sh                     # 全部提交前必须通过
uv run pytest -x -q                    # 快速迭代时
uv run python scripts/loadtest.py      # 容量/性能有疑问时
```

`uv` 是唯一依赖入口。**不要**用 `pip install`、不要手建虚拟环境。

## 提交前必须过

`./scripts/check.sh` 七关全绿。CI 跑的是同一份脚本，本地跑不过 CI 也过不了。

## 禁止

| 禁止 | 说明 |
|---|---|
| **占位代码 / 假实现** | 不写 `pass`、不写返回假数据的桩、不写"以后再实现"。功能没做完就不要加这个 RPC / 这个字段 / 这个配置项 |
| 未使用的字段、参数、配置项 | 是"以后可能要用"的假需求 |
| 手改 `src/moddata/` | 生成物。门禁第 6 关会检测漂移 |
| 测试里 mock 序列化 / 事务 / 状态码 | 被 mock 掉的正是最容易错的一层。一律走真实 gRPC 通道 |
| 在 RPC 里直接 `context.abort` | 状态码只在 `errors.py` 定义、只在 `service._handle` 翻译 |
| 静默钳制越界配置 | 越界一律启动失败 |
| 不经 `validation.py` 直接用请求字段 | 调用方在主机边界之外 |

## 改东西时

- **加索引前先回答"哪条查询走它"**。答不上来就是给每次写入加税；本项目已经因为这个删过两条索引。
- **改 schema 加列**：`CREATE TABLE IF NOT EXISTS` 不会给已存在的表补列，必须写迁移（见 [docs/03](docs/03-数据模型.md) §6）。
- **改 proto**：先读 [docs/02](docs/02-协议契约.md) §7 的兼容性清单，再跑生成脚本。
- **动容量相关的表**（`match_events` / `change_log` / `audit_log` / `idempotency`）：改完跑一次 `scripts/loadtest.py`，把新的稳态数字更新到 [docs/05](docs/05-部署与运维.md) §4。
- **刻意让步**留痕：`# ponytail: <天花板>，<什么时候升级>`。

## 与 CCNR-RP 的关系

本仓库**不修改** CCNR-RP。模组端的接入点在 [docs/04](docs/04-对接说明.md) §2，等级显示迁移在 §3——两份清单都带 `文件:行`，是只读审计的结果，改模组时按它对照。

## 最容易犯的错

1. **每次重试都新生成 `request_id`** —— 幂等就失效了，重试变重复落账。键必须标识*一次意图*。
2. **让本服务去算等级** —— 曲线属于模组。算两遍必然对不上。
3. **给事件写审计行** —— 实测会让稳态体积从 3.2 GiB 涨到 36.5 GiB。`match_events` 本身就是记录。
4. **把 `idempotency` 的保留窗口调得太短** —— 迟到的重放会被当成新请求再执行一次。
