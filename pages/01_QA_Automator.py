# pages/01_QA_Automator.py
"""
QA Automation Dashboard — Step 5 of the Automated AI Agent Testing System.

Streamlit multi-page app entry point for running automated persona tests
against the Restaurant Bot and rendering LLM-as-a-Judge evaluation reports.

Usage:
  Run alongside the main bot: streamlit run main.py
  Navigate to "QA Automator" in the sidebar page list.
"""

import asyncio
import json
import logging

import dotenv

import test_config
import test_runner

dotenv.load_dotenv()

import streamlit as st
from report_generator import generate_qa_report
from test_config import get_persona, get_persona_display_names
from test_runner import TurnResult, run_automated_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page Config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="QA Automator — Restaurant Bot",
    page_icon="🧪",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Helper Functions  (defined first — called later in execution flow)
# ---------------------------------------------------------------------------


def _render_report(report: dict, log_path: str) -> None:
    """
    Render the structured QA report with Streamlit components.

    Args:
        report:   Dict returned by generate_qa_report().
        log_path: Path to the raw session log JSON for the raw-log expander.
    """
    status = report.get("status", "FAIL")
    meta = report.get("_meta", {})

    # Overall Status Banner
    if status == "PASS":
        st.success("### ✅ Result: PASS", icon="✅")
    else:
        st.error("### ❌ Result: FAIL", icon="❌")

    # Summary
    st.markdown(f"**Summary:** {report.get('summary', 'N/A')}")

    # Metadata row
    if meta:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Turns", meta.get("total_turns", "—"))
        col2.metric("Termination", meta.get("termination_reason", "—"))
        col3.metric("Persona", meta.get("persona_display_name", "—"))
        col4.metric("Judge Model", meta.get("report_model", "—"))

    st.divider()

    # Evaluation Detail Expanders
    with st.expander("🔀 Handoff Evaluation", expanded=True):
        st.markdown(report.get("handoff_evaluation", "Not evaluated."))

    with st.expander("🛡️ Guardrail Evaluation", expanded=True):
        st.markdown(report.get("guardrail_evaluation", "Not evaluated."))

    with st.expander("🧠 Memory Retention Evaluation", expanded=True):
        st.markdown(report.get("memory_evaluation", "Not evaluated."))

    with st.expander("🎯 Mission Success Evaluation", expanded=True):
        st.markdown(report.get("mission_success_evaluation", "Not evaluated."))

    # Critical Issues
    critical_issues: list = report.get("critical_issues", [])
    with st.expander(
        f"🚨 Critical Issues ({len(critical_issues)})",
        expanded=bool(critical_issues),
    ):
        if critical_issues:
            for issue in critical_issues:
                st.error(f"• {issue}")
        else:
            st.success("No critical issues found.")

    # Raw JSON Logs side-by-side
    st.divider()
    col_log, col_report = st.columns(2)

    with col_log:
        with st.expander("📄 Raw Session Log (JSON)", expanded=False):
            try:
                with open(log_path, "r", encoding="utf-8") as fh:
                    raw_log = json.load(fh)
                st.json(raw_log)
            except (FileNotFoundError, json.JSONDecodeError, OSError) as read_exc:
                st.error(f"Could not read log file: {read_exc}")

    with col_report:
        with st.expander("📋 Raw Report JSON", expanded=False):
            st.json(report)


# ---------------------------------------------------------------------------
# Page Header
# ---------------------------------------------------------------------------

st.title("🧪 Restaurant Bot — QA Automation Dashboard")
st.caption(
    "Simulate customer personas against the Restaurant Bot and get an "
    "LLM-as-a-Judge evaluation."
)
st.divider()


# ---------------------------------------------------------------------------
# Sidebar — Test Configuration
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Test Configuration")

    display_names = get_persona_display_names()
    persona_options = list(display_names.keys())
    persona_labels = list(display_names.values())

    selected_label = st.selectbox(
        label="Select Persona",
        options=persona_labels,
        index=0,
        help=(
            "Each persona simulates a different customer archetype "
            "to stress-test a specific bot capability."
        ),
    )
    # Reverse-lookup the persona_id from the selected display label.
    selected_persona_id: str = persona_options[persona_labels.index(selected_label)]

    max_turns: int = int(st.number_input(
        label="Max Turns",
        min_value=2,
        max_value=10,
        value=5,
        step=1,
        help="Maximum number of conversation turns before the test auto-terminates.",
    ))

    # Show persona details for reference.
    persona_config = get_persona(selected_persona_id)
    st.divider()
    st.markdown("**🎯 Target Agents**")
    for _agent_name in persona_config["target_agents"]:
        st.markdown(f"- `{_agent_name}`")
    st.markdown("**✅ Success Condition**")
    st.info(persona_config["success_description"])

    st.divider()
    run_button = st.button(
        "▶️ Run Automated Test",
        type="primary",
        use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Empty State (shown when no test is running / has run)
# ---------------------------------------------------------------------------

if not run_button:
    st.markdown(
        """
        ### 👈 Configure a test in the sidebar and click **Run Automated Test** to begin.

        **What this dashboard does:**

        | Step | What Happens |
        |------|-------------|
        | 1 | A **Tester Agent** simulates the selected persona |
        | 2 | Each message is passed to the **Restaurant Bot** backend |
        | 3 | Agent routing, guardrail events & responses are logged |
        | 4 | A **Judge Agent** evaluates the full session |
        | 5 | A structured **PASS/FAIL report** is rendered here |

        **Available Personas:**
        """
    )
    for _pid, _pname in get_persona_display_names().items():
        _pc = get_persona(_pid)
        st.markdown(
            f"- **{_pname}** — targets "
            f"`{'`, `'.join(_pc['target_agents'])}`"
        )
    st.stop()  # Prevent the run block below from executing on empty state.


# ---------------------------------------------------------------------------
# Main Panel — Execution & Results
# ---------------------------------------------------------------------------

# Initialise session state keys for this run.
st.session_state["qa_log_path"] = None
st.session_state["qa_report"] = None
st.session_state["qa_error"] = None

# ------------------------------------------------------------------
# Live Conversation Feed container
# ------------------------------------------------------------------
st.subheader("💬 Live Conversation Feed")
st.caption(
    f"Persona: **{persona_config['display_name']}** · "
    f"Max Turns: **{int(max_turns)}**"
)

conversation_container = st.container(border=True)


def on_turn_complete(turn: TurnResult) -> None:
    """
    Real-time callback fired inside asyncio.run() after each completed turn.
    Writes into the pre-created conversation_container so chat bubbles
    appear progressively as the test runs.
    """
    with conversation_container:
        st.markdown(
            f"<p style='color: grey; font-size: 0.75rem; margin: 4px 0;'>"
            f"— Turn {turn.turn} —</p>",
            unsafe_allow_html=True,
        )

        with st.chat_message("user"):
            st.markdown(f"*🤖 Tester Persona · Turn {turn.turn}*")
            st.write(turn.tester_message)

        with st.chat_message("assistant"):
            st.markdown(f"**Active Agent:** `{turn.active_agent}`")
            if turn.guardrail_triggered:
                guardrail_label = (turn.guardrail_type or "").upper()
                st.warning(
                    f"🚫 **{guardrail_label} GUARDRAIL TRIGGERED** — "
                    "Bot returned safe fallback message.",
                    icon="🛡️",
                )
            st.write(turn.bot_response)


# ------------------------------------------------------------------
# Execute test session with status indicator
# ------------------------------------------------------------------
with st.status(
    f"🏃 Running: {persona_config['display_name']} ...",
    expanded=False,
) as _status:
    _status.write(f"🔧 Initialising TesterAgent for `{selected_persona_id}`...")
    _status.write(f"🎯 Target agents: {', '.join(persona_config['target_agents'])}")
    _status.write(f"🔄 Max turns: {int(max_turns)}")

    try:
        _log_path: str = asyncio.run(
            run_automated_session(
                persona_id=selected_persona_id,
                max_turns=int(max_turns),
                on_turn_complete=on_turn_complete,
            )
        )
        st.session_state["qa_log_path"] = _log_path
        _status.update(
            label="✅ Test session complete.",
            state="complete",
            expanded=False,
        )
        _status.write(f"📄 Log saved: `{_log_path}`")

    except Exception as _exc:
        logger.error("Test session failed: %s", _exc, exc_info=True)
        st.session_state["qa_error"] = str(_exc)
        _status.update(
            label="❌ Test session failed.",
            state="error",
            expanded=True,
        )
        _status.write(f"**Error:** {_exc}")

# ------------------------------------------------------------------
# Generate & Render QA Report
# ------------------------------------------------------------------
if st.session_state.get("qa_log_path"):
    st.divider()
    st.subheader("📊 QA Evaluation Report")

    with st.spinner("🧑‍⚖️ LLM Judge is evaluating the session..."):
        try:
            _report = generate_qa_report(st.session_state["qa_log_path"])
            st.session_state["qa_report"] = _report
        except Exception as _report_exc:
            logger.error("Report generation failed: %s", _report_exc, exc_info=True)
            st.session_state["qa_error"] = str(_report_exc)
            _report = None

    if _report:
        _render_report(_report, st.session_state["qa_log_path"])

if st.session_state.get("qa_error") and not st.session_state.get("qa_report"):
    st.error(f"❌ Error: {st.session_state['qa_error']}")
