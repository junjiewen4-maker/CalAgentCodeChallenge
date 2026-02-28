"""
Cal.com AI chatbot using OpenAI function calling.

This module defines the tool schemas and the CalChatbot class that drives
multi-turn conversations with an OpenAI model, dispatching cal.com API
calls whenever the model invokes a tool.
"""
import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

import cal_api
import timezone_utils

_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[a-z]{2,})+", re.IGNORECASE)
_NAME_RE = re.compile(
    r"(?:i['']?m|my name is|this is|call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
    re.IGNORECASE,
)

load_dotenv()

# ---------------------------------------------------------------------------
# OpenAI tool (function) definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_event_types",
            "description": (
                "List all event types available for booking on cal.com. "
                "Call this first when the user wants to book a meeting so they "
                "can choose the correct event type."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_available_slots",
            "description": (
                "Retrieve available time slots for a specific cal.com event type "
                "within a date/time range. Use this after the user has chosen an "
                "event type and specified when they want to meet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type_id": {
                        "type": "integer",
                        "description": "The numeric ID of the event type.",
                    },
                    "start_time": {
                        "type": "string",
                        "description": (
                            "Start of the search window as a date string in YYYY-MM-DD format, "
                            "e.g. 2024-01-15"
                        ),
                    },
                    "end_time": {
                        "type": "string",
                        "description": (
                            "End of the search window as a date string in YYYY-MM-DD format "
                            "(exclusive upper bound), e.g. 2024-01-21"
                        ),
                    },
                    "time_zone": {
                        "type": "string",
                        "description": (
                            "IANA timezone of the attendee, e.g. America/New_York or America/Los_Angeles. "
                            "Slots are returned in this timezone so the times match the attendee's local clock. "
                            "Always pass this so the attendee's requested time (e.g. '2pm') can be matched directly."
                        ),
                    },
                },
                "required": ["event_type_id", "start_time", "end_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_booking",
            "description": (
                "Create a new cal.com booking. Only call this once all required "
                "details have been gathered from the user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type_id": {
                        "type": "integer",
                        "description": "ID of the event type to book.",
                    },
                    "start": {
                        "type": "string",
                        "description": "Meeting start time in ISO 8601 format.",
                    },
                    "attendee_name": {
                        "type": "string",
                        "description": "Full name of the attendee.",
                    },
                    "attendee_email": {
                        "type": "string",
                        "description": "Email address of the attendee.",
                    },
                    "attendee_timezone": {
                        "type": "string",
                        "description": (
                            "IANA timezone of the attendee, e.g. America/New_York or UTC."
                        ),
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional meeting notes or agenda.",
                    },
                },
                "required": [
                    "event_type_id",
                    "start",
                    "attendee_name",
                    "attendee_email",
                    "attendee_timezone",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_bookings",
            "description": (
                "Retrieve the calendar owner's bookings. Always pass status='upcoming' by default "
                "unless the user explicitly asks for past or cancelled bookings. "
                "Only pass attendee_email to find bookings for a specific external "
                "attendee — do NOT pass the owner's own email as a filter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "attendee_email": {
                        "type": "string",
                        "description": (
                            "Only set this to filter bookings by a specific external attendee's email. "
                            "Leave unset when listing the owner's own bookings."
                        ),
                    },
                    "status": {
                        "type": "string",
                        "enum": ["upcoming", "past", "cancelled"],
                        "description": (
                            "Filter by booking status. Default to 'upcoming' unless the user "
                            "specifically asks for past or cancelled bookings."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_booking",
            "description": (
                "Cancel an existing cal.com booking by its UID. "
                "First list bookings to find the correct UID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_uid": {
                        "type": "string",
                        "description": "Unique identifier of the booking to cancel.",
                    },
                    "cancellation_reason": {
                        "type": "string",
                        "description": (
                            "Optional reason for cancellation. "
                            "Do NOT ask the user for this — if they have not already "
                            "provided a reason, omit this field and proceed with "
                            "cancellation immediately."
                        ),
                    },
                },
                "required": ["booking_uid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_booking",
            "description": (
                "Reschedule an existing cal.com booking to a new start time. "
                "First list bookings to find the correct UID, then call "
                "get_available_slots and use the 'u' field of the chosen slot "
                "directly as new_start — do NOT call local_to_utc or construct "
                "the time manually."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_uid": {
                        "type": "string",
                        "description": "Unique identifier of the booking to reschedule.",
                    },
                    "new_start": {
                        "type": "string",
                        "description": (
                            "New start time as a UTC ISO 8601 string. "
                            "Must be the 'u' field taken directly from a slot returned "
                            "by get_available_slots — e.g. '2026-03-05T23:00:00Z'."
                        ),
                    },
                },
                "required": ["booking_uid", "new_start"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "local_to_utc",
            "description": (
                "Convert a user's local date and time to a UTC ISO 8601 string. "
                "ALWAYS call this before create_booking or reschedule_booking to get "
                "the correct UTC start time. Never compute UTC offsets manually."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Local date in YYYY-MM-DD format, e.g. 2026-03-04.",
                    },
                    "time": {
                        "type": "string",
                        "description": "Local time in HH:MM 24-hour format, e.g. 16:00 for 4 PM.",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone of the user, e.g. America/Los_Angeles.",
                    },
                },
                "required": ["date", "time", "timezone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "utc_to_local",
            "description": (
                "Convert a UTC ISO 8601 datetime (as returned by the Cal.com API) "
                "to the user's local timezone for display. Always call this when "
                "showing booking times back to the user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "utc_iso": {
                        "type": "string",
                        "description": "UTC datetime string from the API, e.g. 2026-03-05T00:00:00.000Z.",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone to convert into, e.g. America/Los_Angeles.",
                    },
                },
                "required": ["utc_iso", "timezone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_date",
            "description": (
                "Resolve a relative day reference (today, tomorrow, day after tomorrow, "
                "yesterday, N days from now, etc.) to an exact YYYY-MM-DD date in the "
                "user's local timezone. ALWAYS call this instead of calculating dates "
                "yourself whenever the user uses a relative expression like 'tomorrow', "
                "'next week', 'in 3 days', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "offset_days": {
                        "type": "integer",
                        "description": (
                            "Number of days from today: 0 = today, 1 = tomorrow, "
                            "2 = day after tomorrow, -1 = yesterday, 7 = one week from today, etc."
                        ),
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone of the user, e.g. America/Los_Angeles.",
                    },
                },
                "required": ["offset_days", "timezone"],
            },
        },
    },
]

# Map tool names to cal_api functions
_TOOL_DISPATCH = {
    "list_event_types": cal_api.list_event_types,
    "get_available_slots": cal_api.get_available_slots,
    "create_booking": cal_api.create_booking,
    "list_bookings": cal_api.list_bookings,
    "cancel_booking": cal_api.cancel_booking,
    "reschedule_booking": cal_api.reschedule_booking,
    "local_to_utc": timezone_utils.local_to_utc,
    "utc_to_local": timezone_utils.utc_to_local,
    "resolve_date": timezone_utils.resolve_date,
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a helpful calendar assistant for cal.com.

You can help the user with:
1. **Booking a new meeting** – list event types, check available slots, then create the booking.
2. **Viewing scheduled events** – list bookings filtered by the user's email.
3. **Cancelling a booking** – find the booking by listing events, then cancel it.
4. **Rescheduling a booking** – find the booking, check new slot availability, then reschedule.

Guidelines:
- **Input format**: Accept user input in ANY natural format — plain sentences, casual phrasing, mixed formats, etc. Never instruct the user to follow a rigid format (e.g. never say "send me: the event type number, date in YYYY-MM-DD, time in HH:MM…"). Interpret and convert whatever they provide.
- **Dates & times**: The user may say things like "3pm", "tomorrow afternoon", "March 5th at 2", "next Monday morning", "in 2 days at noon", etc. Parse and convert these naturally.
- **Timezone**: Default to America/Los_Angeles. Before proceeding with any booking, confirm with the user: "I'll use America/Los_Angeles as your timezone — is that correct?" If they confirm or don't object, use it. If they specify a different timezone, use that instead. Never ask for timezone again after it is confirmed or known.
- Always gather all required information before calling an API function. If anything is missing, ask for ALL missing details in a single conversational message — never ask one field at a time.
- When booking: you need event type, date, time, attendee name, and attendee email. Never use placeholders like "User" or "user@example.com".
  - ALWAYS call list_event_types first when booking, then present the results as a friendly numbered list. Never describe event types abstractly — always show the actual available options from the API.
  - Ask for any other missing details (date, time, name, email) together in the same message, conversationally.
  - Self-booking (user books for themselves): use name/email from Known user info. Ask only for whatever is missing.
  - Booking for someone else: ask for that person's name and email only.
- If the requested time slot is available, book it immediately — no confirmation needed.
- When listing, cancelling, or rescheduling the user's own bookings: call list_bookings with no attendee_email filter — the API key already authenticates as the calendar owner and returns all their bookings. Never pass the owner's email as a filter.
- If the user's name, email, or timezone are listed under "Known user info" below, use them directly — never ask for them again.
- Present results in a clear, readable format (use lists and tables when helpful).
- Never show booking UIDs to the user. Use UIDs only internally for API calls (cancel, reschedule).
- When cancelling: confirm which booking to cancel, then cancel immediately — do NOT ask for a cancellation reason; only include it if the user already volunteered one.
- When rescheduling: confirm the new time with the user before executing.
- When confirming a completed booking, refer to it by event type name only (e.g., "Secret meeting booked for March 10 at 2 PM PST") — do not repeat the verbose auto-generated Cal.com title like "Secret meeting between Jay and Jay".
- If an API call fails, explain the issue and suggest alternatives.
- If a requested time slot is not available, explain why in terms the user understands: tell them what hours the host is available in the user's local timezone, and suggest the nearest available slot. Never just say "that slot is unavailable" without context.
- Slot times returned by get_available_slots are already in the attendee's local timezone. If no slot matches the user's requested time, it means the host's calendar does not cover that local time (e.g., the host may be in a different timezone and only works certain hours).
- TIMEZONE RULE: Never calculate UTC offsets in your head. Always use the local_to_utc tool to convert user times before booking, and utc_to_local to convert API timestamps before displaying them to the user.
- DATE RULE: Never calculate relative dates in your head. Whenever the user says "today", "tomorrow", "the day after tomorrow", "next Monday", "in 3 days", etc., call the resolve_date tool with the appropriate offset_days and the user's timezone to get the exact date.

Today's date and time (UTC): {now}
{profile_section}"""


# ---------------------------------------------------------------------------
# Chatbot class
# ---------------------------------------------------------------------------


class CalChatbot:
    """Stateful multi-turn chatbot backed by OpenAI function calling."""

    def __init__(self, model: str = "gpt-5.2") -> None:
        self.model = model
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.user_profile: dict = {"timezone": "America/Los_Angeles"}  # default timezone
        self.history: list[dict] = []
        self._refresh_system_message()

    def _build_system_content(self) -> str:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        lines = []
        if self.user_profile.get("name"):
            lines.append(f"- Name: {self.user_profile['name']}")
        if self.user_profile.get("email"):
            lines.append(f"- Email: {self.user_profile['email']}")
        if self.user_profile.get("timezone"):
            lines.append(f"- Timezone: {self.user_profile['timezone']}")
        profile_section = (
            "\nKnown user info (do NOT ask for these again):\n" + "\n".join(lines) + "\n"
            if lines else ""
        )
        return _SYSTEM_PROMPT.format(now=now, profile_section=profile_section)

    def _refresh_system_message(self) -> None:
        content = self._build_system_content()
        if self.history:
            self.history[0]["content"] = content
        else:
            self.history = [{"role": "system", "content": content}]

    def _update_profile_from_message(self, message: str) -> None:
        """Extract email and name from free-text user messages."""
        match = _EMAIL_RE.search(message)
        if match:
            self.user_profile.setdefault("email", match.group(0))
        match = _NAME_RE.search(message)
        if match:
            self.user_profile.setdefault("name", match.group(1))

    def _update_profile_from_tool_args(self, fn_name: str, fn_args: dict) -> None:
        """Cache name/email/timezone seen in tool call arguments."""
        if fn_name == "create_booking":
            if fn_args.get("attendee_name"):
                self.user_profile.setdefault("name", fn_args["attendee_name"])
            if fn_args.get("attendee_email"):
                self.user_profile.setdefault("email", fn_args["attendee_email"])
            if fn_args.get("attendee_timezone"):
                self.user_profile.setdefault("timezone", fn_args["attendee_timezone"])
        elif fn_name in ("get_available_slots", "local_to_utc", "utc_to_local"):
            tz = fn_args.get("time_zone") or fn_args.get("timezone")
            if tz:
                self.user_profile.setdefault("timezone", tz)

    def reset(self) -> None:
        """Clear conversation history and cached user profile."""
        self.user_profile = {}
        self.history = []
        self._refresh_system_message()

    def chat(self, user_message: str) -> str:
        """
        Send a user message and return the assistant's reply.

        Handles multi-step tool calls transparently: the method keeps
        sending messages to the model until it produces a plain text response.
        """
        self._update_profile_from_message(user_message)
        self._refresh_system_message()
        self.history.append({"role": "user", "content": user_message})

        while True:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                tools=TOOLS,
                tool_choice="auto",
            )

            message = response.choices[0].message
            # Append the raw assistant turn (may contain tool_calls)
            self.history.append(message)

            if not message.tool_calls:
                # Plain text reply – we're done
                return message.content or ""

            # Execute each requested tool call
            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)

                self._update_profile_from_tool_args(fn_name, fn_args)

                try:
                    fn = _TOOL_DISPATCH.get(fn_name)
                    if fn is None:
                        result = {"error": f"Unknown tool: {fn_name}"}
                    else:
                        result = fn(**fn_args)
                except Exception as exc:  # noqa: BLE001
                    error_msg = str(exc)
                    if hasattr(exc, "response") and exc.response is not None:
                        try:
                            error_msg = exc.response.json()
                        except Exception:
                            error_msg = exc.response.text
                    result = {"error": error_msg}

                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    }
                )
            # Loop back to get the model's next response after tool results


# ---------------------------------------------------------------------------
# Simple CLI for quick local testing
# ---------------------------------------------------------------------------

def _run_cli() -> None:
    print("Cal.com AI Assistant  (type 'quit' or 'exit' to stop, 'reset' to clear history)")
    print("-" * 60)
    bot = CalChatbot()
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit"}:
            print("Goodbye!")
            break
        if user_input.lower() == "reset":
            bot.reset()
            print("Conversation reset.\n")
            continue

        reply = bot.chat(user_input)
        print(f"\nAssistant: {reply}\n")


if __name__ == "__main__":
    _run_cli()
