"""add_audit_run_trace_id

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-11-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('audit_runs', sa.Column('trace_id', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_audit_runs_trace_id'), 'audit_runs', ['trace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_audit_runs_trace_id'), table_name='audit_runs')
    op.drop_column('audit_runs', 'trace_id')
