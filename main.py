import dotenv

dotenv.load_dotenv()

import asyncio
import logging
import sqlite3
import uuid
from pathlib import Path

# Show bot_engine debug logs in terminal AND a file we can easily inspect.
_log_file = Path(__file__).parent / "debug.log"
_handlers: list[logging.Handler] = [logging.StreamHandler()]
try:
    _handlers.append(logging.FileHandler(str(_log_file), mode="a"))
except OSError:
    # Streamlit Cloud or read-only filesystem — file logging not available.
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    handlers=_handlers,
)
logging.getLogger("bot_engine").setLevel(logging.DEBUG)
from typing import TypeVar, Coroutine, Any
import streamlit as st

# ---------------------------------------------------------------------------
# Page config & 모바일 최적화
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Restaurant Bot",
    page_icon="🍽️",
    layout="centered",
)

# 모바일 키보드가 올라올 때 채팅 영역이 밀려 올라가는 문제를 해결합니다.
# - 채팅 입력창을 화면 하단에 고정
# - 채팅 메시지 영역에 스크롤 확보
# - viewport 높이(dvh) 사용으로 키보드 열림/닫힘에 동적 대응
st.markdown(
    """
    <style>
    /* ── 모바일 키보드 대응 ─────────────────────────────── */

    /* Streamlit 루트 컨테이너: 뷰포트 전체를 차지하되 넘치지 않게 */
    .stApp {
        position: fixed !important;
        top: 0; left: 0; right: 0; bottom: 0;
        overflow: hidden !important;
    }

    /* 메인 콘텐츠 영역: 스크롤 가능한 채팅 영역 */
    .stApp > header + div,
    .stMainBlockContainer,
    section[data-testid="stMainBlockContainer"] {
        overflow-y: auto !important;
        -webkit-overflow-scrolling: touch;
        padding-bottom: 80px !important;     /* 입력창 높이만큼 여백 */
    }

    /* 채팅 입력창: 항상 화면 하단 고정 */
    .stChatInput,
    div[data-testid="stChatInput"] {
        position: fixed !important;
        bottom: 0 !important;
        left: 0 !important;
        right: 0 !important;
        z-index: 999 !important;
        background: var(--background-color, white) !important;
        padding: 0.5rem 1rem !important;
    }

    /* 사이드바 토글 버튼이 입력창과 겹치지 않도록 */
    @media (max-width: 768px) {
        .stSidebar {
            z-index: 1000 !important;
        }
        /* 모바일에서 헤더 높이 줄이기 */
        header[data-testid="stHeader"] {
            padding: 0.25rem 0.5rem !important;
        }
    }
    </style>

    <!-- 모바일 키보드가 레이아웃을 밀어내지 않도록 viewport 설정 -->
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0, maximum-scale=1.0, interactive-widget=resizes-content">
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Async helper — single event loop for all async calls
# ---------------------------------------------------------------------------
# Streamlit reruns the script top-to-bottom on every interaction.  Using
# _run_async() repeatedly can conflict with an already-running loop.
# We cache a single loop in session_state and reuse it for every call.
# ---------------------------------------------------------------------------

T = TypeVar("T")


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine in a persistent event loop (cached per session)."""
    if "_event_loop" not in st.session_state:
        st.session_state["_event_loop"] = asyncio.new_event_loop()
    loop: asyncio.AbstractEventLoop = st.session_state["_event_loop"]
    return loop.run_until_complete(coro)


from agents import Runner, SQLiteSession, InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered
from models import RestaurantContext
from my_agents.triage_agent import triage_agent, input_guardrail_agent
from bot_engine import (
    decompose_intents,
    GUARDRAIL_BLOCKED_MESSAGE,
    OUTPUT_GUARDRAIL_BLOCKED_MESSAGE,
)

# ---------------------------------------------------------------------------
# Old session cleanup — 24시간 이상 지난 세션 데이터를 자동 삭제합니다.
# ---------------------------------------------------------------------------
_DB_PATH = Path(__file__).parent / "restaurant-memory.db"
_CLEANUP_MAX_AGE_HOURS = 24


def _cleanup_old_sessions() -> int:
    """Delete sessions older than _CLEANUP_MAX_AGE_HOURS. Returns deleted count."""
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute("PRAGMA foreign_keys = ON")  # CASCADE 삭제 활성화
        cursor = conn.execute(
            """
            DELETE FROM agent_sessions
            WHERE updated_at < datetime('now', ? || ' hours')
            """,
            (f"-{_CLEANUP_MAX_AGE_HOURS}",),
        )
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            logging.getLogger("main").info(
                "SESSION CLEANUP: deleted %d old sessions (>%dh)",
                deleted, _CLEANUP_MAX_AGE_HOURS,
            )
        return deleted
    except Exception as exc:
        logging.getLogger("main").warning("Session cleanup failed: %s", exc)
        return 0


# 세션 시작 시 1회만 정리 실행 (매번 rerun마다 실행하지 않음)
if "_cleanup_done" not in st.session_state:
    _cleanup_old_sessions()
    st.session_state["_cleanup_done"] = True

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

# 각 브라우저 탭(사용자)마다 고유한 세션 ID를 부여하여 대화 기록이 섞이지 않도록 합니다.
if "session_id" not in st.session_state:
    st.session_state["session_id"] = f"chat-{uuid.uuid4().hex[:12]}"

if "session" not in st.session_state:
    st.session_state["session"] = SQLiteSession(
        st.session_state["session_id"],
        "restaurant-memory.db",
    )
session = st.session_state["session"]

if "agent" not in st.session_state:
    st.session_state["agent"] = triage_agent

# Keep RestaurantContext in session_state so pending_intents and other
# context fields persist correctly across Streamlit reruns within a session.
if "ctx" not in st.session_state:
    st.session_state["ctx"] = RestaurantContext(customer_name="Guest")
restaurant_ctx: RestaurantContext = st.session_state["ctx"]


# ---------------------------------------------------------------------------
# Chat history painter
# ---------------------------------------------------------------------------


async def paint_history():
    messages = await session.get_items()
    for message in messages:
        if "role" in message:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.write(message["content"])
                else:
                    if message.get("type") == "message":
                        content = message.get("content", [])
                        if isinstance(content, list) and content:
                            text = content[0].get("text", "") if isinstance(content[0], dict) else ""
                        elif isinstance(content, str):
                            text = content
                        else:
                            text = ""
                        if text:
                            st.write(text.replace("$", "\\$"))


_run_async(paint_history())


# ---------------------------------------------------------------------------
# Pending-intent drain helper
# ---------------------------------------------------------------------------


async def _drain_pending_intents(
    ctx: RestaurantContext,
    session: SQLiteSession,
    text_placeholder,
    logger,
    restore_agent=None,
) -> None:
    """Process any remaining intents left in the queue after a streaming turn.

    Called at the end of EVERY streaming turn (both 3a follow-ups and 3b first turn).
    If ctx.pending_intents is empty, this is a no-op.

    Architecture decision — Runner.run() with isolated session:
      The drain uses non-streaming Runner.run() (not run_streamed) with an ISOLATED
      SQLiteSession for each intent.  This is critical because:

      1. Runner.run() completes the FULL tool-call → response cycle in one call.
         run_streamed() with a polluted session history causes the model to short-
         circuit tool calls and generate placeholder text ("I'll look that up…").

      2. An isolated session prevents the first specialist's conversation history
         (e.g. Front Desk asking "What name?") from confusing the second specialist
         (e.g. Food Expert seeing reservation context and getting confused).

      3. This matches exactly how test_runner.py → bot_engine.process_message()
         works — which we know succeeds reliably.

    After draining, restores st.session_state["agent"] to ``restore_agent`` so that
    follow-up user messages route to the correct specialist (e.g. Front Desk still
    waiting for the guest's name/phone).
    """
    if not (ctx.pending_intents and ctx.is_queue_session):
        return

    # Remember who was active so we can restore after drain.
    pre_drain_agent = restore_agent or st.session_state.get("agent", triage_agent)

    # Snapshot the intents to drain, then clear the queue state from ctx.
    # WHY: Specialist agents check ctx.pending_intents to decide whether to
    # activate QUEUE MODE.  That mode's "IMMEDIATELY hand back" emphasis
    # causes models to skip tool calls and generate placeholder text instead
    # of actually looking things up.  By hiding the queue state, agents use
    # their normal, thorough instructions (which include "MUST use tools").
    # Queue management is handled entirely by this loop — agents don't need
    # to know they're part of a queue.
    intents_to_drain = list(ctx.pending_intents)
    ctx.pending_intents = []
    ctx.is_queue_session = False

    for next_intent in intents_to_drain:
        logger.info("DRAINING QUEUE: processing '%s' (%d left after this)", next_intent[:60], len(intents_to_drain) - intents_to_drain.index(next_intent) - 1)

        st.write(f"🍽️ Now handling your other request...")
        text_placeholder = st.empty()
        st.session_state["text_placeholder"] = text_placeholder

        try:
            # Use an ISOLATED session so the specialist doesn't see the
            # first specialist's conversation history (e.g. reservation
            # Q&A polluting a menu lookup).  The drain is a self-contained
            # mini-conversation: Triage → Specialist → tool calls → response.
            drain_session = SQLiteSession(
                f"drain-{id(next_intent)}",
                "restaurant-memory.db",
            )

            # Runner.run() (non-streaming) completes the full cycle:
            # Triage routes → Specialist calls tools → Specialist responds.
            # This is the same path that works reliably in test_runner.py.
            result = await Runner.run(
                triage_agent,
                next_intent,
                session=drain_session,
                context=ctx,
                max_turns=30,
            )

            # Extract the final text from the completed run.
            response_text: str = (
                result.final_output
                if isinstance(result.final_output, str)
                else str(result.final_output)
            )
            logger.info("DRAIN RESULT for '%s': agent=%s, response=%.120s",
                        next_intent[:60], result.last_agent.name, response_text)

            if response_text:
                text_placeholder.write(response_text.replace("$", "\\$"))

        except Exception as exc:
            logger.error("Error draining intent '%s': %s", next_intent[:60], exc, exc_info=True)
            text_placeholder.write("Sorry, I had trouble handling that request. Please ask again!")

        logger.info("QUEUE DRAINED: '%s'", next_intent[:60])

    # Restore the agent that was active before the drain.
    # If that agent was a specialist still waiting for user input (e.g. Front Desk
    # needs name/phone), subsequent messages will correctly route to them.
    # If the first specialist already completed (agent returned to Triage during
    # step 3a streaming), pre_drain_agent is Triage, which is also correct.
    st.session_state["agent"] = pre_drain_agent
    logger.info("Agent restored to '%s' after drain", pre_drain_agent.name)


# ---------------------------------------------------------------------------
# Main message handler
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    """
    Process a customer message and display the bot's response.

    Flow:
      1. Pre-flight guardrail check (blocks off-topic / inappropriate messages
         before any tokens are consumed by the main agents).
      2. Intent decomposition — detect whether the message contains multiple
         distinct intents (RESERVATION, MENU, ORDER, COMPLAINT).
      3a. Single-intent  → streaming response to current agent.
          After streaming, _drain_pending_intents() processes any queued intents
          left from a prior multi-intent turn.
      3b. Multi-intent (first turn) → populate pending_intents queue, stream the
          FIRST sub-intent to Triage, pop it, then drain remaining intents.
          If the first specialist needs user input, remaining intents are drained
          on subsequent turns when they return via step 3a.
    """
    with st.chat_message("ai"):
        text_placeholder = st.empty()

        active_agent = st.session_state["agent"]

        # ── Step 1: Pre-flight input guardrail ───────────────────────────────
        # Runs synchronously BEFORE streaming so the triage agent never emits
        # tokens for a blocked message.  Only active when the current agent
        # carries input guardrails (i.e. the triage agent).
        if active_agent.input_guardrails:
            guardrail_result = await Runner.run(
                input_guardrail_agent,
                message,
                context=restaurant_ctx,
            )
            if guardrail_result.final_output.is_off_topic:
                text_placeholder.write(GUARDRAIL_BLOCKED_MESSAGE)
                return

        # ── Step 2: Intent decomposition ─────────────────────────────────────
        sub_messages = await decompose_intents(message)
        is_multi_intent = len(sub_messages) > 1

        # Log branch decision to debug.log (NO st.* calls here — they can cause reruns)
        import logging as _lg
        _dbg = _lg.getLogger("main")
        _dbg.info(
            "BRANCH DECISION: sub_messages=%d, is_multi_intent=%s, sub=%s",
            len(sub_messages), is_multi_intent, [s[:50] for s in sub_messages],
        )
        _dbg.info(
            "CTX STATE: pending_intents=%s, is_queue_session=%s, agent=%s",
            restaurant_ctx.pending_intents, restaurant_ctx.is_queue_session,
            st.session_state["agent"].name,
        )

        # ── Step 3a: Single-intent — streaming (unchanged UX) ────────────────
        if not is_multi_intent:
            response = ""
            st.session_state["text_placeholder"] = text_placeholder

            try:
                stream = Runner.run_streamed(
                    st.session_state["agent"],
                    message,
                    session=session,
                    context=restaurant_ctx,
                )

                async for event in stream.stream_events():
                    if event.type == "raw_response_event":
                        if event.data.type == "response.output_text.delta":
                            response += event.data.delta
                            text_placeholder.write(response.replace("$", "\\$"))

                    elif event.type == "agent_updated_stream_event":
                        if st.session_state["agent"].name != event.new_agent.name:
                            st.write(
                                f"🍽️ Connecting you to our {event.new_agent.name}..."
                            )
                            st.session_state["agent"] = event.new_agent
                            text_placeholder = st.empty()
                            st.session_state["text_placeholder"] = text_placeholder
                            response = ""

            except InputGuardrailTripwireTriggered:
                # Safety net — should not be reached due to pre-flight check above.
                text_placeholder.write(GUARDRAIL_BLOCKED_MESSAGE)

            except OutputGuardrailTripwireTriggered:
                text_placeholder.write(OUTPUT_GUARDRAIL_BLOCKED_MESSAGE)

            return

        # ── Step 3b: Multi-intent — process all intents ─────────────────────
        #
        # ARCHITECTURE: "Quick intents first, interactive intent last."
        #
        # The decomposer returns intents in priority order (e.g. reservation
        # before menu query).  The PRIMARY intent (first) is typically the one
        # the user cares most about and may require multi-turn interaction
        # (name, phone, confirmation).  REMAINING intents are usually quick
        # one-shot queries (menu lookups, allergen checks).
        #
        # Strategy:
        #   1. Process REMAINING intents first via Runner.run() with isolated
        #      sessions.  These complete fully (tools + response) in one call.
        #      Display each result immediately — the user sees answers appear.
        #
        #   2. Stream the PRIMARY intent last via run_streamed().  If it needs
        #      multi-turn interaction (e.g. Front Desk asking for name), the
        #      streaming naturally supports follow-up messages in step 3a.
        #
        # This eliminates the drain timing problem entirely — no deferred
        # intents, no specialist completion detection, no drain mechanism.
        #
        _dbg.info("MULTI-INTENT: %d intents detected", len(sub_messages))

        primary_intent = sub_messages[0]
        quick_intents = sub_messages[1:]

        # ctx stays completely clean — no QUEUE MODE, no return_after_done.
        restaurant_ctx.pending_intents = []
        restaurant_ctx.is_queue_session = False

        with st.sidebar:
            st.write(f"⚡ Multi-intent detected — {len(sub_messages)} requests")
            for i, s in enumerate(sub_messages):
                st.caption(f"{i+1}. {s[:100]}")

        # ── Phase 1: Process quick intents via Runner.run() ─────────────
        for qi in quick_intents:
            _dbg.info("QUICK INTENT: processing '%s' via Runner.run()", qi[:60])
            st.write(f"🍽️ Handling your request...")
            qi_placeholder = st.empty()

            try:
                qi_session = SQLiteSession(
                    f"quick-{id(qi)}",
                    "restaurant-memory.db",
                )
                result = await Runner.run(
                    triage_agent,
                    qi,
                    session=qi_session,
                    context=restaurant_ctx,
                    max_turns=30,
                )
                qi_text: str = (
                    result.final_output
                    if isinstance(result.final_output, str)
                    else str(result.final_output)
                )
                _dbg.info("QUICK INTENT RESULT: agent=%s, response=%.120s",
                          result.last_agent.name, qi_text)
                if qi_text:
                    qi_placeholder.write(qi_text.replace("$", "\\$"))

            except Exception as exc:
                _dbg.error("Error processing quick intent '%s': %s",
                           qi[:60], exc, exc_info=True)
                qi_placeholder.write("Sorry, I had trouble with that request.")

        # ── Phase 2: Stream the primary intent ──────────────────────────
        _dbg.info("PRIMARY INTENT: streaming '%s'", primary_intent[:60])
        st.write(f"🍽️ Now handling your main request...")
        response = ""
        text_placeholder = st.empty()
        st.session_state["text_placeholder"] = text_placeholder

        try:
            stream = Runner.run_streamed(
                triage_agent,
                primary_intent,
                session=session,
                context=restaurant_ctx,
            )

            async for event in stream.stream_events():
                if event.type == "raw_response_event":
                    if event.data.type == "response.output_text.delta":
                        response += event.data.delta
                        text_placeholder.write(response.replace("$", "\\$"))

                elif event.type == "agent_updated_stream_event":
                    if st.session_state["agent"].name != event.new_agent.name:
                        st.write(
                            f"🍽️ Connecting you to our {event.new_agent.name}..."
                        )
                        st.session_state["agent"] = event.new_agent
                        text_placeholder = st.empty()
                        st.session_state["text_placeholder"] = text_placeholder
                        response = ""

        except InputGuardrailTripwireTriggered:
            text_placeholder.write(GUARDRAIL_BLOCKED_MESSAGE)

        except OutputGuardrailTripwireTriggered:
            text_placeholder.write(OUTPUT_GUARDRAIL_BLOCKED_MESSAGE)


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

message = st.chat_input("Ask about our menu, place an order, or make a reservation!")

if message:
    with st.chat_message("human"):
        st.write(message)
    _run_async(run_agent(message))

    # 응답 완료 후 최신 메시지로 자동 스크롤
    st.markdown(
        """
        <script>
        const mainBlock = document.querySelector(
            'section[data-testid="stMainBlockContainer"], .stMainBlockContainer'
        );
        if (mainBlock) mainBlock.scrollTop = mainBlock.scrollHeight;
        </script>
        """,
        unsafe_allow_html=True,
    )


with st.sidebar:
    st.title("🍽️ Restaurant Bot")
    reset = st.button("Reset memory")
    if reset:
        _run_async(session.clear_session())
        # 새로운 세션 ID를 발급하여 완전히 깨끗한 대화를 시작합니다.
        new_id = f"chat-{uuid.uuid4().hex[:12]}"
        st.session_state["session_id"] = new_id
        st.session_state["session"] = SQLiteSession(new_id, "restaurant-memory.db")
        st.session_state["agent"] = triage_agent
        st.session_state["ctx"] = RestaurantContext(customer_name="Guest")
    st.write(_run_async(session.get_items()))
