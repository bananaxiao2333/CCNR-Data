# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""device login：Casdoor Device Code 的一次性登录会话。

Revision ID: 0003_device_login
Revises: 0002_control_plane
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_device_login"
down_revision = "0002_control_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_logins",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("device_code", sa.Text(), nullable=False),
        sa.Column("user_code", sa.Text(), nullable=False),
        sa.Column("player_uuid", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("proxy_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("interval_s", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("approved_at", sa.Integer(), nullable=True),
        sa.Column("casdoor_user_id", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_index("idx_device_logins_status", "device_logins", ["status", "expires_at"])
    op.create_index("idx_device_logins_player", "device_logins", ["player_uuid", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_device_logins_player", table_name="device_logins")
    op.drop_index("idx_device_logins_status", table_name="device_logins")
    op.drop_table("device_logins")
