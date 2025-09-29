"""Streamlit UI for interacting with the Agentic Search backend."""

from __future__ import annotations

import html
import time
import uuid
from typing import Any, Dict, List

import requests
import streamlit as st

API_BASE_URL = "http://localhost:8001"
CUSTOM_CSS = """
<style>
:root {
    color-scheme: dark;
}

body {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.stApp {
    background: radial-gradient(circle at 20% 20%, rgba(90, 148, 255, 0.18), transparent 45%),
                radial-gradient(circle at 80% 10%, rgba(236, 72, 153, 0.15), transparent 55%),
                #0f172a;
    color: #f8fafc;
}

.block-container {
    padding-top: 2rem !important;
    padding-bottom: 4rem !important;
    max-width: 820px !important;
}

[data-testid="stSidebar"] {
    background: rgba(15, 23, 42, 0.9);
    border-right: 1px solid rgba(148, 163, 184, 0.16);
}

.sidebar-card {
    background: rgba(30, 41, 59, 0.78);
    border-radius: 1.1rem;
    padding: 1.2rem;
    border: 1px solid rgba(148, 163, 184, 0.2);
    color: #e2e8f0;
    margin-bottom: 1.5rem;
}

.sidebar-card h3 {
    margin: 0 0 0.6rem 0;
    font-size: 1rem;
    font-weight: 600;
}

.sidebar-card p {
    margin: 0 0 0.6rem 0;
    font-size: 0.92rem;
    color: rgba(226, 232, 240, 0.78);
    line-height: 1.4;
}

.sidebar-card .pill {
    display: inline-flex;
    padding: 0.25rem 0.55rem;
    border-radius: 999px;
    border: 1px solid rgba(148, 163, 184, 0.25);
    margin: 0 0.35rem 0.35rem 0;
    font-size: 0.78rem;
    background: rgba(96, 165, 250, 0.18);
    color: #dbeafe;
}

.sidebar-tip {
    font-size: 0.82rem;
    color: rgba(148, 163, 184, 0.8);
    margin-top: 0.8rem;
}

.hero-card {
    padding: 1.5rem 1.8rem;
    border-radius: 1.5rem;
    background: rgba(30, 41, 59, 0.7);
    border: 1px solid rgba(148, 163, 184, 0.22);
    backdrop-filter: blur(14px);
    margin-bottom: 1.8rem;
}

.hero-card h1 {
    font-size: clamp(1.9rem, 2.4vw, 2.4rem);
    margin: 0 0 0.4rem 0;
    font-weight: 700;
}

.hero-card p {
    margin: 0;
    font-size: 0.98rem;
    color: rgba(226, 232, 240, 0.82);
    line-height: 1.55;
}

.chat-bubble {
    padding: 0.85rem 1.1rem;
    border-radius: 1.2rem;
    line-height: 1.55;
    border: 1px solid rgba(148, 163, 184, 0.18);
    box-shadow: 0 10px 28px rgba(15, 23, 42, 0.22);
    backdrop-filter: blur(6px);
    font-size: 0.98rem;
}

.chat-bubble.user-bubble {
    background: linear-gradient(135deg, rgba(125, 211, 252, 0.9), rgba(59, 130, 246, 0.94));
    color: #0b1120;
}

.chat-bubble.assistant-bubble {
    background: rgba(30, 41, 59, 0.72);
    color: #e2e8f0;
}

.payload-block {
    margin-top: 0.7rem;
    padding: 0.75rem 1rem;
    border-radius: 1rem;
    background: rgba(15, 23, 42, 0.7);
    border: 1px solid rgba(148, 163, 184, 0.2);
}

.payload-block strong {
    display: block;
    margin-bottom: 0.35rem;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    font-size: 0.74rem;
    color: rgba(148, 163, 184, 0.86);
}

.payload-block ul {
    padding-left: 1.1rem;
    margin: 0;
}

.sql-pill {
    display: inline-flex;
    align-items: center;
    padding: 0.2rem 0.55rem;
    margin: 0 0.3rem 0.3rem 0;
    border-radius: 999px;
    border: 1px solid rgba(56, 189, 248, 0.4);
    background: rgba(59, 130, 246, 0.18);
    font-size: 0.8rem;
    color: #bae6fd;
}

[data-testid="stDeployButton"] {
    display: none !important;
}

div[data-testid="stToolbar"] {
    display: none !important;
}


.table-block {
    margin-top: 0.75rem;
    border-radius: 1.1rem;
    border: 1px solid rgba(59, 130, 246, 0.28);
    background: rgba(15, 23, 42, 0.78);
    box-shadow: 0 18px 44px rgba(15, 23, 42, 0.45);
    overflow: hidden;
    width: 100%;
}

.table-caption {
    display: block;
    padding: 0.9rem 1.2rem 0 1.2rem;
    color: rgba(191, 219, 254, 0.86);
    font-size: 0.85rem;
    letter-spacing: 0.03em;
    text-transform: uppercase;
}


.table-container {
    overflow-x: auto;
    padding: 0.6rem 1.2rem 1.1rem 1.2rem;
    width: 100%;
}


.table-container table {
    width: 100%;
    min-width: 720px;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.92rem;
}

.table-container thead th {
    position: sticky;
    top: 0;
    z-index: 1;
    background: rgba(37, 99, 235, 0.32);
    color: #f8fafc;
    text-transform: none;
    font-weight: 600;
}

.table-container th,
.table-container td {
    padding: 0.65rem 0.9rem;
    border-bottom: 1px solid rgba(148, 163, 184, 0.24);
    text-align: left;
    color: #f8fafc;
    white-space: nowrap;
}

.table-container td {
    font-weight: 400;
    white-space: normal;
    word-break: break-word;
}

.table-container tbody tr:nth-child(odd) {
    background: rgba(15, 23, 42, 0.68);
}

.table-container tbody tr:nth-child(even) {
    background: rgba(15, 23, 42, 0.58);
}

.table-container tbody tr:hover {
    background: rgba(59, 130, 246, 0.28);
}

[data-testid="stChatMessage"] {
    margin-bottom: 1.2rem;
}

[data-testid="stChatInput"] > div {
    border-radius: 1rem;
    border: 1px solid rgba(148, 163, 184, 0.25);
    background: rgba(15, 23, 42, 0.82);
    box-shadow: 0 10px 26px rgba(15, 23, 42, 0.32);
}

[data-testid="stChatInput"] div[data-baseweb="input"] {
    background: transparent !important;
}

[data-testid="stChatInput"] div[data-baseweb="input"] > div {
    background: transparent !important;
}

[data-testid="stChatInput"] textarea {
    color: #e2e8f0 !important;
    font-size: 0.95rem !important;
    background: transparent !important;
    caret-color: #60a5fa !important;
}

[data-testid="stChatInput"] textarea::placeholder {
    color: rgba(148, 163, 184, 0.78) !important;
}

button[kind="primary"], button[kind="secondary"] {
    border-radius: 0.9rem !important;
    border: 1px solid rgba(148, 163, 184, 0.25) !important;
}
</style>
"""


def initialize_session_state() -> None:
    if "conversation_id" not in st.session_state:
        st.session_state.conversation_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages: List[Dict[str, Any]] = []


def inject_styles() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def render_header() -> None:
    st.markdown(
        """
        <div class="hero-card">
            <h1>SI</h1>
            <p>providing perfect context for your agentic research tasks</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> bool:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-card">
                <h3>Session context</h3>
                <p>Each message keeps building state so the backend can respond with structured notes and suggestions.</p>
                <span class="pill">FastAPI</span>
                <span class="pill">SQLite</span>
                <span class="pill">Gemini 2.5 Flash</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        debug_toggle = st.toggle("Show debug details", value=False)
        if st.button("Reload history", use_container_width=True):
            fetch_history()
        st.markdown(
            "<div class='sidebar-tip'>Responses animate client-side for a quick preview while we wire real streaming.</div>",
            unsafe_allow_html=True,
        )
        return debug_toggle


def append_message(
    role: str,
    content: str,
    payload: Dict[str, Any] | None = None,
    pending: bool = False,
    stream_chunks: List[str] | None = None,
) -> int:
    message = {
        "role": role,
        "content": content,
        "payload": payload,
        "pending": pending,
        "stream_chunks": stream_chunks or [],
    }
    st.session_state.messages.append(message)
    return len(st.session_state.messages) - 1


def chunk_text(text: str, chunk_size: int = 14) -> List[str]:
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def render_bubble(text: str, bubble_class: str) -> str:
    safe_text = text.replace("\n", "<br>")
    return f'<div class="chat-bubble {bubble_class}">{safe_text}</div>'


def display_payload(payload: Dict[str, Any] | None) -> None:
    if not payload:
        return

    summary = payload.get("sql_summary") or payload.get("assistant_message")

    if facts := payload.get("facts"):
        facts_markup = "".join(
            f"<li><strong>{fact.get('source', 'source')}</strong> — {fact.get('text', '')}</li>" for fact in facts
        )
        st.markdown(
            f"<div class='payload-block'><strong>Facts</strong><ul>{facts_markup}</ul></div>",
            unsafe_allow_html=True,
        )

    if suggested_sql := payload.get("suggested_sql_columns"):
        sql_markup = "".join(f"<span class='sql-pill'>{col}</span>" for col in suggested_sql)
        st.markdown(
            f"<div class='payload-block'><strong>Suggested Columns</strong>{sql_markup}</div>",
            unsafe_allow_html=True,
        )

    rows = payload.get("sql_rows")
    if rows:
        caption = None
        if summary:
            caption = summary
            summary = ""
        st.markdown(render_sql_table(rows, caption=caption), unsafe_allow_html=True)
        return

    if summary:
        st.markdown(render_bubble(summary, "assistant-bubble"), unsafe_allow_html=True)


def render_sql_table(rows: List[Dict[str, Any]], caption: str | None = None) -> str:
    if not rows:
        return ""

    columns = [col for col in rows[0].keys() if col.lower() != "description"]
    header_cells = "".join(f"<th>{html.escape(str(col))}</th>" for col in columns)
    body_rows = []
    for row in rows:
        cells = "".join(
            f"<td>{html.escape(str(row.get(col, '')))}</td>" for col in columns
        )
        body_rows.append(f"<tr>{cells}</tr>")
    body_html = "".join(body_rows)
    caption_html = f"<span class='table-caption'>{html.escape(caption)}</span>" if caption else ""
    return (
        "<div class='table-block'>"
        + caption_html
        + "<div class='table-container'><table><thead><tr>"
        + header_cells
        + "</tr></thead><tbody>"
        + body_html
        + "</tbody></table></div></div>"
    )


def render_messages(show_debug: bool = False) -> None:
    avatar_lookup = {"user": "🙂", "assistant": "🤖"}

    for index, message in enumerate(st.session_state.messages):
        role = message.get("role", "assistant")
        content = message.get("content", "")
        payload = message.get("payload") or {}
        pending = message.get("pending", False)
        stream_chunks = message.get("stream_chunks") or []
        bubble_class = "user-bubble" if role == "user" else "assistant-bubble"
        has_sql_rows = bool(payload.get("sql_rows"))
        summary_text = (payload.get("sql_summary") or payload.get("assistant_message") or "").strip()

        with st.chat_message(role, avatar=avatar_lookup.get(role, "💬")):
            if pending:
                st.markdown(render_bubble("Thinking…", bubble_class), unsafe_allow_html=True)
                continue

            if stream_chunks:
                placeholder = st.empty()
                buffer = ""
                for chunk in stream_chunks:
                    buffer += chunk
                    placeholder.markdown(render_bubble(buffer, bubble_class), unsafe_allow_html=True)
                    time.sleep(0.02)
                st.session_state.messages[index]["stream_chunks"] = []
                display_payload(payload)
                if show_debug and role == "assistant":
                    render_debug_block(payload)
                continue

            should_render_bubble = True
            if role == "assistant" and has_sql_rows:
                if not content.strip() or content.strip() == summary_text:
                    should_render_bubble = False

            if should_render_bubble:
                st.markdown(render_bubble(content, bubble_class), unsafe_allow_html=True)
            display_payload(payload)
            if show_debug and role == "assistant":
                render_debug_block(payload)


def render_debug_block(payload: Dict[str, Any]) -> None:
    debug_payload = payload.get("debug") if isinstance(payload, dict) else None
    sql = payload.get("sql") if isinstance(payload, dict) else None
    rows = payload.get("sql_rows") if isinstance(payload, dict) else None

    with st.expander("Debug details", expanded=False):
        if sql:
            st.code(sql, language="sql")
        if rows is not None:
            st.json(rows)
        if debug_payload:
            plan = debug_payload.get("plan")
            if stage := debug_payload.get("stage"):
                st.write(f"**Stage:** {stage}")
            if plan:
                st.markdown("**SQL Plan**")
                st.json(plan)
            result_count = debug_payload.get("result_row_count")
            if result_count is not None:
                st.write(f"Result row count: {result_count}")
        pending_cols = debug_payload.get("pending_columns", [])
        if pending_cols:
            st.write("**Pending columns for enrichment**")
            st.code(", ".join(pending_cols))
            columns_available = debug_payload.get("columns_available", [])
            columns_after = debug_payload.get("columns_after_enrichment", [])
            enrichment_messages = debug_payload.get("enrichment_messages", [])
            enrichment_actions = debug_payload.get("enrichment_actions", [])
            st.write("**Columns (before)**")
            st.code(", ".join(columns_available) or "None")
            st.write("**Columns (after)**")
            st.code(", ".join(columns_after) or "None")
            if enrichment_messages:
                st.write("**Enrichment messages**")
                for msg in enrichment_messages:
                    st.write(f"- {msg}")
            if enrichment_actions:
                st.write("**Enrichment actions**")
                st.json(enrichment_actions)
            if followup := debug_payload.get("followup_gemini"):
                st.write("**Follow-up Gemini payload**")
                st.json(followup)
            if initial := debug_payload.get("initial_gemini"):
                st.write("**Initial Gemini payload**")
                st.json(initial)


def fetch_history() -> None:
    conversation_id = st.session_state.conversation_id
    try:
        resp = requests.get(f"{API_BASE_URL}/conversations/{conversation_id}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            messages = data.get("messages", [])
            for message in messages:
                message.setdefault("payload", {})
                message["pending"] = False
                message["stream_chunks"] = []
            st.session_state.messages = messages
        else:
            st.toast(f"History request failed: {resp.status_code}", icon="⚠️")
    except requests.RequestException as exc:
        st.toast(f"Failed to fetch conversation: {exc}", icon="🚨")


def send_message(conversation_id: str, user_message: str) -> Dict[str, Any]:
    payload = {"conversation_id": conversation_id, "message": user_message}
    resp = requests.post(f"{API_BASE_URL}/chat", json=payload, timeout=90)
    if not resp.ok:
        raise RuntimeError(f"{resp.status_code} {resp.text}")
    return resp.json()


def handle_user_input(user_message: str) -> None:
    append_message("user", user_message, payload=None, pending=False)
    assistant_index = append_message("assistant", "", payload={}, pending=True)

    try:
        with st.spinner("Working on it…"):
            data = send_message(st.session_state.conversation_id, user_message)
    except RuntimeError as exc:
        st.session_state.messages[assistant_index]["content"] = f"Backend error: {exc}"
        st.session_state.messages[assistant_index]["pending"] = False
        st.toast("Backend error. Check server logs.", icon="🚨")
        return

    st.session_state.conversation_id = data.get("conversation_id", st.session_state.conversation_id)
    message = st.session_state.messages[assistant_index]
    message["content"] = data.get("assistant_message", "")
    message["payload"] = data.get("payload") or {}
    message["pending"] = False
    message["stream_chunks"] = chunk_text(message["content"])
    st.session_state.messages[assistant_index] = message


def main() -> None:
    st.set_page_config(page_title="Agentic Search", layout="centered")
    initialize_session_state()
    inject_styles()
    show_debug = render_sidebar()
    render_header()

    user_input = st.chat_input("Ask something…")
    if user_input:
        handle_user_input(user_input)

    render_messages(show_debug=show_debug)


if __name__ == "__main__":
    main()
