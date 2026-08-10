"""The migrations and the models must describe the same database.

Nothing else in the suite checks this. `conftest` builds the test schema from
``Base.metadata.create_all``, while production builds it by running the migration
chain — so a model and its migration can disagree indefinitely and every test still
passes. ``savings_goals.archived_at`` did exactly that: the model inferred a naive
``DateTime()`` from its annotation while migration 0001 created ``timestamptz``.

This runs the real chain against a scratch database and asks Alembic to autogenerate
against ``Base.metadata``. Anything it would write into a new revision is drift, and
drift is a bug in one of the two places.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, text

from alembic import command
from app.config import get_settings
from app.db import Base

from .conftest import _ensure_database, _test_db_url


def _migrations_db_url() -> str:
    """A database of its own — this one is built by migrations, not by metadata."""
    base, _, name = _test_db_url().rpartition("/")
    return f"{base}/{name}_migrations"


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[Engine]:
    url = _migrations_db_url()
    _ensure_database(url)

    eng = create_engine(url)
    with eng.begin() as conn:
        # Start from nothing, so a re-run can never compare against a half-migrated
        # leftover from a previous failure.
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    # alembic/env.py reads the URL from get_settings(), which is lru_cached — so the
    # env var alone is not enough, the cache has to be dropped either side. Restored
    # afterwards because the rest of the suite shares this process.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()

    yield eng
    eng.dispose()


def test_migrations_match_models(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={"compare_type": True, "target_metadata": Base.metadata},
        )
        diffs: list[Any] = compare_metadata(context, Base.metadata)

    assert not diffs, (
        "The migration chain and app.models describe different schemas. Each entry below "
        "is a change Alembic would put in a new revision — fix whichever side is wrong "
        "(and remember: never edit a migration that has already run in production, write "
        "a new one).\n\n" + "\n".join(f"  - {d}" for d in diffs)
    )
