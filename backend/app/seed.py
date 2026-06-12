"""Default categories created per user at registration (technical-plan.md §5).

Colors are the design system's category tokens (docs/design/design-system.md).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Category

DEFAULT_CATEGORIES: list[tuple[str, str, str]] = [
    ("Groceries", "expense", "#9BC85F"),
    ("Eating out", "expense", "#E8995A"),
    ("Transport", "expense", "#62B0CE"),
    ("Fun", "expense", "#DB85C6"),
    ("Bills", "expense", "#9C97B4"),
    ("Health", "expense", "#E58BA0"),
    ("Income", "income", "#63C68C"),
]


def seed_default_categories(db: Session, user_id: uuid.UUID) -> None:
    db.add_all(
        Category(user_id=user_id, name=name, kind=kind, color=color)
        for name, kind, color in DEFAULT_CATEGORIES
    )
