-- CCNR-Data · SQLite 模式（v1）
--
-- 约定：
--   * 所有时间列是 UTC epoch 毫秒整数（见 clock.py），迁 PostgreSQL 时对应 BIGINT。
--   * 所有 DDL 必须 IF NOT EXISTS：bootstrap 每次启动都会执行一遍。
--   * 不写 PRAGMA（journal_mode / foreign_keys / busy_timeout 由 db.py 按连接设置）。
--   * AUTOINCREMENT 只用在 change_log.seq 上：它要求"单调且永不复用"，
--     因为模组端会把它当作断线重连的游标。其余主键用普通 INTEGER PRIMARY KEY。

-- 模式版本。单行表，id 恒为 1。
CREATE TABLE IF NOT EXISTS schema_meta (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    version    INTEGER NOT NULL,
    applied_at INTEGER NOT NULL
);

-- 玩家档案主表。经验与等级都由权威端（模组服务端）给出，本服务不重算。
CREATE TABLE IF NOT EXISTS players (
    player_uuid TEXT    NOT NULL,
    server_id   TEXT    NOT NULL,
    username    TEXT    NOT NULL DEFAULT '',
    experience  INTEGER NOT NULL DEFAULT 0,
    level       INTEGER NOT NULL DEFAULT 0,
    version     INTEGER NOT NULL DEFAULT 0,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (player_uuid, server_id)
);
CREATE INDEX IF NOT EXISTS idx_players_server ON players(server_id);

-- 角色覆盖。保留 enabled=0 的行，用来区分"从没给过"与"给过又收回"。
CREATE TABLE IF NOT EXISTS role_overrides (
    player_uuid TEXT    NOT NULL,
    server_id   TEXT    NOT NULL,
    role        TEXT    NOT NULL,
    enabled     INTEGER NOT NULL,
    source      TEXT    NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (player_uuid, server_id, role)
);
CREATE INDEX IF NOT EXISTS idx_role_overrides_player ON role_overrides(player_uuid, server_id);

-- 服务器级策略。
CREATE TABLE IF NOT EXISTS server_configs (
    server_id   TEXT PRIMARY KEY,
    role_policy TEXT    NOT NULL,
    config_json TEXT    NOT NULL DEFAULT '{}',
    version     INTEGER NOT NULL DEFAULT 0,
    updated_at  INTEGER NOT NULL
);

-- 玩家结算头。request_id 唯一 → 重放不会重复落账。
CREATE TABLE IF NOT EXISTS settlements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id   TEXT    NOT NULL UNIQUE,
    server_id    TEXT    NOT NULL,
    player_uuid  TEXT    NOT NULL,
    match_id     TEXT    NOT NULL DEFAULT '',
    reason       TEXT    NOT NULL,
    xp_before    INTEGER NOT NULL,
    xp_after     INTEGER NOT NULL,
    level_before INTEGER NOT NULL,
    level_after  INTEGER NOT NULL,
    gain         INTEGER NOT NULL,
    diverged     INTEGER NOT NULL DEFAULT 0,
    settled_at   INTEGER NOT NULL,
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_settlements_player ON settlements(player_uuid, server_id, id);
CREATE INDEX IF NOT EXISTS idx_settlements_match ON settlements(server_id, match_id, id);

-- 结算明细，对应模组 XpChangeList 的逐条内容。
CREATE TABLE IF NOT EXISTS settlement_lines (
    settlement_id INTEGER NOT NULL REFERENCES settlements(id) ON DELETE CASCADE,
    line_no       INTEGER NOT NULL,
    rule_id       TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    value         INTEGER NOT NULL,
    PRIMARY KEY (settlement_id, line_no)
);

-- 对局事件流水。只追加，不改不删。
CREATE TABLE IF NOT EXISTS match_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id        TEXT    NOT NULL UNIQUE,
    server_id         TEXT    NOT NULL,
    kind              TEXT    NOT NULL,
    match_id          TEXT    NOT NULL DEFAULT '',
    phase_id          TEXT    NOT NULL DEFAULT '',
    previous_phase_id TEXT    NOT NULL DEFAULT '',
    definition_id     TEXT    NOT NULL DEFAULT '',
    actor_uuid        TEXT    NOT NULL DEFAULT '',
    target_uuid       TEXT    NOT NULL DEFAULT '',
    payload_json      TEXT    NOT NULL DEFAULT '{}',
    occurred_at       INTEGER NOT NULL,
    created_at        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_match_events_match ON match_events(server_id, match_id, id);
-- 日志轮换按时间整批删除，必须有时间索引，否则每次清理都是全表扫。
CREATE INDEX IF NOT EXISTS idx_match_events_occurred ON match_events(occurred_at);

-- 幂等表。与业务写入同事务提交，所以"行存在"就等于"业务已生效"。
CREATE TABLE IF NOT EXISTS idempotency (
    request_id    TEXT PRIMARY KEY,
    method        TEXT NOT NULL,
    request_hash  TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at    INTEGER NOT NULL
);

-- 审计日志。每次写入业务数据都同步落一条。
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT NOT NULL,
    request_id  TEXT NOT NULL DEFAULT '',
    before_json TEXT,
    after_json  TEXT,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

-- 变更流。seq 全局单调，WatchChanges 用它做游标。
CREATE TABLE IF NOT EXISTS change_log (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    change_type  TEXT    NOT NULL,
    server_id    TEXT    NOT NULL,
    player_uuid  TEXT    NOT NULL DEFAULT '',
    version      INTEGER NOT NULL,
    payload_json TEXT    NOT NULL DEFAULT '{}',
    occurred_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_change_log_server ON change_log(server_id, seq);
CREATE INDEX IF NOT EXISTS idx_change_log_occurred ON change_log(occurred_at);
