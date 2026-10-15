# A new account's first page load sends several requests at once; each
# creates the user if it's missing, and all but one lose the insert race.
from unittest.mock import MagicMock

from app import models
from app.auth import get_or_create_user


def test_creates_the_user_on_first_request(db_session):
    user = get_or_create_user(db_session, "clerk-new-user")
    assert user.id is not None
    assert get_or_create_user(db_session, "clerk-new-user").id == user.id


def test_losing_the_creation_race_returns_the_winners_user(db_session, monkeypatch):
    # The winning request's row exists (committed), but this request looked
    # before it did: its lookup found nothing, so it tries to insert too.
    winner = models.User(clerk_user_id="clerk-raced-user")
    db_session.add(winner)
    db_session.commit()

    real_query = db_session.query
    lookups = []

    def query(*args, **kwargs):
        lookups.append(args)
        if len(lookups) == 1:  # the stale "not found" lookup
            return MagicMock(filter=lambda *a: MagicMock(first=lambda: None))
        return real_query(*args, **kwargs)

    monkeypatch.setattr(db_session, "query", query)

    assert get_or_create_user(db_session, "clerk-raced-user").id == winner.id
