"""Time handling.

Everything is stored as TIMESTAMPTZ and handled in UTC internally. The only
place a local time exists is at the edges: a form submits a wall-clock time
("Saturday 6pm") and a page renders one back.

A game's time is wall-clock at the court, so interpreting it needs a timezone.
Per-court timezones would be the fully correct model -- derivable from the
coordinates now that PostGIS is here -- but this app serves one metro area at a
time, so a single configured zone is the honest simplification. APP_TIMEZONE is
the knob.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from flask import current_app


def utcnow():
    """Timezone-aware current time.

    datetime.now() returns naive *local* time, which then gets compared against
    values that mean something else. datetime.utcnow() is worse: it returns a
    naive datetime holding UTC, so it looks local and is not.
    """
    return datetime.now(UTC)


def app_timezone():
    name = current_app.config.get("APP_TIMEZONE", "UTC")
    try:
        return ZoneInfo(name)
    except Exception:
        current_app.logger.warning("Unknown APP_TIMEZONE %r; falling back to UTC", name)
        return UTC


def to_utc(naive_local):
    """Interpret a naive wall-clock time in the app timezone, return UTC."""
    if naive_local is None:
        return None
    if naive_local.tzinfo is not None:
        return naive_local.astimezone(UTC)
    return naive_local.replace(tzinfo=app_timezone()).astimezone(UTC)


def to_local(aware_utc):
    """Render a stored instant back as wall-clock in the app timezone."""
    if aware_utc is None:
        return None
    if aware_utc.tzinfo is None:
        aware_utc = aware_utc.replace(tzinfo=UTC)
    return aware_utc.astimezone(app_timezone())
