"""Dates belong to the user, not to the server process.

Before this, every date the app decided for itself came from ``date.today()`` — the
API container's today. These pin the three things that has to mean now: the helper
resolves a date in the user's zone, an unusable zone degrades instead of raising, and
the endpoints actually route through it.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app.deps import today_in
from tests.conftest import create_account

# 25 hours apart, so their local dates differ at *every* instant. That is what makes
# the endpoint test below deterministic without freezing the clock.
FAR_EAST = "Pacific/Kiritimati"  # UTC+14
FAR_WEST = "Pacific/Niue"  # UTC-11

# Midnight UTC: the east is already tomorrow afternoon, the west still yesterday.
MOMENT = dt.datetime(2026, 8, 10, 0, 30, tzinfo=dt.UTC)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_today_in_resolves_the_users_date() -> None:
    assert today_in(FAR_EAST, now=MOMENT) == dt.date(2026, 8, 10)
    assert today_in(FAR_WEST, now=MOMENT) == dt.date(2026, 8, 9)
    assert today_in("Europe/Helsinki", now=MOMENT) == dt.date(2026, 8, 10)


def test_today_in_falls_back_to_utc() -> None:
    """Unset is UTC, and so is unusable — this must never be the thing that 500s.

    A name retired from the tz database, or a hand-edited row, would otherwise raise on
    every request the user makes. UTC is the same answer the app gave before anyone
    could set a zone, so degrading costs nothing.
    """
    assert today_in(None, now=MOMENT) == dt.date(2026, 8, 10)
    assert today_in("", now=MOMENT) == dt.date(2026, 8, 10)
    assert today_in("Mars/Olympus_Mons", now=MOMENT) == dt.date(2026, 8, 10)
    assert today_in("../../etc/passwd", now=MOMENT) == dt.date(2026, 8, 10)


def test_patch_me_round_trips_a_timezone(client: TestClient) -> None:
    token = create_account(client, "tz@example.com")
    assert client.get("/me", headers=_h(token)).json()["timezone"] is None

    ok = client.patch("/me", headers=_h(token), json={"timezone": "Europe/Helsinki"})
    assert ok.status_code == 200
    assert ok.json()["timezone"] == "Europe/Helsinki"

    # explicit null is how the user withdraws it, and must not be read as "unset"
    cleared = client.patch("/me", headers=_h(token), json={"timezone": None})
    assert cleared.status_code == 200
    assert cleared.json()["timezone"] is None


def test_patch_me_rejects_an_unknown_timezone(client: TestClient) -> None:
    token = create_account(client, "badtz@example.com")
    bad = client.patch("/me", headers=_h(token), json={"timezone": "Europe/Atlantis"})
    assert bad.status_code == 422
    assert client.get("/me", headers=_h(token)).json()["timezone"] is None


def test_daily_note_is_dated_in_the_users_timezone(client: TestClient) -> None:
    """The endpoint honours it, not just the helper.

    Two accounts 25 hours apart must never agree on what day it is, whenever this runs.
    """
    east = create_account(client, "east@example.com")
    west = create_account(client, "west@example.com")
    assert client.patch("/me", headers=_h(east), json={"timezone": FAR_EAST}).status_code == 200
    assert client.patch("/me", headers=_h(west), json={"timezone": FAR_WEST}).status_code == 200

    east_date = client.get("/advisor/daily", headers=_h(east)).json()["date"]
    west_date = client.get("/advisor/daily", headers=_h(west)).json()["date"]

    assert east_date != west_date
    assert dt.date.fromisoformat(east_date) - dt.date.fromisoformat(west_date) == dt.timedelta(
        days=1
    )
