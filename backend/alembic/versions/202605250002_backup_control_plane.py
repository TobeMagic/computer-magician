"""backup control plane

Revision ID: 202605250002
Revises: 202605250001
Create Date: 2026-05-25 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605250002"
down_revision: str | None = "202605250001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_manifests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("backup_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="created"),
        sa.Column("storage_uri", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(length=160), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("statistics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("risks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_backup_manifests_actor_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_manifests")),
    )
    op.create_index(op.f("ix_backup_manifests_actor_user_id"), "backup_manifests", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_backup_manifests_backup_type"), "backup_manifests", ["backup_type"], unique=False)
    op.create_index(op.f("ix_backup_manifests_status"), "backup_manifests", ["status"], unique=False)
    op.create_index("ix_backup_manifests_type_status_created", "backup_manifests", ["backup_type", "status", "created_at"], unique=False)

    op.create_table(
        "restore_drills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("manifest_id", sa.Uuid(), nullable=True),
        sa.Column("drill_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="created"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("verified_counts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("risks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_restore_drills_actor_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["manifest_id"], ["backup_manifests.id"], name=op.f("fk_restore_drills_manifest_id_backup_manifests"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_restore_drills")),
    )
    op.create_index(op.f("ix_restore_drills_actor_user_id"), "restore_drills", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_restore_drills_drill_type"), "restore_drills", ["drill_type"], unique=False)
    op.create_index(op.f("ix_restore_drills_manifest_id"), "restore_drills", ["manifest_id"], unique=False)
    op.create_index(op.f("ix_restore_drills_status"), "restore_drills", ["status"], unique=False)
    op.create_index("ix_restore_drills_status_created", "restore_drills", ["status", "created_at"], unique=False)
    op.create_index("ix_restore_drills_type_status", "restore_drills", ["drill_type", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_restore_drills_type_status", table_name="restore_drills")
    op.drop_index("ix_restore_drills_status_created", table_name="restore_drills")
    op.drop_index(op.f("ix_restore_drills_status"), table_name="restore_drills")
    op.drop_index(op.f("ix_restore_drills_manifest_id"), table_name="restore_drills")
    op.drop_index(op.f("ix_restore_drills_drill_type"), table_name="restore_drills")
    op.drop_index(op.f("ix_restore_drills_actor_user_id"), table_name="restore_drills")
    op.drop_table("restore_drills")

    op.drop_index("ix_backup_manifests_type_status_created", table_name="backup_manifests")
    op.drop_index(op.f("ix_backup_manifests_status"), table_name="backup_manifests")
    op.drop_index(op.f("ix_backup_manifests_backup_type"), table_name="backup_manifests")
    op.drop_index(op.f("ix_backup_manifests_actor_user_id"), table_name="backup_manifests")
    op.drop_table("backup_manifests")
