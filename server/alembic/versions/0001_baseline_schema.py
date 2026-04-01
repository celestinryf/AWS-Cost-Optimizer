"""Baseline: capture initial schema (runs + execution_audit tables).

Revision ID: 0001
Revises:
Create Date: 2026-03-30

This migration records the schema that already exists in production.
Running upgrade() on a fresh database creates both tables; running it
on an existing database is a no-op because of IF NOT EXISTS guards.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            recommendations_json TEXT NOT NULL,
            scores_json TEXT NOT NULL,
            savings_details_json TEXT NOT NULL,
            savings_summary_json TEXT,
            execution_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_runs_updated_at
        ON runs(updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_audit (
            audit_id TEXT PRIMARY KEY,
            execution_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            recommendation_id TEXT NOT NULL,
            recommendation_type TEXT NOT NULL,
            bucket TEXT NOT NULL,
            key TEXT,
            action_status TEXT NOT NULL,
            message TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            requires_approval INTEGER NOT NULL,
            permitted INTEGER NOT NULL,
            required_permissions_json TEXT NOT NULL,
            missing_permissions_json TEXT NOT NULL,
            simulated INTEGER NOT NULL,
            pre_change_state_json TEXT NOT NULL,
            post_change_state_json TEXT,
            rollback_available INTEGER NOT NULL,
            rollback_status TEXT NOT NULL,
            rolled_back_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_execution_audit_run_id
        ON execution_audit(run_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_execution_audit_execution_id
        ON execution_audit(execution_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_execution_audit_execution_id")
    op.execute("DROP INDEX IF EXISTS idx_execution_audit_run_id")
    op.execute("DROP TABLE IF EXISTS execution_audit")
    op.execute("DROP INDEX IF EXISTS idx_runs_updated_at")
    op.execute("DROP TABLE IF EXISTS runs")
