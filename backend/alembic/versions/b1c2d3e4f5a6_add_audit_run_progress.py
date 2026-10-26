"""add_audit_run_progress

Revision ID: b1c2d3e4f5a6
Revises: a7d8e9f01234
Create Date: 2026-10-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a7d8e9f01234'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('audit_runs', sa.Column('progress', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('audit_runs', 'progress')
