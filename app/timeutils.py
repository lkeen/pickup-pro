"""Time handling.

Everything is stored as TIMESTAMPTZ and handled in UTC. Local time exists only
at the edges: a form submits a wall-clock time and a page renders one back.

A wall-clock time means nothing until it is anchored to a zone, and the zone
that matters is the person's: someone in New York typing 19:00 means 19:00 in
New York. The browser reports its IANA zone (static/js/timezone.js), with the
form for input and in a cookie for display. APP_TIMEZONE is the fallback when
the browser has not said, such as with JavaScript off or on a first visit.
"""

from datetime import UTC, datetime, timedelta
from datetime import time as time_of_day
from zoneinfo import ZoneInfo

from flask import current_app, has_request_context, request

# Set by static/js/timezone.js.
TIMEZONE_COOKIE = "tz"

# The longest IANA name is about 30 characters. Anything far past that is not
# one, so there is no reason to hand it to the zone loader.
_MAX_ZONE_NAME = 64


def utcnow():
    """Timezone-aware current time."""
    return datetime.now(UTC)


def app_timezone():
    name = current_app.config.get("APP_TIMEZONE", "UTC")
    try:
        return ZoneInfo(name)
    except Exception:
        current_app.logger.warning("Unknown APP_TIMEZONE %r; falling back to UTC", name)
        return UTC


def resolve_timezone(name):
    """The zone for an IANA name supplied by a client, or None if it is not one.

    The name comes from the browser, so it is untrusted: an unknown key, a
    path, or an empty string all come back as None rather than raising.
    """
    if not name or len(name) > _MAX_ZONE_NAME:
        return None
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        # ZoneInfoNotFoundError is a KeyError; path-like keys raise ValueError;
        # a key naming a directory in the zone database can raise OSError.
        return None


def viewer_timezone():
    """The zone to show times in: the browser's if it has said, else APP_TIMEZONE."""
    if has_request_context():
        zone = resolve_timezone(request.cookies.get(TIMEZONE_COOKIE))
        if zone is not None:
            return zone
    return app_timezone()


def to_utc(naive_local, zone=None):
    """Interpret a naive wall-clock time in ``zone`` (default APP_TIMEZONE), return UTC."""
    if naive_local is None:
        return None
    if naive_local.tzinfo is not None:
        return naive_local.astimezone(UTC)
    return naive_local.replace(tzinfo=zone or app_timezone()).astimezone(UTC)


def local_day(date, zone=None):
    """The UTC bounds [start, end) of calendar day ``date`` in ``zone``.

    None when the day cannot be expressed as UTC instants, which happens at the
    very ends of the calendar (year 1 ahead of UTC, year 9999 behind it).
    """
    try:
        start = to_utc(datetime.combine(date, time_of_day.min), zone)
        end = to_utc(datetime.combine(date + timedelta(days=1), time_of_day.min), zone)
    except OverflowError:
        return None
    return start, end


def to_local(aware_utc, zone=None):
    """Render a stored instant as wall-clock in ``zone`` (default APP_TIMEZONE)."""
    if aware_utc is None:
        return None
    if aware_utc.tzinfo is None:
        aware_utc = aware_utc.replace(tzinfo=UTC)
    return aware_utc.astimezone(zone or app_timezone())
