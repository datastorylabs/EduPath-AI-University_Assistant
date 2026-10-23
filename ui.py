"""Shared Streamlit UI helpers."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import streamlit as st

from backend.data_loader import load_universities
from backend.profile import is_profile_complete


def init_session_state() -> None:
    """Authenticate, restore the owner's saved state, and persist a safe snapshot."""
    from backend.legacy_auth import require_signed_in
    from backend.state import init_session_state as init_application_state
    from backend.legacy_storage import persist_application_state, restore_application_state

    require_signed_in()
    init_application_state()
    try:
        restore_application_state()
        persist_application_state()
    except Exception:
        st.error("EduPath could not safely load your saved data. Check database settings and run Alembic migrations before continuing.")
        st.stop()


def get_universities_data() -> dict[str, Any]:
    return load_universities()


def render_sidebar() -> None:
    from backend import state

    with st.sidebar:
        st.title("EduPath AI")
        st.caption("Smart University Admission Assistant")
        st.divider()

        profile = state.get_profile()
        uni, prog, _, _ = state.get_selection()
        name = profile.get("name") or "Student"
        qualification = profile.get("qualification") or "Not recorded"
        agg = profile.get("aggregate")
        agg_label = f"{agg}%" if isinstance(agg, (int, float)) else "Not recorded"

        st.markdown("**Current application**")
        st.markdown(f"👤 **{name}**")
        st.markdown(f"🎓 {qualification}")
        st.markdown(f"📊 Aggregate: {agg_label}")
        if uni and prog:
            st.markdown(f"🏫 {uni['name']}")
            st.markdown(f"📚 {prog['name']}")
        else:
            st.caption("No program selected.")

        st.divider()

        completed, total, ratio = progress_summary()

        st.markdown("**Progress**")
        st.progress(ratio)
        st.caption(f"{completed} of {total} steps completed")

        for label, done in progress_steps():
            icon = "✅" if done else "⬜"
            st.markdown(f"{icon} {label}")

        st.divider()

        if st.checkbox(
            "I understand this will clear my profile, documents, eligibility, and conversation.",
            key="sidebar_reset_confirm",
        ):
            st.button(
                "Start New Application",
                type="primary",
                use_container_width=True,
                key="sidebar_reset",
                on_click=state.reset_application,
            )

        notice = st.session_state.pop("_edupath_auth_notice", None)
        if notice:
            st.success(notice)
        if st.session_state.get("_edupath_storage_error"):
            st.error("Your latest changes could not be saved. Check the database and migration setup before leaving this page.")
        from backend.legacy_auth import render_account_controls
        render_account_controls()

        st.markdown("[About](#)")


def verdict_color(verdict: str) -> str:
    if verdict.startswith("ELIGIBLE - Conditional"):
        return "#f0ad4e"
    if verdict == "ELIGIBLE":
        return "#5cb85c"
    return "#d9534f"


def verdict_card(result: dict[str, Any]) -> None:
    verdict = result["verdict"]
    css_class = "ep-verdict-not-eligible"
    if verdict == "ELIGIBLE":
        css_class = "ep-verdict-eligible"
    elif verdict.startswith("ELIGIBLE - Conditional"):
        css_class = "ep-verdict-conditional"
    st.markdown(
        f"""
        <div class="{css_class}">
            <h3 style="margin:0;font-size:1.25rem;">{verdict}</h3>
        </div>
        """,
        unsafe_allow_html=True,
    )


def missing_docs_card(missing: list[dict[str, Any]]) -> None:
    with st.container(border=True):
        if not missing:
            st.success("All required documents are present.")
            return
        st.subheader("Missing required documents")
        for doc in missing:
            st.write(f"❌ {str(doc.get('name') or 'Required document')[:180]}")


def requirements_card(program: dict[str, Any]) -> None:
    req = program.get("requirements", {})
    quals = ", ".join(str(v) for v in (req.get("qualification") or [])) or "N/A"
    with st.container(border=True):
        st.subheader("Program Requirements")
        st.write("🎓 **Qualification:**", quals)
        st.write("✅ **Minimum aggregate:**", f"{req.get('minimum_aggregate')}%" if req.get("minimum_aggregate") is not None else "Not specified")
        if req.get("estimated_cutoff") is not None:
            st.write("📊 **Historical / estimated cutoff:**", f"{req.get('estimated_cutoff')}%")
        st.write("📝 **Admission test:**", req.get("admission_test") or "Not specified")
        st.write("📅 **Application deadline:**", req.get("application_deadline") or "Not specified")


# ---------------------------------------------------------------------------
# Design system — dashboard / marketing-style components
# ---------------------------------------------------------------------------

EP_COLORS: dict[str, str] = {
    "primary": "#4F46E5",
    "primary_dark": "#3730A3",
    "primary_soft": "#EEF0FF",
    "background": "#F7F7FB",
    "card": "#FFFFFF",
    "text": "#1E1B34",
    "muted": "#5B5876",
    "border": "#E6E5F0",
}

_EP_CSS = """
<style>
    .block-container {
        /* Streamlit's top toolbar is ~60px (3.75rem). On the very first render
           the main content block can start at viewport y=0 and overlap the
           toolbar, clipping the dashboard header. A fixed top pad guarantees
           clearance on first paint and after navigation/reset. */
        padding-top: 4.5rem !important;
        max-width: 1180px !important;
    }
    [data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #E6E5F0 !important;
    }
    div.stButton > button {
        border-radius: 10px !important;
        font-weight: 600 !important;
        padding: 0.6rem 1rem !important;
        transition: all 0.2s ease !important;
    }
    div.stButton > button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px rgba(79, 70, 229, 0.15) !important;
    }
    .ep-card {
        background-color: #FFFFFF;
        border: 1px solid #E6E5F0;
        border-radius: 16px;
        padding: 1.25rem 1.35rem;
        box-shadow: 0 1px 2px rgba(30, 27, 52, 0.04), 0 8px 24px rgba(79, 70, 229, 0.06);
        height: 100%;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .ep-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(79, 70, 229, 0.12);
    }
    .ep-hero {
        background: linear-gradient(135deg, #EEF0FF 0%, #FFFFFF 55%, #F4F1FF 100%);
        border: 1px solid #E6E5F0;
        border-radius: 20px;
        padding: 2.5rem;
    }
    .ep-eyebrow {
        display: inline-block;
        background: #EEF0FF;
        color: #4F46E5;
        font-size: 0.8rem;
        font-weight: 600;
        padding: 0.3rem 0.75rem;
        border-radius: 999px;
        margin-bottom: 0.75rem;
    }
    .ep-h1 {
        font-size: clamp(1.9rem, 4vw, 3rem);
        line-height: 1.15;
        letter-spacing: -0.02em;
        color: #1E1B34;
        margin: 0 0 0.75rem 0;
    }
    .ep-sub {
        color: #5B5876;
        font-size: 1.05rem;
        line-height: 1.6;
        max-width: 640px;
        margin: 0 0 1.5rem 0;
    }
    .ep-icon {
        width: 44px;
        height: 44px;
        border-radius: 12px;
        background: #EEF0FF;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.4rem;
        margin-bottom: 0.75rem;
    }
    .ep-step-num {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: #4F46E5;
        color: #FFFFFF;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 0.85rem;
        font-weight: 700;
        margin-bottom: 0.75rem;
    }
    .ep-trust {
        border-left: 4px solid #4F46E5;
    }
    .ep-footer {
        color: #5B5876;
        font-size: 0.9rem;
        text-align: center;
    }
    .ep-page-header {
        margin-bottom: 1.5rem;
    }
    .ep-page-header h1 {
        font-size: clamp(1.6rem, 3vw, 2.2rem);
        color: #1E1B34;
        margin: 0 0 0.35rem 0;
        line-height: 1.2;
    }
    .ep-page-header p {
        color: #5B5876;
        font-size: 1.05rem;
        line-height: 1.55;
        margin: 0;
        max-width: 640px;
    }
    .ep-section {
        background: #FFFFFF;
        border: 1px solid #E6E5F0;
        border-radius: 16px;
        padding: 1.25rem 1.35rem;
        margin-bottom: 1rem;
    }
    .ep-chip {
        display: inline-flex;
        align-items: center;
        background: #EEF0FF;
        color: #4F46E5;
        font-size: 0.8rem;
        font-weight: 600;
        padding: 0.35rem 0.8rem;
        border-radius: 999px;
        margin: 0 0.5rem 0.5rem 0;
    }
    .ep-metric {
        background: #FFFFFF;
        border: 1px solid #E6E5F0;
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
    }
    .ep-metric-value {
        font-size: 1.5rem;
        font-weight: 700;
        color: #1E1B34;
    }
    .ep-metric-label {
        font-size: 0.85rem;
        color: #5B5876;
    }
    .ep-list-item {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.35rem 0;
        color: #1E1B34;
    }
    .ep-verdict-eligible {
        background: #ECFDF5;
        color: #047857;
        border: 1px solid #A7F3D0;
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
        font-weight: 700;
    }
    .ep-verdict-conditional {
        background: #FFFBEB;
        color: #B45309;
        border: 1px solid #FDE68A;
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
        font-weight: 700;
    }
    .ep-verdict-not-eligible {
        background: #FEF2F2;
        color: #B91C1C;
        border: 1px solid #FECACA;
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
        font-weight: 700;
    }
    @media (max-width: 640px) {
        .ep-hero { padding: 1.5rem !important; }
    }
</style>
"""


def inject_theme() -> None:
    """Inject the EduPath design-system CSS for the current page DOM."""
    st.markdown(_EP_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "", emoji: str = "") -> None:
    """Render a consistent interior page header."""
    emoji_html = f'<span style="font-size:1.6rem;margin-right:0.5rem;vertical-align:middle;">{emoji}</span>' if emoji else ""
    subtitle_html = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        f"""
        <div class="ep-page-header">
            <h1>{emoji_html}{title}</h1>
            {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def nav_row(
    back_page: str | None = None,
    next_page: str | None = None,
    back_label: str = "← Back",
    next_label: str = "Next →",
    next_primary: bool = True,
) -> None:
    """Render consistent back/next navigation buttons."""
    cols = st.columns([1, 1, 2])
    if back_page and cols[0].button(back_label, use_container_width=True, key=f"nav_back_{back_page.replace('/', '_')}"):
        st.switch_page(back_page)
    if next_page:
        btn_type = "primary" if next_primary else "secondary"
        if cols[1].button(next_label, type=btn_type, use_container_width=True, key=f"nav_next_{next_page.replace('/', '_')}"):
            st.switch_page(next_page)


def progress_steps() -> list[tuple[str, bool]]:
    """Return the 5 application steps and their completion status."""
    profile = st.session_state.get("student_profile") or {}
    uni_id = st.session_state.get("selected_university_id")
    prog_id = st.session_state.get("selected_program_id")
    return [
        ("Documents Uploaded", bool(st.session_state.get("parsed_docs"))),
        ("Profile Completed", is_profile_complete(profile)),
        ("Program Selected", bool(uni_id and prog_id)),
        ("Eligibility Checked", bool(st.session_state.get("eligibility_result"))),
        ("Advisor Consulted", bool(st.session_state.get("chat_history"))),
    ]


def progress_summary() -> tuple[int, int, float]:
    """Return (completed_count, total_count, ratio) for the progress bar."""
    steps = progress_steps()
    completed = sum(1 for _, done in steps if done)
    total = len(steps)
    ratio = completed / total if total else 0.0
    return completed, total, ratio


def app_header(tagline: str = "Your smarter path to university.") -> None:
    """Render the dashboard header with brand and a primary action."""
    left, right = st.columns([3, 2], vertical_alignment="center")
    with left:
        st.markdown(
            f"""
            <div style="display:flex;align-items:center;gap:0.75rem;">
                <div style="width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,#4F46E5,#7C3AED);display:flex;align-items:center;justify-content:center;color:white;font-size:1.4rem;">🎓</div>
                <div>
                    <div style="font-size:1.5rem;font-weight:700;color:#1E1B34;line-height:1.1;">EduPath AI</div>
                    <div style="font-size:0.9rem;color:#5B5876;">{tagline}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        c1, c2 = st.columns([2, 1])
        with c1:
            if st.button("Get Started", type="primary", use_container_width=True, key="hdr_get_started"):
                st.switch_page("pages/1_Upload_Documents.py")


def feature_card(icon: str, title: str, description: str) -> None:
    """Render a single feature card."""
    st.markdown(
        f"""
        <div class="ep-card">
            <div class="ep-icon">{icon}</div>
            <h4 style="margin:0 0 0.4rem 0;color:#1E1B34;font-size:1.05rem;">{title}</h4>
            <p style="margin:0;color:#5B5876;font-size:0.95rem;line-height:1.5;">{description}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def step_card(number: int, title: str, description: str) -> None:
    """Render a numbered 'How it works' card."""
    num = f"{number:02d}"
    st.markdown(
        f"""
        <div class="ep-card">
            <div class="ep-step-num">{num}</div>
            <h4 style="margin:0 0 0.4rem 0;color:#1E1B34;font-size:1.05rem;">{title}</h4>
            <p style="margin:0;color:#5B5876;font-size:0.95rem;line-height:1.5;">{description}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def trust_note(text: str) -> None:
    """Render a trust/disclaimer card with a left accent border."""
    st.markdown(
        f"""
        <div class="ep-card ep-trust">
            <h4 style="margin:0 0 0.4rem 0;color:#1E1B34;font-size:1rem;">Trustworthy guidance</h4>
            <p style="margin:0;color:#5B5876;font-size:0.95rem;line-height:1.5;">{text}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def app_footer() -> None:
    """Render the page footer."""
    st.divider()
    st.markdown(
        """
        <div class="ep-footer">
            <strong style="color:#1E1B34;">EduPath AI</strong> — Smart University Admission Assistant
        </div>
        """,
        unsafe_allow_html=True,
    )
