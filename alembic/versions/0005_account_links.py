# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""account links：平台账号 ↔ Casdoor 用户。

Revision ID: 0005_account_links
Revises: 0004_device_login_purpose
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_account_links"
down_revision = "0004_device_login_purpose"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_links",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("casdoor_user_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("linked_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("casdoor_user_id"),
    )


def downgrade() -> None:
    op.drop_table("account_links")
