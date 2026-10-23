# 0004. 用 Casdoor Device Code 做登录证明

- 状态：已接受
- 日期：2026-10-24
- 相关：[0003](0003-velocity-access-and-telemetry.md)、[docs/06](../06-控制面与统计.md)

## 背景

静态身份投影只能证明"某 UUID 曾绑定过某 Casdoor 用户"，不能证明"这次连接就是本人"。
代理又是 offline-mode：任何人把游戏名改成别人的名字，就能复用绑定。CCNR Skin 的
Yggdrasil 要求本地密码，而 OAuth 账号没有密码，走不通。

## 决策

1. 玩家先连 limbo（`auth` 服），插件调 `BeginDeviceLogin` 取 `user_code`；
2. 玩家在 CCNR Pass（Casdoor）登录并授权；
3. `DeviceLoginPoller` 在服务端轮询 token，解析 `owner/preferred_username`，写投影（`source=PASS`）；
4. 插件只认 **这条连接** 的授权结果，通过后才送到 `lobby` 并执行 `AuthorizePlayer`；
5. 设备码 pending/slow_down 是 4xx，但不能计入 Casdoor 熔断。

## 后果

- 好处：不需要第二个密码；skin 退出认证链；每条连接都有 Pass 授权证明。
- 代价：登录多一次浏览器操作；需要 limbo 服；Casdoor 必须启用 Device Code。
- 重新评估：如果 Pass 提供更轻的 OAuth 授权码回传方式，可替换设备码。
