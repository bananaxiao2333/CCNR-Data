# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""结算头与明细。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from ccnr_data.models import Settlement, SettlementLine
from ccnr_data.repositories._common import inserted_id, table_of

__all__ = ["insert_settlement", "insert_settlement_lines", "iter_lines"]


def insert_settlement(
    session: Session,
    *,
    request_id: str,
    server_id: str,
    player_uuid: str,
    match_id: str,
    reason: str,
    xp_before: int,
    xp_after: int,
    level_before: int,
    level_after: int,
    gain: int,
    diverged: bool,
    settled_at: int,
    created_at: int,
) -> int:
    """写入结算头，返回 settlement id。"""
    table = table_of(Settlement)
    result = session.execute(
        insert(table).values(
            request_id=request_id,
            server_id=server_id,
            player_uuid=player_uuid,
            match_id=match_id,
            reason=reason,
            xp_before=xp_before,
            xp_after=xp_after,
            level_before=level_before,
            level_after=level_after,
            gain=gain,
            diverged=1 if diverged else 0,
            settled_at=settled_at,
            created_at=created_at,
        )
    )
    return inserted_id(result)


def insert_settlement_lines(
    session: Session,
    settlement_id: int,
    lines: Sequence[tuple[int, str, str, int]],
) -> None:
    """批量写入结算明细。入参为 (line_no, rule_id, title, value)。"""
    if not lines:
        return
    table = table_of(SettlementLine)
    session.execute(
        insert(table),
        [
            {
                "settlement_id": settlement_id,
                "line_no": no,
                "rule_id": rule_id,
                "title": title,
                "value": value,
            }
            for no, rule_id, title, value in lines
        ],
    )


def iter_lines(session: Session, settlement_id: int) -> list[RowMapping]:
    """读某次结算的明细（测试与排障用）。"""
    table = table_of(SettlementLine)
    return list(
        session.execute(
            select(table).where(table.c.settlement_id == settlement_id).order_by(table.c.line_no)
        ).mappings()
    )
