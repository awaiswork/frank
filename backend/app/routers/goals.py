"""Savings goals + contributions (§8). All queries scoped to the current user."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DbSession
from app.models import GoalContribution, SavingsGoal
from app.schemas import (
    GoalContributionIn,
    GoalContributionOut,
    GoalCreate,
    GoalOut,
    GoalUpdate,
)

router = APIRouter(prefix="/goals", tags=["goals"])


def _owned_goal(db: Session, user_id: uuid.UUID, goal_id: uuid.UUID) -> SavingsGoal:
    goal = db.get(SavingsGoal, goal_id)
    if goal is None or goal.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found")
    return goal


def _contributed_cents(db: Session, goal_id: uuid.UUID) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(GoalContribution.amount_cents), 0)).where(
            GoalContribution.goal_id == goal_id
        )
    )
    return int(total or 0)


def _to_out(goal: SavingsGoal, contributed_cents: int) -> GoalOut:
    progress = contributed_cents / goal.target_cents if goal.target_cents > 0 else 0.0
    return GoalOut(
        id=goal.id,
        name=goal.name,
        target_cents=goal.target_cents,
        due_date=goal.due_date,
        archived_at=goal.archived_at,
        contributed_cents=contributed_cents,
        progress_fraction=progress,
    )


@router.get("", response_model=list[GoalOut])
def list_goals(
    user: CurrentUser,
    db: DbSession,
    include_archived: Annotated[bool, Query()] = False,
) -> list[GoalOut]:
    contributed = (
        select(
            GoalContribution.goal_id.label("goal_id"),
            func.coalesce(func.sum(GoalContribution.amount_cents), 0).label("total"),
        )
        .group_by(GoalContribution.goal_id)
        .subquery()
    )
    stmt = (
        select(SavingsGoal, func.coalesce(contributed.c.total, 0))
        .join(contributed, contributed.c.goal_id == SavingsGoal.id, isouter=True)
        .where(SavingsGoal.user_id == user.id)
        .order_by(SavingsGoal.due_date.nulls_last(), SavingsGoal.created_at)
    )
    if not include_archived:
        stmt = stmt.where(SavingsGoal.archived_at.is_(None))
    return [_to_out(goal, int(total)) for goal, total in db.execute(stmt)]


@router.post("", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
def create_goal(body: GoalCreate, user: CurrentUser, db: DbSession) -> GoalOut:
    goal = SavingsGoal(
        user_id=user.id,
        name=body.name,
        target_cents=body.target_cents,
        due_date=body.due_date,
    )
    db.add(goal)
    db.commit()
    return _to_out(goal, 0)


@router.patch("/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: uuid.UUID, body: GoalUpdate, user: CurrentUser, db: DbSession) -> GoalOut:
    goal = _owned_goal(db, user.id, goal_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        goal.name = data["name"]
    if "target_cents" in data:
        goal.target_cents = data["target_cents"]
    if "due_date" in data:
        goal.due_date = data["due_date"]
    if "archived" in data:
        goal.archived_at = dt.datetime.now(dt.UTC) if data["archived"] else None
    db.commit()
    return _to_out(goal, _contributed_cents(db, goal.id))


@router.post(
    "/{goal_id}/contributions",
    response_model=GoalContributionOut,
    status_code=status.HTTP_201_CREATED,
)
def add_contribution(
    goal_id: uuid.UUID, body: GoalContributionIn, user: CurrentUser, db: DbSession
) -> GoalContribution:
    _owned_goal(db, user.id, goal_id)
    contribution = GoalContribution(
        goal_id=goal_id,
        amount_cents=body.amount_cents,
        occurred_on=body.occurred_on or dt.date.today(),
    )
    db.add(contribution)
    db.commit()
    return contribution
