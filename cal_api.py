"""
Cal.com API v2 wrapper.

Provides functions to interact with the Cal.com REST API for managing
bookings, event types, and available slots.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from typing import Optional

CAL_BASE_URL = "https://api.cal.com/v2"

# Each endpoint family requires a specific api-version per Cal.com docs.
_VERSION_EVENT_TYPES = "2024-06-14"
_VERSION_SLOTS = "2024-09-04"
_VERSION_BOOKINGS = "2024-08-13"


def _get_headers(api_version: str = _VERSION_BOOKINGS) -> dict:
    api_key = os.environ.get("CAL_API_KEY", "")
    return {
        "Authorization": f"Bearer {api_key}",
        "cal-api-version": api_version,
        "Content-Type": "application/json",
    }


_EVENT_TYPE_KEEP = {"id", "title", "lengthInMinutes", "description"}


def list_event_types() -> dict:
    """Return all event types available for the authenticated user."""
    response = requests.get(
        f"{CAL_BASE_URL}/event-types", headers=_get_headers(_VERSION_EVENT_TYPES)
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data.get("data"), list):
        data["data"] = [
            {k: v for k, v in et.items() if k in _EVENT_TYPE_KEEP}
            for et in data["data"]
        ]
    return data


def get_available_slots(
    event_type_id: int,
    start_time: str,
    end_time: str,
    time_zone: Optional[str] = None,
) -> dict:
    """
    Return available time slots for an event type within the given date range.

    Args:
        event_type_id: ID of the event type to check.
        start_time: Range start as a date string in YYYY-MM-DD format (e.g. 2024-01-15).
        end_time:   Range end   as a date string in YYYY-MM-DD format (e.g. 2024-01-21).
        time_zone:  IANA timezone string (e.g. America/New_York). Slots are returned
                    in this timezone so times match the attendee's local clock.
    """
    # Guard against zero-width windows: if start == end, advance end by 1 day.
    from datetime import date as _date, timedelta as _timedelta
    _start = _date.fromisoformat(start_time)
    _end   = _date.fromisoformat(end_time)
    if _end <= _start:
        _end = _start + _timedelta(days=1)
        end_time = _end.isoformat()

    params: dict = {
        "eventTypeId": event_type_id,
        "start": start_time,
        "end": end_time,
    }
    if time_zone:
        params["timeZone"] = time_zone

    response = requests.get(
        f"{CAL_BASE_URL}/slots",
        headers=_get_headers(_VERSION_SLOTS),
        params=params,
    )
    response.raise_for_status()
    raw = response.json()

    # Build compact slot list. Each slot is {"t": "<local HH:MM>", "u": "<UTC ISO>"}.
    # Cal.com returns start times with local timezone offsets, e.g. "2026-03-01T14:00:00.000-08:00".
    # We must explicitly convert to UTC before formatting, otherwise strftime produces the
    # local wall time labelled as "Z" (wrong).
    # "t" is for display; "u" must be passed directly to create_booking as `start`.
    tz_obj = None
    if time_zone:
        try:
            tz_obj = ZoneInfo(time_zone)
        except ZoneInfoNotFoundError:
            pass  # fall back to raw UTC extraction

    utc_zone = ZoneInfo("UTC")
    compacted: dict = {}
    for date_key, slots in raw.get("data", {}).items():
        # Cal.com interprets start/end as UTC but returns date keys in local timezone,
        # causing UTC-bleed keys outside the requested local-date range.  Filter them out.
        try:
            key_date = _date.fromisoformat(date_key)
        except ValueError:
            continue
        if not (_start <= key_date < _end):
            continue

        entries = []
        for s in slots:
            dt = datetime.fromisoformat(s["start"].replace("Z", "+00:00"))
            dt_utc = dt.astimezone(utc_zone)          # always true UTC
            local_hm = (
                dt.astimezone(tz_obj).strftime("%H:%M") if tz_obj
                else dt_utc.strftime("%H:%M")
            )
            utc_iso = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            entries.append({"t": local_hm, "u": utc_iso})
        compacted[date_key] = entries

    return {
        "status": raw.get("status"),
        "timezone": time_zone or "UTC",
        "note": (
            "Each slot has 't' (local display time) and 'u' (UTC ISO for booking). "
            "Pass 'u' directly as the 'start' parameter to create_booking — "
            "do NOT call local_to_utc for slot times."
        ),
        "data": compacted,
    }


def create_booking(
    event_type_id: int,
    start: str,
    attendee_name: str,
    attendee_email: str,
    attendee_timezone: str,
    notes: Optional[str] = None,
) -> dict:
    """
    Create a new booking.

    Args:
        event_type_id:       Event type to book.
        start:               ISO 8601 start time.
        attendee_name:       Full name of the attendee.
        attendee_email:      Email address of the attendee.
        attendee_timezone:   IANA timezone string (e.g. America/New_York).
        notes:               Optional meeting notes / reason.
    """
    payload: dict = {
        "eventTypeId": event_type_id,
        "start": start,
        "attendee": {
            "name": attendee_name,
            "email": attendee_email,
            "timeZone": attendee_timezone,
        },
    }
    if notes:
        payload["bookingFieldsResponses"] = {"notes": notes}

    response = requests.post(
        f"{CAL_BASE_URL}/bookings", headers=_get_headers(), json=payload
    )
    response.raise_for_status()
    return response.json()


def list_bookings(
    attendee_email: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """
    Return bookings, optionally filtered by attendee e-mail and/or status.

    Args:
        attendee_email: Filter to bookings where this address is an attendee.
        status:         One of "upcoming", "past", or "cancelled".
    """
    params: dict = {}
    if attendee_email:
        params["attendeeEmail"] = attendee_email
    if status:
        params["status"] = status

    response = requests.get(
        f"{CAL_BASE_URL}/bookings", headers=_get_headers(), params=params
    )
    response.raise_for_status()
    data = response.json()
    _BOOKING_STRIP = {"meetingUrl", "location", "metadata", "icsUid", "bookingFieldsResponses",
                      "absentHost", "rating", "description", "cancelledByEmail",
                      "rescheduledByEmail", "hosts"}
    if isinstance(data.get("data"), list):
        data["data"] = [
            {k: v for k, v in b.items() if k not in _BOOKING_STRIP}
            for b in data["data"]
        ]
    return data


def cancel_booking(
    booking_uid: str, cancellation_reason: Optional[str] = None
) -> dict:
    """
    Cancel a booking identified by its UID.

    Args:
        booking_uid:          Unique identifier of the booking.
        cancellation_reason:  Optional human-readable reason for cancellation.
    """
    payload: dict = {}
    if cancellation_reason:
        payload["cancellationReason"] = cancellation_reason

    response = requests.post(
        f"{CAL_BASE_URL}/bookings/{booking_uid}/cancel",
        headers=_get_headers(),
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def reschedule_booking(
    booking_uid: str,
    new_start: str,
    rescheduled_by: Optional[str] = None,
) -> dict:
    """
    Reschedule an existing booking to a new start time.

    Args:
        booking_uid:     Unique identifier of the booking.
        new_start:       New ISO 8601 start time.
        rescheduled_by:  Optional email address of the person rescheduling.
    """
    payload: dict = {"start": new_start}
    if rescheduled_by:
        payload["rescheduledBy"] = rescheduled_by
    response = requests.post(
        f"{CAL_BASE_URL}/bookings/{booking_uid}/reschedule",
        headers=_get_headers(),
        json=payload,
    )
    response.raise_for_status()
    return response.json()
