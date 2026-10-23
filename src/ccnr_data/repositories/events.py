# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""对局事件流水。"""

from __future__ import annotations

from sqlalchemy import insert
from sqlalchemy.orm import Session

from ccnr_data.models import MatchEvent
from ccnr_data.repositories._common import PURGE_BATCH, inserted_id, purge_before, table_of

__all__ = ["insert_match_event", "purge_events_before"]


def insert_match_event(
    session: Session,
    *,
    request_id: str,
    server_id: str,
    kind: str,
    match_id: str,
    phase_id: str,
    previous_phase_id: str,
    definition_id: str,
    actor_uuid: str,
    target_uuid: str,
    payload_json: str,
    occurred_at: int,
    created_at: int,
) -> int:
    table = table_of(MatchEvent)
    result = session.execute(
        insert(table).values(
            request_id=request_id,
            server_id=server_id,
            kind=kind,
            match_id=match_id,
            phase_id=phase_id,
            previous_phase_id=previous_phase_id,
            definition_id=definition_id,
            actor_uuid=actor_uuid,
            target_uuid=target_uuid,
            payload_json=payload_json,
            occurred_at=occurred_at,
            created_at=created_at,
        )
    )
    return inserted_id(result)


def purge_events_before(session: Session, cutoff_ms: int, *, limit: int = PURGE_BATCH) -> int:
    """删除 occurred_at 早于 cutoff 的事件流水。"""
    return purge_before(
        session,
        table_of(MatchEvent),
        id_column="id",
        time_column="occurred_at",
        cutoff_ms=cutoff_ms,
        limit=limit,
    )
