# 0003. Velocity 插件承担准入与会话遥测

- 状态：部分被 [0004](0004-device-code-login.md) 取代（准入改为设备码登录后判定）
- 日期：2026-10-24
- 相关：[docs/06](../06-控制面与统计.md)、[docs/02](../02-协议契约.md)

## 背景

准入与统计都发生在代理层，但代理不能成为第二个「真相源」：

- 登录必须快速给出 allow/deny，不能每次同步等一个远程服务；
- 统计需要会话、转服、断线、登录失败，代理崩溃时不能丢已发生的事件；
- 代理重启、数据库故障、Casdoor 故障都不能把玩家一起拖下水。

## 决策

1. 新写 Velocity 插件 `ccnr-control`（Java 17 / Velocity 3.x），只做两件事：
   **登录准入**与**会话遥测**。
2. 准入：`LoginEvent` 同步查本地缓存；未命中以 1000ms deadline 调
   `control.v1.AuthorizePlayer`；拒绝时用中文 `ComponentResult.denied(message)`。
3. 缓存：按 UUID 缓存决策（默认 60s，TTL 由服务端下发）；连不上服务端时按
   `fail_open`（默认 false = 拒绝）处理，在线玩家不受影响。
4. 遥测：`SESSION_STARTED` / `SERVER_SWITCHED` / `SESSION_ENDED` / `LOGIN_DENIED`，
   心跳只更新 `last_seen_at`（不写事件表）；事件进有界队列，单线程发送 + 指数退避，
   关服 flush，未发完落 `queue.jsonl` 下次重放。
5. 幂等：`request_id = <kind>:<session_id>:<seq>`，重试复用同一条消息。
6. 插件独立成同级 `CCNR-Velocity/`（Java / Gradle，自带门禁），不并入本仓库的 Python 门禁。

## 后果

### 正面

- 代理侧逻辑可单测：缓存、拒绝映射、队列重试都不依赖真实服务器；
- 服务端故障不会放大为「全员掉线」；统计可补发；
- 准入与统计共用一条 gRPC 契约，字段不会漂移。

### 负面 / 代价

- `LoginEvent` 是同步事件，冷路径会阻塞登录线程最多 1s；用缓存把命中率压到绝大多数；
- 多一个 Java 构建链（Gradle + ShadowJar 重定位），CI 时间增加；
- 插件与 Python 服务必须同步升级 proto，靠同仓路径规避漂移。

## 备选方案

| 方案 | 为什么不选 |
| --- | --- |
| 代理直接查 Casdoor | 每次登录打 Casdoor，且拿不到封禁/白名单口径 |
| 先放行、PostLogin 再异步踢 | 玩家会看到「进服又被踢」，体验差且统计口径混乱 |
| 用 HTTP/JSON 而不是 gRPC | 需要第二套契约；gRPC-Java 在模组侧已验证 |
| 遥测走日志采集 | 无法保证幂等与断线补发，统计会缺段 |

## 何时重新评估

- Velocity 提供异步登录事件，或代理侧需要限流/排队；
- 代理多实例需要集中配置分发；
- 事件量增长到需要批量 RPC 或本地聚合。
