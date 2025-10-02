"""Streamlit UI for interacting with the Agentic Search backend."""

from __future__ import annotations

import html
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = "http://localhost:8000"
LOG_FILE_PATH = Path(__file__).resolve().parent.parent / "logs" / "chat_runs.jsonl"
CUSTOM_CSS = """
<style>
body {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.stApp {
    background: radial-gradient(circle at 12% 18%, rgba(186, 230, 253, 0.45), transparent 42%),
                radial-gradient(circle at 88% 14%, rgba(244, 215, 255, 0.4), transparent 58%),
                linear-gradient(180deg, #f9fbfe 0%, #eef2fb 60%, #e6ecfb 100%);
    color: #1f2a44;
}

.block-container {
    padding-top: 2rem !important;
    padding-bottom: 4rem !important;
    max-width: 820px !important;
}

[data-testid="stSidebar"] {
    background: rgba(255, 255, 255, 0.92);
    border-right: 1px solid rgba(203, 213, 225, 0.6);
}

.sidebar-card {
    background: linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(236, 244, 255, 0.94));
    border-radius: 1.2rem;
    padding: 1.3rem;
    border: 1px solid rgba(148, 163, 184, 0.2);
    color: #374151;
    margin-bottom: 1.6rem;
    box-shadow: 0 20px 38px rgba(15, 23, 42, 0.12);
}

.sidebar-card h3 {
    margin: 0 0 0.6rem 0;
    font-size: 1rem;
    font-weight: 600;
}

.sidebar-card p {
    margin: 0 0 0.7rem 0;
    font-size: 0.93rem;
    color: rgba(71, 85, 105, 0.88);
    line-height: 1.55;
}

.sidebar-card .pill {
    display: inline-flex;
    padding: 0.25rem 0.55rem;
    border-radius: 999px;
    border: 1px solid rgba(59, 130, 246, 0.25);
    margin: 0 0.35rem 0.35rem 0;
    font-size: 0.78rem;
    background: rgba(191, 219, 254, 0.42);
    color: #1d4ed8;
}

.sidebar-tip {
    font-size: 0.82rem;
    color: rgba(99, 115, 132, 0.82);
    margin-top: 0.85rem;
}

.hero-card {
    padding: 1.8rem 2.3rem;
    border-radius: 1.8rem;
    background: linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(242, 248, 255, 0.94));
    border: 1px solid rgba(203, 213, 225, 0.55);
    backdrop-filter: blur(12px);
    margin-bottom: 2.1rem;
    box-shadow: 0 28px 50px rgba(15, 23, 42, 0.18);
}

.hero-card h1 {
    font-size: clamp(2.1rem, 3vw, 2.8rem);
    margin: 0 0 0.55rem 0;
    font-weight: 700;
    color: #0f172a;
}

.hero-card p {
    margin: 0;
    font-size: 1rem;
    color: rgba(71, 85, 105, 0.85);
    line-height: 1.65;
}

.chat-bubble {
    padding: 0.85rem 1.1rem;
    border-radius: 1.2rem;
    line-height: 1.55;
    border: 1px solid rgba(203, 213, 225, 0.6);
    box-shadow: 0 20px 34px rgba(148, 163, 184, 0.18);
    backdrop-filter: blur(6px);
    font-size: 1rem;
}

.chat-bubble.user-bubble {
    background: linear-gradient(135deg, rgba(219, 234, 254, 0.95), rgba(191, 219, 254, 0.95));
    color: #1d4ed8;
}

.chat-bubble.assistant-bubble {
    background: rgba(255, 255, 255, 0.94);
    color: #1f2937;
}

.payload-block {
    margin-top: 0.7rem;
    padding: 0.75rem 1rem;
    border-radius: 1.1rem;
    background: rgba(255, 255, 255, 0.96);
    border: 1px solid rgba(203, 213, 225, 0.6);
}

.payload-block strong {
    display: block;
    margin-bottom: 0.35rem;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    font-size: 0.75rem;
    color: rgba(59, 130, 246, 0.8);
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
    border: 1px solid rgba(59, 130, 246, 0.35);
    background: rgba(191, 219, 254, 0.5);
    font-size: 0.8rem;
    color: #1d4ed8;
}

[data-testid="stDeployButton"] {
    display: none !important;
}

div[data-testid="stToolbar"] {
    display: none !important;
}


/* Table styles are now handled inline with Streamlit dataframes */

[data-testid="stChatMessage"] {
    margin-bottom: 1.2rem;
}

[data-testid="stChatInput"] > div {
    border-radius: 1rem;
    border: 1px solid rgba(203, 213, 225, 0.6);
    background: rgba(255, 255, 255, 0.98);
    box-shadow: 0 16px 36px rgba(15, 23, 42, 0.18);
}

[data-testid="stChatInput"] > div {
    border-radius: 1rem;
    border: 1px solid rgba(203, 213, 225, 0.6);
    background: rgba(255, 255, 255, 0.95);
    box-shadow: 0 16px 36px rgba(15, 23, 42, 0.16);
}

[data-testid="stChatInput"] div[data-baseweb="textarea"] {
    background: rgba(255, 255, 255, 0.95) !important;
    border-radius: 0.75rem !important;
}

[data-testid="stChatInput"] textarea {
    color: #0f172a !important;
    font-size: 0.97rem !important;
    background: rgba(255, 255, 255, 0.98) !important;
    caret-color: #2563eb !important;
}

[data-testid="stChatInput"] textarea::placeholder {
    color: rgba(107, 114, 128, 0.68) !important;
}

[data-testid="stChatInput"] button {
    background: linear-gradient(135deg, #2563eb, #4f46e5) !important;
    color: #fff !important;
    border-radius: 0.8rem !important;
}

[data-testid="stChatInput"] textarea::placeholder {
    color: rgba(99, 115, 132, 0.65) !important;
}

button[kind="primary"], button[kind="secondary"] {
    border-radius: 0.9rem !important;
    border: 1px solid rgba(148, 163, 184, 0.35) !important;
}

[data-testid="stTabs"] button[role="tab"] {
    background: rgba(255, 255, 255, 0.85) !important;
    border: none !important;
    border-radius: 0.9rem 0.9rem 0 0 !important;
    margin-right: 0.4rem !important;
    padding: 0.75rem 1.6rem !important;
    font-size: 1.05rem !important;
    font-weight: 600 !important;
    color: rgba(30, 64, 175, 0.72) !important;
    box-shadow: 0 -4px 16px rgba(15, 23, 42, 0.08);
}

[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #1e3a8a !important;
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(226, 232, 240, 0.9)) !important;
    box-shadow: 0 -6px 22px rgba(59, 130, 246, 0.12);
}

[data-testid="stTabs"] button[role="tab"]:hover {
    color: #1d4ed8 !important;
}

[data-testid="stTabs"] div[data-baseweb="tab-highlight"] {
    background: linear-gradient(90deg, rgba(37, 99, 235, 0.85), rgba(79, 70, 229, 0.85)) !important;
    height: 3px !important;
    border-radius: 999px !important;
}

[data-testid="stHeader"] {
    background: transparent !important;
    color: inherit !important;
    box-shadow: none !important;
}


/* Semantic search table styles are now handled inline with Streamlit dataframes */
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
            <h1>NthOrder: Prediction Market Discovery Engine</h1>
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


def get_category_name(category_code: str) -> str:
    """Convert category code to readable name."""
    category_mapping = {
        "2.1.1": "US Politics - Elections",
        "2.1.2": "US Politics - Government",
        "2.1.3": "International Politics",
        "2.2.1": "Economics - Markets",
        "2.2.2": "Economics - Policy",
        "3.1.1": "Technology - AI/ML",
        "3.1.2": "Technology - Crypto",
        "4.1.1": "Sports",
        "5.1.1": "Entertainment",
        "6.1.1": "Science",
        # Add more mappings as needed
    }
    return category_mapping.get(category_code, category_code)


def render_semantic_results_table(semantic_results: List[Dict[str, Any]]) -> None:
    """Render semantic search results as a beautiful Streamlit table."""
    if not semantic_results:
        return
    
    # Create header
    st.markdown(
        f"""
        <div style="
            background: linear-gradient(135deg, rgba(236, 254, 255, 0.95), rgba(224, 242, 254, 0.9));
            border: 1px solid rgba(14, 165, 233, 0.25);
            border-radius: 12px 12px 0 0;
            padding: 12px 16px;
            margin-top: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        ">
            <span style="font-size: 18px;">🔍</span>
            <span style="font-weight: 600; color: rgba(14, 116, 144, 0.9); font-size: 15px;">
                Semantic Search Results
            </span>
            <span style="color: rgba(71, 85, 105, 0.7); font-size: 13px; font-weight: 500;">
                ({len(semantic_results)} found)
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    # Prepare data for Streamlit table
    table_data = []
    for i, result in enumerate(semantic_results, 1):
        question = result.get("question", "")
        relevance_score = result.get("relevance_score", 0)
        search_source = result.get("search_source", "weaviate")
        category = result.get("category", "") or result.get("market_category_name", "")
        
        # Format relevance score as percentage
        score_display = f"{relevance_score * 100:.1f}%" if relevance_score else "N/A"
        
        # Create source display
        source_display = "Categorized" if "categorized" in search_source else "Standard"
        
        # Truncate long questions for table display
        display_question = question if len(question) <= 80 else question[:77] + "..."
        
        # Create category display with readable name
        category_display = get_category_name(category) if category else "—"
        
        table_data.append({
            "#": f"#{i}",
            "Market Question": display_question,
            "Relevance": score_display,
            "Source": source_display,
            "Category": category_display
        })
    
    # Display as Streamlit dataframe with custom styling
    df = pd.DataFrame(table_data)
    
    # Custom CSS for the dataframe
    st.markdown(
        """
        <style>
        .stDataFrame {
            border: 1px solid rgba(14, 165, 233, 0.25) !important;
            border-top: none !important;
            border-radius: 0 0 12px 12px !important;
            overflow: hidden !important;
        }
        .stDataFrame > div {
            border-radius: 0 0 12px 12px !important;
        }
        .stDataFrame table {
            background: rgba(255, 255, 255, 0.9) !important;
        }
        .stDataFrame thead th {
            background: rgba(219, 234, 254, 0.8) !important;
            color: #1e40af !important;
            font-weight: 600 !important;
            font-size: 13px !important;
            text-transform: uppercase !important;
            letter-spacing: 0.5px !important;
            border-bottom: 2px solid rgba(14, 165, 233, 0.2) !important;
        }
        .stDataFrame tbody tr:nth-child(odd) {
            background: rgba(255, 255, 255, 0.6) !important;
        }
        .stDataFrame tbody tr:nth-child(even) {
            background: rgba(248, 250, 255, 0.8) !important;
        }
        .stDataFrame tbody tr:hover {
            background: rgba(191, 219, 254, 0.4) !important;
        }
        .stDataFrame tbody td {
            font-size: 14px !important;
            padding: 12px 8px !important;
            border-bottom: 1px solid rgba(14, 165, 233, 0.1) !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    # Display the dataframe
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "#": st.column_config.TextColumn(width="small"),
            "Market Question": st.column_config.TextColumn(width="large"),
            "Relevance": st.column_config.TextColumn(width="small"),
            "Source": st.column_config.TextColumn(width="medium"),
            "Category": st.column_config.TextColumn(width="medium")
        }
    )


def display_payload(payload: Dict[str, Any] | None, *, show_summary: bool = True) -> None:
    if not payload:
        return

    summary = payload.get("sql_summary") or payload.get("assistant_message")

    # Display semantic search results if available
    debug_info = payload.get("debug", {})
    semantic_results = debug_info.get("semantic_results", [])
    if semantic_results:
        render_semantic_results_table(semantic_results)

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

    rows = payload.get("sql_rows") or payload.get("final_table_rows")
    if rows:
        caption = None
        if summary:
            caption = summary
            summary = ""
        render_sql_table(rows, caption=caption)
        return

    if summary and show_summary:
        st.markdown(render_bubble(summary, "assistant-bubble"), unsafe_allow_html=True)


def render_sql_table(rows: List[Dict[str, Any]], caption: str | None = None) -> None:
    """Render SQL results as a beautiful Streamlit table."""
    if not rows:
        return

    # Create header with caption
    if caption:
        st.markdown(
            f"""
            <div style="
                background: linear-gradient(135deg, rgba(219, 234, 254, 0.95), rgba(191, 219, 254, 0.9));
                border: 1px solid rgba(59, 130, 246, 0.25);
                border-radius: 12px 12px 0 0;
                padding: 12px 16px;
                margin-top: 12px;
                display: flex;
                align-items: center;
                gap: 8px;
            ">
                <span style="font-size: 18px;">📊</span>
                <span style="font-weight: 600; color: rgba(30, 64, 175, 0.9); font-size: 15px;">
                    Query Results
                </span>
                <span style="color: rgba(71, 85, 105, 0.7); font-size: 13px; font-weight: 500;">
                    ({len(rows)} rows)
                </span>
            </div>
            <div style="
                background: rgba(255, 255, 255, 0.9);
                border: 1px solid rgba(59, 130, 246, 0.25);
                border-top: none;
                padding: 12px 16px;
                font-size: 14px;
                color: #374151;
                line-height: 1.5;
            ">
                {html.escape(caption)}
            </div>
            """,
            unsafe_allow_html=True
        )

    # Filter out description column and normalize data
    columns = [col for col in rows[0].keys() if col.lower() != "description"]
    
    def _normalize(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            stripped = value.strip()
            if (
                stripped
                and stripped.upper() == stripped
                and any(ch.isalpha() for ch in stripped)
                and not any(ch.isdigit() for ch in stripped)
            ):
                return stripped.title()
            return stripped
        return str(value)

    # Prepare data for Streamlit table
    table_data = []
    for row in rows:
        normalized_row = {}
        for col in columns:
            normalized_row[col] = _normalize(row.get(col, ''))
        table_data.append(normalized_row)
    
    # Create DataFrame
    df = pd.DataFrame(table_data)
    
    # Custom CSS for the SQL results dataframe
    st.markdown(
        """
        <style>
        .stDataFrame {
            border: 1px solid rgba(59, 130, 246, 0.25) !important;
            border-top: none !important;
            border-radius: 0 0 12px 12px !important;
            overflow: hidden !important;
        }
        .stDataFrame > div {
            border-radius: 0 0 12px 12px !important;
        }
        .stDataFrame table {
            background: rgba(255, 255, 255, 0.9) !important;
        }
        .stDataFrame thead th {
            background: rgba(219, 234, 254, 0.8) !important;
            color: #1e40af !important;
            font-weight: 600 !important;
            font-size: 13px !important;
            text-transform: uppercase !important;
            letter-spacing: 0.5px !important;
            border-bottom: 2px solid rgba(59, 130, 246, 0.2) !important;
        }
        .stDataFrame tbody tr:nth-child(odd) {
            background: rgba(255, 255, 255, 0.6) !important;
        }
        .stDataFrame tbody tr:nth-child(even) {
            background: rgba(248, 250, 255, 0.8) !important;
        }
        .stDataFrame tbody tr:hover {
            background: rgba(191, 219, 254, 0.4) !important;
        }
        .stDataFrame tbody td {
            font-size: 14px !important;
            padding: 12px 8px !important;
            border-bottom: 1px solid rgba(59, 130, 246, 0.1) !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    # Display the dataframe
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
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
                display_payload(payload, show_summary=(buffer.strip() != summary_text))
                if show_debug and role == "assistant":
                    render_debug_block(payload)
                continue

            should_render_bubble = True
            if role == "assistant" and has_sql_rows:
                if not content.strip() or content.strip() == summary_text:
                    should_render_bubble = False

            if should_render_bubble:
                st.markdown(render_bubble(content, bubble_class), unsafe_allow_html=True)
            display_payload(payload, show_summary=not should_render_bubble or (summary_text and summary_text.strip() != content.strip()))
            if show_debug and role == "assistant":
                render_debug_block(payload)


def render_debug_block(payload: Dict[str, Any]) -> None:
    debug_payload = payload.get("debug") if isinstance(payload, dict) else None
    sql = payload.get("sql") if isinstance(payload, dict) else None
    rows = payload.get("sql_rows") if isinstance(payload, dict) else None

    with st.expander("Debug details", expanded=False):
        if sql:
            st.code(sql, language="sql")
        if batch := payload.get("sql_batch"):
            st.markdown("**SQL Batch**")
            for entry in batch:
                label = entry.get("name") or "query"
                st.write(f"- {label} ({entry.get('row_count', 0)} rows)")
                if statement := entry.get("sql"):
                    st.code(statement, language="sql")
        if rows is not None:
            st.json(rows)
        if debug_payload:
            plan = debug_payload.get("plan")
            if stage := debug_payload.get("stage"):
                st.write(f"**Stage:** {stage}")
            if plan:
                st.markdown("**SQL Plan**")
                st.json(plan)
            if top_n := debug_payload.get("selected_top_n"):
                st.write(f"Top N requested: {top_n}")
            result_count = debug_payload.get("result_row_count")
            if result_count is not None:
                st.write(f"Result row count: {result_count}")
            
            # Show semantic search information
            semantic_count = debug_payload.get("semantic_search_count", 0)
            semantic_source = debug_payload.get("semantic_search_source", "none")
            if semantic_count > 0:
                st.write(f"**Semantic Search:** {semantic_count} results from {semantic_source}")
                if semantic_results := debug_payload.get("semantic_search_results", []):
                    st.markdown("**Full Semantic Search Results**")
                    st.json(semantic_results)
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
    try:
        resp = requests.post(f"{API_BASE_URL}/chat", json=payload, timeout=90)
    except requests.RequestException as exc:
        raise RuntimeError(str(exc)) from exc
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
    st.rerun()


def _parse_log_timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        cleaned = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return datetime.min
    return datetime.min


def load_logs_by_conversation() -> Dict[str, List[Dict[str, Any]]]:
    if not LOG_FILE_PATH.exists():
        return {}

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    try:
        with LOG_FILE_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                conv_id = record.get("conversation_id", "unknown")
                grouped.setdefault(conv_id, []).append(record)
    except OSError:
        return {}

    for conv_id, records in grouped.items():
        records.sort(key=lambda item: _parse_log_timestamp(item.get("timestamp")))
    return grouped




def render_logs_tab() -> None:
    st.subheader("Conversation Logs")
    log_groups = load_logs_by_conversation()
    if not log_groups:
        st.info("No log entries found yet. Send a message to the backend to generate logs.")
        return

    conversation_ids = list(log_groups.keys())
    conversation_ids.sort(
        key=lambda cid: _parse_log_timestamp(log_groups[cid][-1].get("timestamp")),
        reverse=True,
    )

    def _format_conversation_option(cid: str) -> str:
        records = log_groups[cid]
        latest_ts = records[-1].get("timestamp", "unknown time")
        return f"{cid} · {len(records)} entries · last {latest_ts}"

    selected_id = st.selectbox(
        "Select a conversation",
        conversation_ids,
        index=0,
        format_func=_format_conversation_option,
    )

    records = log_groups.get(selected_id, [])
    if not records:
        st.warning("No records for this conversation. Try another one.")
        return

    for idx, record in enumerate(records):
        timestamp = record.get("timestamp", "unknown time")
        user_message = (record.get("user_message") or "").strip()
        preview = user_message[:80] + ("…" if len(user_message) > 80 else "")
        header = f"{timestamp} — {preview or 'No user message'}"
        with st.expander(header, expanded=False):
            assistant_message = record.get("assistant_message", "")
            st.markdown(f"**User message**: {user_message or '—'}")
            st.markdown(f"**Assistant message**: {assistant_message or '—'}")

            if plan := record.get("plan"):
                st.markdown("**SQL Plan**")
                st.json(plan)

            sql_executed = record.get("sql_executed")
            if sql_executed:
                st.markdown("**Executed SQL**")
                st.code(sql_executed, language="sql")

            sql_vars = record.get("sql_variables") or {}
            if sql_vars:
                st.markdown("**SQL Parameters**")
                st.json(sql_vars)

            sql_results = record.get("sql_results")
            if sql_results:
                st.markdown("**SQL Results**")
                st.json(sql_results)

            if sql_batch := record.get("sql_batch"):
                st.markdown("**SQL Batch**")
                for entry in sql_batch:
                    label = entry.get("name") or "query"
                    st.write(f"- {label} ({entry.get('row_count', 0)} rows)")
                    if statement := entry.get("sql"):
                        st.code(statement, language="sql")

            execution_summary = record.get("execution_summary")
            if execution_summary:
                st.markdown("**Execution Summary**")
                st.json(execution_summary)

            gemini_block = record.get("gemini") or {}
            if gemini_block:
                if prompt := gemini_block.get("chat_prompt"):
                    st.markdown("**Gemini Planning Prompt**")
                    st.code(prompt, language="markdown")
                if response_text := gemini_block.get("chat_response_text"):
                    st.markdown("**Gemini Planning Raw Response**")
                    st.code(response_text, language="markdown")
                if answer_prompt := gemini_block.get("answer_prompt"):
                    st.markdown("**Gemini Answer Prompt**")
                    st.code(answer_prompt, language="markdown")
                if answer_response := gemini_block.get("answer_response_text"):
                    st.markdown("**Gemini Answer Raw Response**")
                    st.code(answer_response, language="markdown")
                if chat_payload := gemini_block.get("chat_response_payload"):
                    st.markdown("**Gemini Planning Parsed Payload**")
                    st.json(chat_payload)
                if answer_payload := gemini_block.get("answer_response_payload"):
                    st.markdown("**Gemini Answer Parsed Payload**")
                    st.json(answer_payload)

            debug_payload = record.get("debug")
            if debug_payload:
                # Show semantic search summary first
                semantic_count = debug_payload.get("semantic_search_count", 0)
                semantic_source = debug_payload.get("semantic_search_source", "none")
                if semantic_count > 0:
                    st.markdown("**Semantic Search Summary**")
                    st.write(f"- Found {semantic_count} results from {semantic_source}")
                    if semantic_results := debug_payload.get("semantic_search_results", []):
                        for i, result in enumerate(semantic_results[:3], 1):  # Show top 3
                            question = result.get("question", "")[:100] + "..." if len(result.get("question", "")) > 100 else result.get("question", "")
                            score = result.get("relevance_score", 0)
                            st.write(f"  {i}. {question} (Score: {score*100:.1f}%)")
                
                st.markdown("**Debug Payload**")
                st.json(debug_payload)

            st.caption(f"Log index: {idx + 1} of {len(records)}")


def main() -> None:
    st.set_page_config(page_title="Agentic Search", layout="centered")
    initialize_session_state()
    inject_styles()
    show_debug = render_sidebar()

    chat_tab, logs_tab = st.tabs(["Chat", "Logs"])

    with chat_tab:
        render_header()
        render_messages(show_debug=show_debug)

        user_input = st.chat_input("Ask something…")
        if user_input:
            handle_user_input(user_input)

    with logs_tab:
        render_logs_tab()


if __name__ == "__main__":
    main()
