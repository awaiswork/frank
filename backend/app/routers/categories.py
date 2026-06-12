"""Categories — read the user's category list (seeded at registration, §5).

§8 doesn't enumerate a categories endpoint, but the UI needs the user's category
ids to assign transactions and budgets, so we expose a read-only list scoped to
the current user. (Custom-category creation is out of scope for v1.)
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import Category
from app.schemas import CategoryOut

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
def list_categories(user: CurrentUser, db: DbSession) -> list[Category]:
    stmt = (
        select(Category)
        .where(Category.user_id == user.id)
        .order_by(Category.kind.desc(), Category.name)  # expense before income, then A–Z
    )
    return list(db.scalars(stmt))
