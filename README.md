# CalAgentCodeChallenge

An AI-powered chatbot that lets you manage your [cal.com](https://cal.com) bookings through natural conversation, powered by **OpenAI function calling**.

---

## Features

| Capability | Description |
|---|---|
| Book a meeting | The bot asks for date/time, attendee details, and reason, checks availability, then creates the event |
| List scheduled events | Retrieve upcoming (or past/cancelled) bookings filtered by your e-mail |
| Cancel a booking | Find and cancel the right event based on your email and desired time |
| Reschedule a booking | Move an existing booking to a new available slot |
| Web UI | Interactive Streamlit chat interface (bonus) |
| REST API | FastAPI server so any HTTP client can drive the chatbot |

---

## Architecture

```
Streamlit UI (app.py)  ──┐
                          ├──► chatbot.py (CalChatbot + OpenAI tools) ──► cal_api.py ──► cal.com API v2
REST client             ──┘        │
  via server.py (FastAPI)          └──► OpenAI GPT-4o
```

`chatbot.py` defines six OpenAI tools that map directly to `cal_api.py` functions. The model decides when to call them based on the conversation.

---

## Project structure

```
CalAgentCodeChallenge/
├── cal_api.py        # cal.com API v2 wrapper (bookings, slots, event types)
├── chatbot.py        # OpenAI function-calling chatbot + CLI entry point
├── server.py         # FastAPI REST server
├── app.py            # Streamlit web UI (bonus)
├── requirements.txt
├── .env.example      # Template for environment variables
└── .gitignore
```

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/junjiewen4-maker/CalAgentCodeChallenge
cd CalAgentCodeChallenge
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in the values:

```dotenv
# OpenAI API key – https://platform.openai.com/api-keys
OPENAI_API_KEY=sk-...

# cal.com personal API key – Settings > Developer > API Keys
CAL_API_KEY=cal_...

# (Optional) default email used when listing/cancelling bookings
CAL_USER_EMAIL=you@example.com
```

**How to get your cal.com API key:**
1. Log in to [cal.com](https://app.cal.com)
2. Navigate to **Settings → Developer → API Keys**
3. Create a new key and copy it into `.env`

---

## Running

### Option A – Streamlit web UI (recommended)

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser and start chatting.

### Option B – FastAPI REST server

```bash
python server.py
# or: uvicorn server:app --reload
```

**Health check:**
```bash
curl http://localhost:8000/
```

**Send a message:**
```bash
curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "Show my upcoming meetings", "session_id": "user-1"}'
```

**Reset a session:**
```bash
curl -X DELETE http://localhost:8000/sessions/user-1
```

Interactive Swagger docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Option C – Command-line REPL

```bash
python chatbot.py
```

Type `reset` to clear history, `quit`/`exit` to stop.

---

## Example conversations

**Booking a meeting**
```
You:       I'd like to book a meeting
Assistant: Sure! Let me fetch the available event types first...
           [lists event types]
           Which type would you like, and what date/time works for you?

You:       A 30-minute call, tomorrow afternoon
Assistant: Let me check availability for tomorrow afternoon...
           [shows available slots]
           I found slots at 2:00 PM, 3:00 PM, and 4:00 PM.
           Which would you prefer, and what's your name, email, and timezone?

You:       3 PM, Jane Doe, jane@example.com, America/New_York, to discuss Q1 planning
Assistant: [creates booking]
           Your meeting is confirmed for tomorrow at 3:00 PM ET.
```

**Listing events**
```
You:       Show me my scheduled events
Assistant: What's your email address?
You:       jane@example.com
Assistant: [lists upcoming bookings]
```

**Cancelling a booking**
```
You:       Cancel my event at 3pm today
Assistant: Let me look up your bookings. What's your email?
You:       jane@example.com
Assistant: [finds the booking]
           Found: "30-min call" at 3:00 PM today. Shall I cancel it?
You:       Yes, I have a conflict
Assistant: [cancels booking]
           Done – your 3:00 PM meeting has been cancelled.
```

---

## How OpenAI function calling works here

The chatbot exposes six tools to GPT-4o:

| Tool | Description |
|---|---|
| `list_event_types` | Fetch available event types from cal.com |
| `get_available_slots` | Check open time slots for a given event type and date range |
| `create_booking` | Create a new booking |
| `list_bookings` | List bookings (filterable by email and status) |
| `cancel_booking` | Cancel a booking by UID |
| `reschedule_booking` | Move a booking to a new start time |

GPT-4o decides autonomously when to call these tools and chains multiple calls together (e.g. list → find → cancel) to fulfil the user's request.
