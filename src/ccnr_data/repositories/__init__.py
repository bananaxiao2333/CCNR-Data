# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""数据访问层（SQLAlchemy）。

所有函数接收调用方给的 Session，不 commit：
服务层可以把「幂等行 + 业务行 + 审计行 + 变更流」放进同一个事务，
要么全成要么全不成。
"""

from __future__ import annotations

from ccnr_data.repositories import access, identities, proxy
from ccnr_data.repositories._common import PURGE_BATCH
from ccnr_data.repositories.audit import audit, purge_audit_before
from ccnr_data.repositories.changes import (
    MAX_CHANGE_BATCH,
    append_change,
    fetch_changes,
    oldest_change_seq,
    purge_changes_before,
)
from ccnr_data.repositories.events import insert_match_event, purge_events_before
from ccnr_data.repositories.idempotency import (
    claim_idempotency,
    purge_idempotency_before,
    store_idempotency_response,
)
from ccnr_data.repositories.players import (
    get_player,
    list_roles,
    upsert_player,
    upsert_role_override,
)
from ccnr_data.repositories.server_config import get_server_config, upsert_server_config
from ccnr_data.repositories.settlements import (
    insert_settlement,
    insert_settlement_lines,
    iter_lines,
)

__all__ = [
    "MAX_CHANGE_BATCH",
    "PURGE_BATCH",
    "access",
    "append_change",
    "audit",
    "claim_idempotency",
    "fetch_changes",
    "get_player",
    "get_server_config",
    "identities",
    "insert_match_event",
    "insert_settlement",
    "insert_settlement_lines",
    "iter_lines",
    "list_roles",
    "oldest_change_seq",
    "proxy",
    "purge_audit_before",
    "purge_changes_before",
    "purge_events_before",
    "purge_idempotency_before",
    "store_idempotency_response",
    "upsert_player",
    "upsert_role_override",
    "upsert_server_config",
]
