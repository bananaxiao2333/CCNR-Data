# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""control plane：身份投影、准入规则、代理会话与事件。

同时删除旧的 schema_meta（版本管理交给 alembic_version）。

Revision ID: 0002_control_plane
Revises: 0001_baseline
Create Date: 2026-10-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_control_plane"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "player_identities",
        sa.Column("player_uuid", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("username_lower", sa.Text(), nullable=False),
        sa.Column("casdoor_user_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("linked_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("player_uuid"),
    )
    op.create_index(
        "uq_player_identities_username",
        "player_identities",
        ["username_lower"],
        unique=True,
    )
    op.create_index("idx_player_identities_casdoor", "player_identities", ["casdoor_user_id"])

    op.create_table(
        "access_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("effect", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_access_rules_subject",
        "access_rules",
        ["subject_type", "subject", "scope"],
        unique=True,
    )
    op.create_index("idx_access_rules_expires", "access_rules", ["expires_at"])

    op.create_table(
        "access_policies",
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("scope"),
    )

    op.create_table(
        "proxy_sessions",
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("player_uuid", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("proxy_id", sa.Text(), nullable=False),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Integer(), nullable=False),
        sa.Column("last_seen_at", sa.Integer(), nullable=False),
        sa.Column("ended_at", sa.Integer(), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=False),
        sa.Column("client_version", sa.Text(), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("idx_proxy_sessions_online", "proxy_sessions", ["ended_at", "last_seen_at"])
    op.create_index("idx_proxy_sessions_player", "proxy_sessions", ["player_uuid", "started_at"])
    op.create_index("idx_proxy_sessions_server", "proxy_sessions", ["server_id", "started_at"])

    op.create_table(
        "proxy_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("player_uuid", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("from_server_id", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.Integer(), nullable=False),
        sa.Column("end_reason", sa.Text(), nullable=False),
        sa.Column("deny_reason", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("idx_proxy_events_occurred", "proxy_events", ["occurred_at"])

    bind = op.get_bind()
    if "schema_meta" in sa.inspect(bind).get_table_names():
        op.drop_table("schema_meta")


def downgrade() -> None:
    op.drop_index("idx_proxy_events_occurred", table_name="proxy_events")
    op.drop_table("proxy_events")
    op.drop_index("idx_proxy_sessions_server", table_name="proxy_sessions")
    op.drop_index("idx_proxy_sessions_player", table_name="proxy_sessions")
    op.drop_index("idx_proxy_sessions_online", table_name="proxy_sessions")
    op.drop_table("proxy_sessions")
    op.drop_table("access_policies")
    op.drop_index("idx_access_rules_expires", table_name="access_rules")
    op.drop_index("uq_access_rules_subject", table_name="access_rules")
    op.drop_table("access_rules")
    op.drop_index("idx_player_identities_casdoor", table_name="player_identities")
    op.drop_index("uq_player_identities_username", table_name="player_identities")
    op.drop_table("player_identities")

    op.create_table(
        "schema_meta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("applied_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_schema_meta_single_row"),
        sa.PrimaryKeyConstraint("id"),
    )
