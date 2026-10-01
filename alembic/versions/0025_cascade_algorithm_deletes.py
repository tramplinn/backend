"""cascade deletes of algorithm problems and practice sets to their history

Revision ID: 0025_cascade_algorithm_deletes
Revises: 0024_profile_directories
Create Date: 2026-10-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025_cascade_algorithm_deletes"
down_revision: str | None = "0024_profile_directories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (constraint, table, column, referred table)
_FKS: list[tuple[str, str, str, str]] = [
    (
        "fk_algorithm_submissions_problem_id_algorithm_problems",
        "algorithm_submissions",
        "problem_id",
        "algorithm_problems",
    ),
    (
        "fk_practice_sessions_practice_set_id_practice_sets",
        "practice_sessions",
        "practice_set_id",
        "practice_sets",
    ),
]


def _recreate(ondelete: str) -> None:
    for name, table, column, referred in _FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, referred, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    _recreate("CASCADE")


def downgrade() -> None:
    _recreate("RESTRICT")
