# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""device login：区分游戏登录与 bot 账号绑定。

Revision ID: 0004_device_login_purpose
Revises: 0003_device_login
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_device_login_purpose"
down_revision = "0003_device_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_logins",
        sa.Column("purpose", sa.Text(), nullable=False, server_default="GAME"),
    )


def downgrade() -> None:
    op.drop_column("device_logins", "purpose")
