"""
Timezone conversion utilities.

All functions use Python's zoneinfo module to perform exact, DST-aware
conversions so the LLM never has to calculate UTC offsets manually.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_date(offset_days: int, timezone: str) -> dict:
    """
    Return the exact calendar date for a day offset from today in the user's
    local timezone.  Use this whenever the user refers to a relative date
    (today, tomorrow, the day after tomorrow, next Monday, etc.) so that
    Python — not the LLM — determines the correct date.

    Args:
        offset_days: 0 = today, 1 = tomorrow, 2 = day after tomorrow,
                     -1 = yesterday, 7 = one week from today, etc.
        timezone:    IANA timezone string, e.g. "America/Los_Angeles".

    Returns a dict with:
        date         – resolved date in YYYY-MM-DD format
        weekday      – full weekday name, e.g. "Sunday"
        display      – human-readable, e.g. "Sunday, March 1, 2026"
    """
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return {"error": f"Unknown timezone: {timezone!r}. Use an IANA name like America/Los_Angeles."}

    today_local = datetime.now(tz).date()
    target = today_local + timedelta(days=offset_days)

    return {
        "date": target.strftime("%Y-%m-%d"),
        "weekday": target.strftime("%A"),
        "display": target.strftime("%A, %B %-d, %Y"),
    }


def local_to_utc(date: str, time: str, timezone: str) -> dict:
    """
    Convert a user's local date + time to a UTC ISO 8601 string suitable
    for passing directly to create_booking or reschedule_booking.

    Args:
        date:     Local date in YYYY-MM-DD format, e.g. "2026-03-04".
        time:     Local time in HH:MM (24-hour) format, e.g. "16:00" for 4 PM.
        timezone: IANA timezone string, e.g. "America/Los_Angeles".

    Returns a dict with:
        utc_iso      – full ISO 8601 UTC string to pass to the booking API
        utc_date     – UTC date (may differ from local date near midnight)
        utc_time     – UTC time as HH:MM
        local_display – human-readable local time with abbreviation
    """
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return {"error": f"Unknown timezone: {timezone!r}. Use an IANA name like America/Los_Angeles."}

    try:
        dt_local = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except ValueError as exc:
        return {"error": str(exc)}

    dt_utc = dt_local.astimezone(ZoneInfo("UTC"))

    return {
        "utc_iso": dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "utc_date": dt_utc.strftime("%Y-%m-%d"),
        "utc_time": dt_utc.strftime("%H:%M"),
        "local_display": dt_local.strftime(f"%Y-%m-%d %H:%M %Z"),
    }


def utc_to_local(utc_iso: str, timezone: str) -> dict:
    """
    Convert a UTC ISO 8601 datetime (as returned by the Cal.com API) to the
    user's local timezone for display.

    Args:
        utc_iso:  UTC datetime string, e.g. "2026-03-05T00:00:00.000Z".
        timezone: IANA timezone string, e.g. "America/Los_Angeles".

    Returns a dict with:
        local_display – human-readable local datetime with abbreviation
        local_date    – local date in YYYY-MM-DD
        local_time    – local time as HH:MM
    """
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return {"error": f"Unknown timezone: {timezone!r}. Use an IANA name like America/Los_Angeles."}

    try:
        dt_utc = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    except ValueError as exc:
        return {"error": str(exc)}

    dt_local = dt_utc.astimezone(tz)

    return {
        "local_display": dt_local.strftime("%Y-%m-%d %H:%M %Z"),
        "local_date": dt_local.strftime("%Y-%m-%d"),
        "local_time": dt_local.strftime("%H:%M"),
    }
