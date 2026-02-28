"""
FastAPI REST server for the Cal.com AI chatbot.

Endpoints
---------
GET  /                       – health check
POST /chat                   – send a message; returns the assistant reply
DELETE /sessions/{session_id} – reset (clear) a conversation session

Session management
------------------
Each caller can maintain a separate conversation by passing a unique
`session_id` in the request body.  If none is provided the request is
handled in the shared "default" session.

Usage example
-------------
# Start the server
python server.py

# Send a message
curl -X POST http://localhost:8000/chat \\
     -H "Content-Type: application/json" \\
     -d '{"message": "Show my upcoming meetings", "session_id": "user-123"}'
"""
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from chatbot import CalChatbot

load_dotenv()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Cal.com AI Chatbot",
    description=(
        "An AI-powered assistant for managing cal.com bookings via "
        "OpenAI function calling."
    ),
    version="1.0.0",
)

# In-memory session store  {session_id -> CalChatbot}
_sessions: dict[str, CalChatbot] = {}


def _get_or_create_session(session_id: str) -> CalChatbot:
    if session_id not in _sessions:
        _sessions[session_id] = CalChatbot()
    return _sessions[session_id]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    session_id: str


class StatusResponse(BaseModel):
    status: str
    message: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_model=StatusResponse)
def health_check() -> StatusResponse:
    return StatusResponse(status="ok", message="Cal.com AI Chatbot is running.")


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """
    Send a message to the chatbot and receive a reply.

    The chatbot maintains conversation history per `session_id`, so
    multi-turn interactions work correctly.
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message must not be empty.")

    bot = _get_or_create_session(request.session_id)
    try:
        reply = bot.chat(request.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChatResponse(response=reply, session_id=request.session_id)


@app.delete("/sessions/{session_id}", response_model=StatusResponse)
def reset_session(session_id: str) -> StatusResponse:
    """Clear the conversation history for the given session."""
    if session_id in _sessions:
        del _sessions[session_id]
    return StatusResponse(
        status="ok", message=f"Session '{session_id}' has been reset."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("server:app", host=host, port=port, reload=True)
