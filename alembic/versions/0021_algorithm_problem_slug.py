"""add slug to algorithm_problems

Revision ID: 0021_algorithm_problem_slug
Revises: 0020_drop_soft_delete
Create Date: 2026-09-08
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_algorithm_problem_slug"
down_revision: str | None = "0020_drop_soft_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "c",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def _slugify(title: str) -> str:
    text = "".join(_TRANSLIT.get(ch, ch) for ch in title.lower())
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:100] or "problem"


def upgrade() -> None:
    op.add_column("algorithm_problems", sa.Column("slug", sa.String(120), nullable=True))
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, title FROM algorithm_problems ORDER BY created_at")
    ).fetchall()
    used: set[str] = set()
    for row in rows:
        base = _slugify(row.title)
        slug = base
        suffix = 1
        while slug in used:
            suffix += 1
            slug = f"{base}-{suffix}"
        used.add(slug)
        conn.execute(
            sa.text("UPDATE algorithm_problems SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": row.id},
        )
    op.alter_column("algorithm_problems", "slug", existing_type=sa.String(120), nullable=False)
    op.create_unique_constraint("uq_algorithm_problems_slug", "algorithm_problems", ["slug"])


def downgrade() -> None:
    op.drop_constraint("uq_algorithm_problems_slug", "algorithm_problems", type_="unique")
    op.drop_column("algorithm_problems", "slug")
