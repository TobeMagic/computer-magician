"""series kind taxonomy

Revision ID: 202608040001
Revises: 202606120001
Create Date: 2026-08-04 12:00:00

Adds ``series_kind`` to ``series`` so the cron router can dispatch
hot-topic / industry-insight / solution / architecture jobs without
having to grep the row name. Values: ``hot`` (legacy daily-news),
``industry_insight``, ``solution_architecture``, ``architecture_design``.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608040001"
down_revision: str | None = "202606120001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SERIES_KIND_VALUES = (
    "hot",
    "industry_insight",
    "solution_architecture",
    "architecture_design",
)


def upgrade() -> None:
    op.add_column(
        "series",
        sa.Column(
            "series_kind",
            sa.String(length=40),
            nullable=False,
            server_default="hot",
        ),
    )
    op.create_index(
        op.f("ix_series_series_kind"),
        "series",
        ["series_kind"],
        unique=False,
    )

    bind = op.get_bind()
    series_table = sa.table(
        "series",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String),
        sa.column("series_kind", sa.String),
    )
    bind.execute(
        series_table.update().where(
            sa.or_(
                series_table.c.name.ilike("%极客成长%"),
                series_table.c.name.ilike("%geek_growth%"),
            )
        ).values(series_kind="hot")
    )
    bind.execute(
        series_table.update().where(
            series_table.c.name.ilike("%Notion%")
        ).values(series_kind="hot")
    )
    bind.execute(
        series_table.update().where(
            series_table.c.name.ilike("%AI 工作流%")
        ).values(series_kind="hot")
    )
    bind.execute(
        series_table.update().where(
            series_table.c.name.ilike("%面试八股%")
        ).values(series_kind="hot")
    )

    bind.execute(
        sa.text(
            "UPDATE series SET series_kind = 'hot' WHERE series_kind NOT IN (:k1, :k2, :k3, :k4)"
        ).bindparams(
            k1="hot",
            k2="industry_insight",
            k3="solution_architecture",
            k4="architecture_design",
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_series_series_kind"), table_name="series")
    op.drop_column("series", "series_kind")