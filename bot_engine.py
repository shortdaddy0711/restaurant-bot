# bot_engine.py
"""
Shared bot message processing engine.

Used by both main.py (live Streamlit chat) and test_runner.py (automated QA)
so that every customer message — regardless of entry point — goes through the
same intent decomposition, loop detection, and divide-and-conquer queue.

Public API
----------
decompose_intents(message)              → list[str]
run_single_intent(msg, agent, sess, ctx) → (str, agent, bool, str|None)
process_message(msg, agent, sess, ctx)  → (str, agent, bool, str|None)

Constants
---------
RUNNER_MAX_TURNS
GUARDRAIL_BLOCKED_MESSAGE
OUTPUT_GUARDRAIL_BLOCKED_MESSAGE

Exceptions
----------
RoutingLoopDetected
"""

import json
import logging

from openai import AsyncOpenAI

# Module-level client for the intent decomposer.
# Creating it here (once at import time) ensures the client picks up env vars
# (OPENAI_API_KEY, SSL_CERT_FILE) set by dotenv.load_dotenv() in main.py,
# and avoids repeated client instantiation inside decompose_intents().
_decomposer_client = AsyncOpenAI()

from agents import (
    InputGuardrailTripwireTriggered,
    MaxTurnsExceeded,
    OutputGuardrailTripwireTriggered,
    Runner,
    SQLiteSession,
)
from agents.lifecycle import RunHooksBase
from models import RestaurantContext, APP_MODEL
from my_agents.triage_agent import triage_agent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The SDK's internal per-call turn budget.  Default is 10, which is far too
# low for multi-intent requests that traverse multiple handoff cycles.
#
# Turn cost breakdown for a single Runner.run() call with a 3-intent message:
#   Triage LLM call         = 1
#   Handoff to Specialist A = 1
#   Specialist A LLM calls  = 1–3  (reasoning + tool call + result processing)
#   Specialist A tool calls = 2–4  (each call + result = 2 turns)
#   Handoff back to Triage  = 1
#   Repeat for Specialist B = ~8 more
#   Triage final response   = 1
#   ─────────────────────────────
#   Total for 2-hop chain   ≈ 15–25 turns minimum on the happy path
#
# 50 is the last-resort ceiling.  Genuine routing loops are caught much
# earlier by LoopDetectingRunHooks (typically at turn 6–12), so in
# practice MaxTurnsExceeded at 50 should never fire on well-behaved flows.
RUNNER_MAX_TURNS: int = 50

# Number of times the SAME directed handoff pair (e.g. "Menu → Reservation")
# must repeat before LoopDetectingRunHooks raises RoutingLoopDetected.
_LOOP_DETECTION_PAIR_THRESHOLD: int = 3

GUARDRAIL_BLOCKED_MESSAGE: str = (
    "I'm sorry, I can only assist with restaurant-related inquiries. "
    "I can help you view the menu, make a reservation, or place an order. 🍽️"
)

OUTPUT_GUARDRAIL_BLOCKED_MESSAGE: str = (
    "⚠️ I wasn't able to generate an appropriate response. "
    "Please try rephrasing your question, and I'll do my best to help!"
)

# System prompt for the lightweight intent decomposer.
INTENT_DECOMPOSER_SYSTEM_PROMPT: str = """
You are an intent parser for a restaurant chatbot. Your task is to detect whether a
customer's message contains multiple distinct service intents and, if so, split it into
separate single-intent messages.

The restaurant bot handles exactly these intent categories:
  COMPLAINT   — raising issues, requesting refunds, manager callbacks
  RESERVATION — booking a table, party size, date/time, availability
  ORDER       — placing a food or drink order, adding or confirming items
  MENU        — browsing dishes, ingredients, allergens, specials, pricing

RULES:
- Only split when two or more intents from DIFFERENT categories are clearly present.
- Keep the customer's original tone and phrasing in each split message.
- Each split message must be fully self-contained and understandable on its own.
  Include all relevant details from the original message in the appropriate sub-message.
- Do NOT invent information not present in the original message.
- Do NOT split a single intent into sub-parts.
- If the message is ambiguous or contains only one intent, return it unchanged.

PRIORITY ORDER — when multiple intents are detected, return them in this order:
  1. COMPLAINT   (address first so the guest feels heard immediately)
  2. RESERVATION (time-sensitive — they need a table)
  3. ORDER       (active transaction in progress)
  4. MENU        (browsing — no urgency, can wait)

Return ONLY a valid JSON object with this exact schema — no other text:
{"intents": ["<sub-message 1>", "<sub-message 2>", ...]}

If single intent:
{"intents": ["<the original message unchanged>"]}
"""


# ---------------------------------------------------------------------------
# Loop Detection
# ---------------------------------------------------------------------------


class RoutingLoopDetected(Exception):
    """
    Raised by LoopDetectingRunHooks when a cycling handoff pattern is found.

    Attributes:
        loop_summary: Human-readable description of the detected loop,
                      including the pair that cycled and the full sequence.
    """

    def __init__(self, loop_summary: str) -> None:
        super().__init__(loop_summary)
        self.loop_summary: str = loop_summary


class LoopDetectingRunHooks(RunHooksBase):
    """
    RunHooks implementation that detects infinite routing loops.

    Tracks every agent-to-agent handoff within a single Runner.run() call.
    When the same directed pair (e.g. "Food Expert → Front Desk")
    is observed _LOOP_DETECTION_PAIR_THRESHOLD or more times, raises
    RoutingLoopDetected to abort the run immediately.
    """

    def __init__(self) -> None:
        self._pair_counts: dict[str, int] = {}
        self._handoff_sequence: list[str] = []

    async def on_handoff(self, context, from_agent, to_agent) -> None:  # type: ignore[override]
        """Fires on every handoff. Raises RoutingLoopDetected on repeated pairs."""
        pair_key = f"{from_agent.name} → {to_agent.name}"
        self._handoff_sequence.append(pair_key)
        self._pair_counts[pair_key] = self._pair_counts.get(pair_key, 0) + 1

        count = self._pair_counts[pair_key]
        if count >= _LOOP_DETECTION_PAIR_THRESHOLD:
            full_sequence = " ➜ ".join(self._handoff_sequence)
            loop_summary = (
                f"Routing loop: '{pair_key}' repeated {count}× in one response. "
                f"Full handoff sequence: {full_sequence}"
            )
            logger.error("Loop detected — aborting Runner.run(). %s", loop_summary)
            raise RoutingLoopDetected(loop_summary)

    @property
    def handoff_sequence(self) -> list[str]:
        """Returns a copy of the observed handoff sequence for diagnostics."""
        return list(self._handoff_sequence)


# ---------------------------------------------------------------------------
# Core Processing Functions
# ---------------------------------------------------------------------------


async def decompose_intents(message: str) -> list[str]:
    """
    Detect and split a multi-intent customer message into single-intent sub-messages.

    Uses a lightweight LLM call (APP_MODEL) to classify intents (RESERVATION, MENU,
    ORDER, COMPLAINT) and returns them in priority order. Returns the original
    message unchanged if only one intent is present or if the call fails.

    Args:
        message: The raw customer message to analyse.

    Returns:
        A list of one or more single-intent strings. Always non-empty.
    """
    try:
        logger.info("Decomposer called — model=%s, message=%.80s", APP_MODEL, message)
        response = await _decomposer_client.chat.completions.create(
            model=APP_MODEL,
            messages=[
                {"role": "system", "content": INTENT_DECOMPOSER_SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content or "{}"
        logger.info("Decomposer raw response: %.200s", raw_content)
        result = json.loads(raw_content)
        intents: list[str] = result.get("intents", [])

        if not intents:
            logger.warning("Decomposer returned empty intents list — using original message.")
            return [message]

        logger.info("Decomposer result: %d intent(s) → %s", len(intents), [i[:60] for i in intents])
        return intents

    except Exception as exc:
        logger.warning(
            "Intent decomposer failed (%s: %s) — falling back to original message.",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return [message]


async def run_single_intent(
    message: str,
    current_agent,
    session: SQLiteSession,
    ctx: RestaurantContext,
) -> tuple[str, object, bool, str | None]:
    """
    Send a single, single-intent message to the Restaurant Bot via Runner.run().

    Args:
        message:       A single-intent user message.
        current_agent: The Agent to start from (triage_agent or a specialist).
        session:       The SQLiteSession for this conversation.
        ctx:           The RestaurantContext for this conversation.

    Returns:
        (response_text, last_agent, guardrail_triggered, guardrail_type)
        where guardrail_type is "input", "output", or None.
    """
    loop_hooks = LoopDetectingRunHooks()

    try:
        result = await Runner.run(
            current_agent,
            message,
            session=session,
            context=ctx,
            max_turns=RUNNER_MAX_TURNS,
            hooks=loop_hooks,
        )
        response_text: str = (
            result.final_output
            if isinstance(result.final_output, str)
            else str(result.final_output)
        )
        return response_text, result.last_agent, False, None

    except InputGuardrailTripwireTriggered:
        logger.info("Input guardrail triggered for message: %.60s", message)
        return GUARDRAIL_BLOCKED_MESSAGE, current_agent, True, "input"

    except OutputGuardrailTripwireTriggered:
        logger.info("Output guardrail triggered.")
        return OUTPUT_GUARDRAIL_BLOCKED_MESSAGE, current_agent, True, "output"

    except RoutingLoopDetected as exc:
        sequence_summary = " ➜ ".join(loop_hooks.handoff_sequence)
        error_msg = (
            f"[🔁 ROUTING LOOP DETECTED] The bot entered an infinite handoff cycle "
            f"and was stopped early.\n"
            f"Loop detail: {exc.loop_summary}\n"
            f"Full observed sequence: {sequence_summary}\n"
            "This is a critical bot architectural defect: specialist agents are "
            "re-routing intents from the original multi-intent message rather than "
            "handling only their assigned portion."
        )
        return error_msg, current_agent, False, None

    except MaxTurnsExceeded as exc:
        logger.error(
            "SDK MaxTurnsExceeded (%d turns) after loop detection did not trigger: %s",
            RUNNER_MAX_TURNS,
            exc,
        )
        error_msg = (
            f"[⚠️ Bot Error: Response required more than {RUNNER_MAX_TURNS} internal "
            "steps without a detectable repeating loop pattern. "
            "This indicates an excessively deep tool-call or reasoning chain.]"
        )
        return error_msg, current_agent, False, None

    except Exception as exc:
        logger.error("Unexpected error from bot Runner: %s", exc, exc_info=True)
        error_msg = f"[Bot Error: {type(exc).__name__}: {exc}]"
        return error_msg, current_agent, False, None


async def process_message(
    message: str,
    current_agent,
    session: SQLiteSession,
    ctx: RestaurantContext,
) -> tuple[str, object, bool, str | None]:
    """
    Main entry point: send a customer message to the bot, handling multi-intent splitting.

    For single-intent messages the behaviour is identical to a direct run_single_intent()
    call.  For multi-intent messages the intent queue is populated in context and a single
    Runner.run() is used. Triage processes each intent in priority order by cycling
    through the queue internally (Triage → Specialist → Triage → Specialist → …)
    until all intents are exhausted, then generates a combined summary.

    Always clears ctx.pending_intents and ctx.is_queue_session at the start so that
    single-intent follow-up messages are never mistaken for queue continuation.

    Args:
        message:       The raw customer message (may contain multiple intents).
        current_agent: The currently active Agent (used for single-intent only).
        session:       The SQLiteSession for this conversation.
        ctx:           The RestaurantContext for this conversation.

    Returns:
        (response_text, last_agent, guardrail_triggered, guardrail_type)
    """
    # Clear any queue state carried over from the previous turn.
    ctx.pending_intents = []
    ctx.is_queue_session = False

    sub_messages = await decompose_intents(message)

    # ── Single intent — direct pass-through, no overhead ─────────────────────
    if len(sub_messages) == 1:
        return await run_single_intent(sub_messages[0], current_agent, session, ctx)

    # ── Multi-intent — populate queue and let Triage orchestrate internally ──
    # Triage's dynamic instructions check pending_intents on each invocation:
    #   • non-empty → route to next specialist immediately (queue mode)
    #   • empty     → generate combined summary (is_queue_session flag)
    # handle_return_handoff pops the completed intent each time a specialist
    # returns to Triage, advancing the queue automatically.
    logger.info(
        "Multi-intent queue: %d intents → %s",
        len(sub_messages),
        [m[:60] for m in sub_messages],
    )
    ctx.pending_intents = list(sub_messages)
    ctx.is_queue_session = True

    # Pass the original message (for natural session history) starting from triage.
    return await run_single_intent(message, triage_agent, session, ctx)
