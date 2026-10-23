# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""baseline：复刻 v1 的 9 张业务表（schema_meta 由 Alembic 取代）。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "players",
        sa.Column("player_uuid", sa.Text(), nullable=False),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("experience", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("player_uuid", "server_id"),
    )
    op.create_index("idx_players_server", "players", ["server_id"])

    op.create_table(
        "role_overrides",
        sa.Column("player_uuid", sa.Text(), nullable=False),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("player_uuid", "server_id", "role"),
    )
    op.create_index("idx_role_overrides_player", "role_overrides", ["player_uuid", "server_id"])

    op.create_table(
        "server_configs",
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("role_policy", sa.Text(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("server_id"),
    )

    op.create_table(
        "settlements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("player_uuid", sa.Text(), nullable=False),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("xp_before", sa.Integer(), nullable=False),
        sa.Column("xp_after", sa.Integer(), nullable=False),
        sa.Column("level_before", sa.Integer(), nullable=False),
        sa.Column("level_after", sa.Integer(), nullable=False),
        sa.Column("gain", sa.Integer(), nullable=False),
        sa.Column("diverged", sa.Integer(), nullable=False),
        sa.Column("settled_at", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("idx_settlements_player", "settlements", ["player_uuid", "server_id", "id"])
    op.create_index("idx_settlements_match", "settlements", ["server_id", "match_id", "id"])

    op.create_table(
        "settlement_lines",
        sa.Column("settlement_id", sa.Integer(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["settlement_id"], ["settlements.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("settlement_id", "line_no"),
    )

    op.create_table(
        "match_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("phase_id", sa.Text(), nullable=False),
        sa.Column("previous_phase_id", sa.Text(), nullable=False),
        sa.Column("definition_id", sa.Text(), nullable=False),
        sa.Column("actor_uuid", sa.Text(), nullable=False),
        sa.Column("target_uuid", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("idx_match_events_match", "match_events", ["server_id", "match_id", "id"])
    op.create_index("idx_match_events_occurred", "match_events", ["occurred_at"])

    op.create_table(
        "idempotency",
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("request_id"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_audit_created", "audit_log", ["created_at"])

    op.create_table(
        "change_log",
        sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("change_type", sa.Text(), nullable=False),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("player_uuid", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_change_log_server", "change_log", ["server_id", "seq"])
    op.create_index("idx_change_log_occurred", "change_log", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("idx_change_log_occurred", table_name="change_log")
    op.drop_index("idx_change_log_server", table_name="change_log")
    op.drop_table("change_log")
    op.drop_index("idx_audit_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("idempotency")
    op.drop_index("idx_match_events_occurred", table_name="match_events")
    op.drop_index("idx_match_events_match", table_name="match_events")
    op.drop_table("match_events")
    op.drop_table("settlement_lines")
    op.drop_index("idx_settlements_match", table_name="settlements")
    op.drop_index("idx_settlements_player", table_name="settlements")
    op.drop_table("settlements")
    op.drop_table("server_configs")
    op.drop_index("idx_role_overrides_player", table_name="role_overrides")
    op.drop_table("role_overrides")
    op.drop_index("idx_players_server", table_name="players")
    op.drop_table("players")
