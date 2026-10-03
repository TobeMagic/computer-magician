"""credential vault and platform health

Revision ID: 202605180002
Revises: 202605180001
Create Date: 2026-05-18 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605180002"
down_revision: str | None = "202605180001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credential_materials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("credential_kind", sa.String(length=80), nullable=False),
        sa.Column("encrypted_blob", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("source_machine", sa.String(length=160), nullable=True),
        sa.Column("source_ip", sa.String(length=80), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="stored"),
        sa.Column("validation_status", sa.String(length=80), nullable=False, server_default="pending"),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], name=op.f("fk_credential_materials_uploaded_by_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credential_materials")),
    )
    op.create_index(op.f("ix_credential_materials_fingerprint"), "credential_materials", ["fingerprint"], unique=False)
    op.create_index(op.f("ix_credential_materials_platform"), "credential_materials", ["platform"], unique=False)
    op.create_index("ix_credential_materials_platform_kind_created", "credential_materials", ["platform", "credential_kind", "created_at"], unique=False)
    op.create_index("ix_credential_materials_platform_status", "credential_materials", ["platform", "status"], unique=False)
    op.create_index(op.f("ix_credential_materials_status"), "credential_materials", ["status"], unique=False)
    op.create_index(op.f("ix_credential_materials_uploaded_by_user_id"), "credential_materials", ["uploaded_by_user_id"], unique=False)
    op.create_index(op.f("ix_credential_materials_validation_status"), "credential_materials", ["validation_status"], unique=False)

    op.create_table(
        "platform_health",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="unknown"),
        sa.Column("readiness", sa.String(length=80), nullable=False, server_default="unknown"),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blockers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("capabilities_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["credential_id"], ["credential_materials.id"], name=op.f("fk_platform_health_credential_id_credential_materials"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_health")),
        sa.UniqueConstraint("platform", name="uq_platform_health_platform"),
    )
    op.create_index(op.f("ix_platform_health_credential_id"), "platform_health", ["credential_id"], unique=False)
    op.create_index(op.f("ix_platform_health_readiness"), "platform_health", ["readiness"], unique=False)
    op.create_index(op.f("ix_platform_health_status"), "platform_health", ["status"], unique=False)
    op.create_index("ix_platform_health_status_readiness", "platform_health", ["status", "readiness"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_platform_health_status_readiness", table_name="platform_health")
    op.drop_index(op.f("ix_platform_health_status"), table_name="platform_health")
    op.drop_index(op.f("ix_platform_health_readiness"), table_name="platform_health")
    op.drop_index(op.f("ix_platform_health_credential_id"), table_name="platform_health")
    op.drop_table("platform_health")

    op.drop_index(op.f("ix_credential_materials_validation_status"), table_name="credential_materials")
    op.drop_index(op.f("ix_credential_materials_uploaded_by_user_id"), table_name="credential_materials")
    op.drop_index(op.f("ix_credential_materials_status"), table_name="credential_materials")
    op.drop_index("ix_credential_materials_platform_status", table_name="credential_materials")
    op.drop_index("ix_credential_materials_platform_kind_created", table_name="credential_materials")
    op.drop_index(op.f("ix_credential_materials_platform"), table_name="credential_materials")
    op.drop_index(op.f("ix_credential_materials_fingerprint"), table_name="credential_materials")
    op.drop_table("credential_materials")
