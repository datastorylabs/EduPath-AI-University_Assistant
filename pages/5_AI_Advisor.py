"""Integrated AI admission assistant — RAG-powered."""
from __future__ import annotations

from typing import Any

import streamlit as st

from backend.rag import ask, build_index, get_index_status, is_available
from backend.rag.llm import get_package_status
from backend.state import ensure_eligibility, get_profile, get_selection
from ui import init_session_state, inject_theme, nav_row, page_header, render_sidebar


def _engine_label(engine: str | None, model: str | None = None) -> str:
    if engine == "rag":
        return "🤖 AI Advisor"
    if engine == "rule-based":
        return "📘 Fallback Advisor (rule-based)"
    return "Advisor"


def _run_question(question: str, profile: dict[str, Any], eligibility: dict[str, Any]) -> None:
    stripped = question.strip()
    if not stripped:
        return

    uni_id = st.session_state.get("selected_university_id")
    prog_id = st.session_state.get("selected_program_id")

    if len(stripped) > 1200:
        st.warning("Please keep each question to 1,200 characters or fewer.")
        return
    index_status = get_index_status()
    if not index_status.get("ready") and not st.session_state.get("_edupath_policy_index_attempted"):
        st.session_state["_edupath_policy_index_attempted"] = True
        with st.spinner("Preparing the admissions knowledge base for the first question. The first run may take a few minutes..."):
            build_result = build_index()
        if build_result.error:
            st.warning("The policy index could not be prepared. EduPath will use the rules-based fallback until the index is repaired.")
        else:
            st.session_state.pop("_edupath_policy_index_error", None)
    try:
        ask_result = ask(
            question=stripped,
            profile=profile,
            eligibility=eligibility,
            history=st.session_state["chat_history"],
            university_id=uni_id,
            program_id=prog_id,
        )
    except Exception as exc:  # pragma: no cover — UI safety net
        st.error(
            "The AI advisor is temporarily unavailable. Please try again in a moment."
        )
        st.caption(f"Diagnostic: {type(exc).__name__}")
        return

    if ask_result.engine == "rag":
        reply = ask_result.answer
    else:
        reply = ask_result.answer
        if ask_result.error:
            reply = f"{reply}\n\n*(Fallback mode: the AI advisor is unavailable — {ask_result.error}. Showing a rule-based answer instead.)*"

    history = st.session_state["chat_history"]
    sources_by_index = st.session_state["chat_history_sources"]

    # Append user message (sources slot = empty list so indices stay aligned).
    history.append({"role": "user", "content": stripped})
    while len(sources_by_index) < len(history):
        sources_by_index.append([])

    # Append assistant message (sources slot = actual sources for this index).
    history.append(
        {
            "role": "assistant",
            "content": reply,
            "engine": ask_result.engine,
            "model": ask_result.model,
        }
    )
    while len(sources_by_index) < len(history):
        sources_by_index.append([])
    sources_by_index[len(history) - 1] = list(ask_result.sources)
    from backend.legacy_storage import persist_application_state
    persist_application_state()
    st.rerun()


st.set_page_config(page_title="AI Advisor | EduPath AI", page_icon="🤖", layout="wide")
init_session_state()
inject_theme()
render_sidebar()

page_header(
    "EduPath Advisor",
    "Ask anything about your admission journey. Answers are grounded in verified university policies and your profile.",
    "🤖",
)

uni, prog, prog_display, _initial = get_selection()
if prog is None or uni is None:
    with st.container(border=True):
        st.warning("Select a program first to get grounded advice.")
        if st.button("Select Program", type="primary", key="goto_select"):
            st.switch_page("pages/3_Select_Program.py")
    st.stop()

profile = get_profile()
result = ensure_eligibility() or {}

with st.container(border=True):
    st.markdown(
        f"""
        <div class="ep-list-item">🏫 Answering based on: <strong>{uni['name']} — {prog['name']}</strong></div>
        <div class="ep-list-item">👤 Profile: <strong>{profile.get('qualification', 'N/A')}, {profile.get('aggregate', 'N/A')}% aggregate</strong></div>
        """,
        unsafe_allow_html=True,
    )
    package_status = get_package_status()
    if not package_status.available:
        st.warning(
            "Groq runtime is unavailable. Answers will use the rule-based fallback. "
            "Install or repair the Groq package in the interpreter shown below."
        )
        st.caption(package_status.message or "Groq package status is unavailable.")
    elif not is_available():
        st.info(
            "Groq API key not configured. Answers will use the rule-based fallback. "
            "To enable the full RAG advisor, set `GROQ_API_KEY` in `.streamlit/secrets.toml`."
        )

index_status = get_index_status()
if index_status.get("ready"):
    st.success(f"Admission knowledge index ready ({index_status.get('count', 0)} searchable passages).")
else:
    st.warning("The knowledge index is not ready. EduPath will try to build it on the first question; otherwise it will use the deterministic fallback.")
    if st.button("Build / repair admission knowledge index", key="build_admission_index", type="primary"):
        with st.spinner("Building the local admissions knowledge index. First-time embedding setup may take several minutes..."):
            build_result = build_index(force=bool(index_status.get("exists")))
        if build_result.error:
            st.error("Index build failed. Check the terminal for local dependency diagnostics; no student data was changed.")
        else:
            st.session_state["_edupath_policy_index_attempted"] = True
            st.session_state.pop("_edupath_policy_index_error", None)
            st.success(f"Index built: {build_result.indexed_chunks} searchable passages.")
            st.rerun()

st.markdown("### Quick Questions")
quick_questions = [
    "What is my eligibility verdict?",
    "What documents are missing?",
    "When is the application deadline?",
    "How do I register for the admission test?",
    "What is the minimum aggregate required?",
]

for row_start in range(0, len(quick_questions), 3):
    row_questions = quick_questions[row_start : row_start + 3]
    cols = st.columns(len(row_questions))
    for idx, qq in enumerate(row_questions):
        if cols[idx].button(qq, key=f"qq_{row_start + idx}", use_container_width=True):
            _run_question(qq, profile, result)

st.divider()

st.markdown("### Chat")
if st.button("Clear saved conversation", key="clear_advisor_conversation"):
    st.session_state["chat_history"] = []
    st.session_state["chat_history_sources"] = []
    from backend.legacy_storage import persist_application_state
    persist_application_state()
    st.rerun()
history = st.session_state["chat_history"]
sources_by_index = st.session_state["chat_history_sources"]

for i, msg in enumerate(history):
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            engine = msg.get("engine")
            model = msg.get("model")
            label = _engine_label(engine, model)
            if engine == "rule-based":
                st.caption(f"{label}")
            else:
                st.caption(f"{label}")
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and i < len(sources_by_index):
            sources = sources_by_index[i]
            if sources:
                with st.expander("Sources", expanded=False):
                    for src in sources:
                        st.caption(f"• {src}")

user_input = st.chat_input("Ask a question about your admission...")
if user_input and user_input.strip():
    _run_question(user_input, profile, result)


nav_row(
    back_page="pages/4_Eligibility_Check.py",
    next_page="pages/6_Action_Plan.py",
    back_label="← Back to Eligibility",
    next_label="Next: Action Plan →",
)
