"""add_deployments_telemetry_drift_rollback

Revision ID: a7d8e9f01234
Revises: 8f1e2d3c4b5a
Create Date: 2026-10-08 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import models


# revision identifiers, used by Alembic.
revision: str = 'a7d8e9f01234'
down_revision: Union[str, None] = '8f1e2d3c4b5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. deployments table
    op.create_table(
        'deployments',
        sa.Column('id', models.GUID(), nullable=False),
        sa.Column('project_id', models.GUID(), nullable=False),
        sa.Column('commit_sha', sa.String(length=100), nullable=False),
        sa.Column('image_name', sa.String(length=255), nullable=False),
        sa.Column('image_tag', sa.String(length=100), nullable=False),
        sa.Column('image_digest', sa.String(length=255), nullable=True),
        sa.Column('environment', sa.String(length=50), nullable=False),
        sa.Column('version', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('deployed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('previous_deployment_id', models.GUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['previous_deployment_id'], ['deployments.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deployments_id'), 'deployments', ['id'], unique=False)
    op.create_index(op.f('ix_deployments_project_id'), 'deployments', ['project_id'], unique=False)
    op.create_index(op.f('ix_deployments_commit_sha'), 'deployments', ['commit_sha'], unique=False)
    op.create_index(op.f('ix_deployments_environment'), 'deployments', ['environment'], unique=False)
    op.create_index(op.f('ix_deployments_status'), 'deployments', ['status'], unique=False)
    op.create_index(op.f('ix_deployments_previous_deployment_id'), 'deployments', ['previous_deployment_id'], unique=False)
    op.create_index('ix_deployments_project_status', 'deployments', ['project_id', 'status'], unique=False)
    op.create_index('ix_deployments_project_env', 'deployments', ['project_id', 'environment'], unique=False)

    # 2. telemetry_snapshots table
    op.create_table(
        'telemetry_snapshots',
        sa.Column('id', models.GUID(), nullable=False),
        sa.Column('deployment_id', models.GUID(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('health_status', sa.String(length=50), nullable=False),
        sa.Column('request_count', sa.Integer(), nullable=True),
        sa.Column('error_count', sa.Integer(), nullable=True),
        sa.Column('error_rate', sa.Float(), nullable=True),
        sa.Column('latency_avg', sa.Float(), nullable=True),
        sa.Column('latency_p95', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['deployment_id'], ['deployments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('request_count IS NULL OR request_count >= 0', name='chk_telemetry_request_count'),
        sa.CheckConstraint('error_count IS NULL OR error_count >= 0', name='chk_telemetry_error_count'),
        sa.CheckConstraint('error_rate IS NULL OR (error_rate >= 0.0 AND error_rate <= 1.0)', name='chk_telemetry_error_rate'),
        sa.CheckConstraint('latency_avg IS NULL OR latency_avg >= 0.0', name='chk_telemetry_latency_avg'),
        sa.CheckConstraint('latency_p95 IS NULL OR latency_p95 >= 0.0', name='chk_telemetry_latency_p95')
    )
    op.create_index(op.f('ix_telemetry_snapshots_id'), 'telemetry_snapshots', ['id'], unique=False)
    op.create_index(op.f('ix_telemetry_snapshots_deployment_id'), 'telemetry_snapshots', ['deployment_id'], unique=False)
    op.create_index(op.f('ix_telemetry_snapshots_timestamp'), 'telemetry_snapshots', ['timestamp'], unique=False)
    op.create_index('ix_telemetry_deployment_timestamp', 'telemetry_snapshots', ['deployment_id', 'timestamp'], unique=False)

    # 3. drift_events table
    op.create_table(
        'drift_events',
        sa.Column('id', models.GUID(), nullable=False),
        sa.Column('deployment_id', models.GUID(), nullable=False),
        sa.Column('drift_type', sa.String(length=50), nullable=False),
        sa.Column('expected_value', sa.Text(), nullable=False),
        sa.Column('actual_value', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['deployment_id'], ['deployments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_drift_events_id'), 'drift_events', ['id'], unique=False)
    op.create_index(op.f('ix_drift_events_deployment_id'), 'drift_events', ['deployment_id'], unique=False)
    op.create_index(op.f('ix_drift_events_drift_type'), 'drift_events', ['drift_type'], unique=False)
    op.create_index(op.f('ix_drift_events_severity'), 'drift_events', ['severity'], unique=False)
    op.create_index(op.f('ix_drift_events_detected_at'), 'drift_events', ['detected_at'], unique=False)
    op.create_index('ix_drift_events_deployment_detected', 'drift_events', ['deployment_id', 'detected_at'], unique=False)

    # 4. rollback_records table
    op.create_table(
        'rollback_records',
        sa.Column('id', models.GUID(), nullable=False),
        sa.Column('deployment_id', models.GUID(), nullable=False),
        sa.Column('target_deployment_id', models.GUID(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('trigger_source', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('safety_check_result', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['deployment_id'], ['deployments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_deployment_id'], ['deployments.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rollback_records_id'), 'rollback_records', ['id'], unique=False)
    op.create_index(op.f('ix_rollback_records_deployment_id'), 'rollback_records', ['deployment_id'], unique=False)
    op.create_index(op.f('ix_rollback_records_target_deployment_id'), 'rollback_records', ['target_deployment_id'], unique=False)
    op.create_index(op.f('ix_rollback_records_status'), 'rollback_records', ['status'], unique=False)
    op.create_index('ix_rollback_records_deployment_created', 'rollback_records', ['deployment_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('rollback_records')
    op.drop_table('drift_events')
    op.drop_table('telemetry_snapshots')
    op.drop_table('deployments')
