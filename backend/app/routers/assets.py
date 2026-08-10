"""Assets and their valuations — what is owned that has no ledger.

Nothing here transacts. An asset is worth what its owner last said it was worth, and
net worth reads the most recent statement on or before whatever date is being asked
about, so a valuation entered late but dated correctly rewrites the trend from then.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DbSession, LedgerUpToDate, Today
from app.models import Asset, AssetValuation
from app.schemas import (
    AssetCreate,
    AssetOut,
    AssetUpdate,
    NetWorthOut,
    NetWorthPointOut,
    ValuationIn,
)
from app.services.networth import net_worth

router = APIRouter(prefix="/assets", tags=["assets"])


def _owned(db: Session, user_id: uuid.UUID, asset_id: uuid.UUID) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    return asset


def _latest(db: Session, asset_id: uuid.UUID) -> AssetValuation | None:
    return db.scalar(
        select(AssetValuation)
        .where(AssetValuation.asset_id == asset_id)
        .order_by(AssetValuation.valued_on.desc())
        .limit(1)
    )


def _out(db: Session, asset: Asset, today: dt.date) -> AssetOut:
    latest = _latest(db, asset.id)
    return AssetOut(
        id=asset.id,
        name=asset.name,
        group=asset.group,
        archived_at=asset.archived_at,
        value_cents=latest.value_cents if latest else None,
        last_valued_on=latest.valued_on if latest else None,
        days_since_valued=(today - latest.valued_on).days if latest else None,
    )


@router.get("", response_model=list[AssetOut])
def list_assets(
    user: CurrentUser,
    db: DbSession,
    today: Today,
    include_archived: bool = Query(default=False),
) -> list[AssetOut]:
    stmt = select(Asset).where(Asset.user_id == user.id)
    if not include_archived:
        stmt = stmt.where(Asset.archived_at.is_(None))
    return [_out(db, asset, today) for asset in db.scalars(stmt.order_by(Asset.name))]


@router.post("", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
def create_asset(body: AssetCreate, user: CurrentUser, db: DbSession, today: Today) -> AssetOut:
    """Created with its first valuation, because an asset with no value says nothing.

    A row with no number attached would sit in the list contributing nothing to net
    worth and looking like it should.
    """
    asset = Asset(user_id=user.id, name=body.name.strip(), group=body.group)
    db.add(asset)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have something with that name"
        ) from exc

    db.add(
        AssetValuation(
            asset_id=asset.id,
            valued_on=body.valued_on or today,
            value_cents=body.value_cents,
        )
    )
    db.commit()
    return _out(db, asset, today)


@router.post("/{asset_id}/valuations", response_model=AssetOut)
def add_valuation(
    asset_id: uuid.UUID, body: ValuationIn, user: CurrentUser, db: DbSession, today: Today
) -> AssetOut:
    """State what it is worth now — or what it was worth on some earlier day.

    Backdating is the point: net worth reads the most recent statement on or before
    each date, so saying today what a car was worth in March corrects March.
    """
    asset = _owned(db, user.id, asset_id)
    valued_on = body.valued_on or today

    existing = db.scalar(
        select(AssetValuation).where(
            AssetValuation.asset_id == asset.id, AssetValuation.valued_on == valued_on
        )
    )
    if existing is not None:
        # Saying it twice on one day means the second is the answer, not that both are.
        existing.value_cents = body.value_cents
    else:
        db.add(AssetValuation(asset_id=asset.id, valued_on=valued_on, value_cents=body.value_cents))
    db.commit()
    return _out(db, asset, today)


@router.patch("/{asset_id}", response_model=AssetOut)
def update_asset(
    asset_id: uuid.UUID, body: AssetUpdate, user: CurrentUser, db: DbSession, today: Today
) -> AssetOut:
    asset = _owned(db, user.id, asset_id)
    data = body.model_dump(exclude_unset=True)
    if "archived" in data and data["archived"] is not None:
        # Archiving is how something is sold: it counts up to here and not after, so
        # the trend falls on this date without any special case.
        asset.archived_at = dt.datetime.now(dt.UTC) if data["archived"] else None
    if data.get("name") is not None:
        asset.name = str(data["name"]).strip()
    if data.get("group") is not None:
        asset.group = str(data["group"])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have something with that name"
        ) from exc
    return _out(db, asset, today)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    """Removes it from history entirely — archive instead to record a sale."""
    asset = _owned(db, user.id, asset_id)
    db.delete(asset)
    db.commit()


@router.get("/net-worth", response_model=NetWorthOut, dependencies=[LedgerUpToDate])
def net_worth_series(
    user: CurrentUser,
    db: DbSession,
    today: Today,
    months: int = Query(default=12, ge=2, le=60),
) -> NetWorthOut:
    series = net_worth(db, user.id, today=today, months=months)
    return NetWorthOut(
        points=[
            NetWorthPointOut(
                on=point.on,
                accounts_cents=point.accounts_cents,
                assets_cents=point.assets_cents,
                total_cents=point.total_cents,
            )
            for point in series.points
        ],
        complete_from=series.complete_from,
    )
