"""Streamlit chat client for the agentic search backend."""
from __future__ import annotations

from typing import Any

import requests
import streamlit as st

API_BASE_URL = st.secrets.get("api_base_url", "http://localhost:8000")

st.set_page_config(page_title="Agentic Search Chat", layout="wide")
st.title("Agentic Search Chat")


if "messages" not in st.session_state:
    st.session_state.messages: list[dict[str, Any]] = []


@st.cache_data(show_spinner=False)
def fetch_history() -> list[dict[str, Any]]:
    """Load chat history from the backend."""

    response = requests.get(f"{API_BASE_URL}/chat/history", timeout=10)
    response.raise_for_status()
    payload = response.json()
    messages = []
    for message in reversed(payload.get("messages", [])):
        messages.append(
            {
                "user_message": message.get("user_message", ""),
                "assistant_message": message.get("assistant_message", ""),
                "structured_response": message.get("structured_response", {}),
                "sql_results": [],
            }
        )
    return messages


def send_message(message: str, result_limit: int) -> dict[str, Any]:
    """Send a chat message to the backend and return the response."""

    response = requests.post(
        f"{API_BASE_URL}/chat",
        json={"message": message, "result_limit": result_limit},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


with st.sidebar:
    st.header("Configuration")
    result_limit = st.number_input("Result limit", min_value=1, max_value=200, value=10)
    if st.button("Refresh history"):
        try:
            st.session_state.messages = fetch_history()
            st.success("History refreshed")
        except requests.RequestException as exc:  # pragma: no cover - UI feedback
            st.error(f"Unable to load history: {exc}")


if not st.session_state.messages:
    try:
        st.session_state.messages = fetch_history()
    except requests.RequestException as exc:  # pragma: no cover - UI feedback
        st.warning(f"Unable to load history: {exc}")


for message in st.session_state.messages:
    with st.chat_message("user"):
        st.markdown(message["user_message"])
    with st.chat_message("assistant"):
        st.markdown(message["assistant_message"])
        if message["structured_response"].get("sql"):
            st.caption(f"SQL: `{message['structured_response']['sql']}`")
        if message.get("sql_results"):
            st.caption(f"Rows returned: {len(message['sql_results'])}")


if prompt := st.chat_input("Ask about startups..."):
    with st.spinner("Thinking..."):
        try:
            response = send_message(prompt, result_limit)
            st.session_state.messages.append(
                {
                    "user_message": prompt,
                    "assistant_message": response["reply"],
                    "structured_response": {
                        "sql": response["sql"],
                        "enrichment_attributes": response["enrichment_attributes"],
                    },
                    "sql_results": response.get("sql_results", []),
                }
            )
            st.experimental_rerun()
        except requests.RequestException as exc:  # pragma: no cover - UI feedback
            st.error(f"Request failed: {exc}")


st.markdown("---")
st.subheader("Latest SQL Results")
if st.session_state.messages:
    last_message = st.session_state.messages[-1]
    with st.expander("Structured response", expanded=False):
        st.json(last_message["structured_response"])
    st.dataframe(last_message.get("sql_results", []))
    enrichment = last_message["structured_response"].get("enrichment_attributes", [])
    if enrichment:
        st.caption(
            "Enrichment jobs queued: "
            + ", ".join(hint.get("attribute_name", "?") for hint in enrichment)
        )
else:
    st.info("Send a message to see results.")
