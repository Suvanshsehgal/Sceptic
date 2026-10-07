"""add_hashed_password_to_users

Revision ID: 8f1e2d3c4b5a
Revises: 79a4b960b2f5
Create Date: 2026-10-07 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f1e2d3c4b5a'
down_revision: Union[str, None] = '79a4b960b2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS hashed_password VARCHAR(255);"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS hashed_password;"))
