# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""device login：指定期望的 CCNR 账号，只允许它完成本次验证。

Revision ID: 0006_device_login_expected_account
Revises: 0005_account_links
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_device_login_expected_account"
down_revision = "0005_account_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("device_logins", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "expected_casdoor_user_id",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("device_logins", schema=None) as batch_op:
        batch_op.drop_column("expected_casdoor_user_id")
