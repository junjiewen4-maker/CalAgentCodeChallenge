"""
Streamlit web UI for the Cal.com AI chatbot.

Run with:
    streamlit run app.py
"""
import os

import streamlit as st
from dotenv import load_dotenv

from chatbot import CalChatbot

load_dotenv()

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Cal.com AI Assistant",
    page_icon="📅",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "chatbot" not in st.session_state:
    st.session_state.chatbot = CalChatbot()

if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("📅 Cal.com Assistant")
    st.markdown(
        "An AI-powered chatbot that manages your **cal.com** bookings using "
        "OpenAI function calling."
    )
    st.divider()

    st.subheader("What I can do")
    st.markdown(
        "- 📅 **Book** a new meeting\n"
        "- 📋 **List** your scheduled events\n"
        "- ❌ **Cancel** a booking\n"
        "- 🔄 **Reschedule** a meeting\n"
    )
    st.divider()

    if st.button("🗑️ Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.chatbot.reset()
        st.rerun()

    st.caption("Powered by cal.com API & OpenAI gpt-5.2")

# ---------------------------------------------------------------------------
# Main chat area
# ---------------------------------------------------------------------------

st.header("Chat")

# Render existing messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Welcome message on first load
if not st.session_state.messages:
    with st.chat_message("assistant"):
        welcome = (
            "Hello! I'm your Cal.com AI assistant. I can help you book, view, cancel, or reschedule meetings.\n\n"
            "Just tell me what you'd like to do in your own words — for example:\n"
            "- \"Book a meeting for next Tuesday at 3pm\"\n"
            "- \"Show my upcoming events\"\n"
            "- \"Cancel my meeting on Friday\"\n\n"
            "What would you like to do today?"
        )
        st.markdown(welcome)

# Chat input
if user_input := st.chat_input("Type your message…"):
    # Show user message immediately
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

    # Get and display the assistant reply
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                reply = st.session_state.chatbot.chat(user_input)
            except Exception as exc:  # noqa: BLE001
                reply = f"An error occurred: {exc}"
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
