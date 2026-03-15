# test_runner.py
"""
Automated Interaction Loop — Step 3 of the Automated AI Agent Testing System.

Orchestrates a full test session between a TesterAgent persona and the
Restaurant Bot. Runs the bot via the OpenAI Agents SDK Runner directly,
completely bypassing the Streamlit UI layer.

Key design decisions:
  - Uses Runner.run() (non-streaming) for clean turn-by-turn control.
  - Tracks active agent via result.last_agent to correctly continue
    mid-conversation after handoffs (matches main.py behaviour).
  - Handles both InputGuardrailTripwireTriggered and
    OutputGuardrailTripwireTriggered gracefully.
  - Writes a self-contained JSON log to qa_logs/ for the report generator.
  - Accepts an optional on_turn_complete callback for real-time Streamlit UI.

Bot processing (intent decomposition, loop detection, queue logic) is
provided by bot_engine.py, which is the shared engine used by both this
module and main.py.
"""

import logging
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import dotenv

dotenv.load_dotenv()

from agents import SQLiteSession
from bot_engine import process_message
from models import RestaurantContext
from my_agents.triage_agent import triage_agent
from test_config import get_persona
from tester_engine import TERMINATION_SIGNAL, TesterAgent
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QA_LOGS_DIR: Path = Path(__file__).parent / "qa_logs"


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass
class TurnResult:
    """
    Captures the full state of a single conversation turn for logging
    and real-time UI display.
    """

    turn: int
    tester_message: str
    bot_response: str
    active_agent: str
    guardrail_triggered: bool = False
    guardrail_type: str | None = None  # "input", "output", or None
    termination_reached: bool = False


@dataclass
class SessionLog:
    """Full structured log for one test session, persisted as JSON."""

    persona_id: str
    persona_display_name: str
    max_turns: int
    test_started_at: str
    test_completed_at: str = ""
    total_turns: int = 0
    termination_reason: str = ""  # "TEST_COMPLETE", "MAX_TURNS_REACHED", "ERROR"
    conversation: list[dict] = field(default_factory=list)

    def append_turn(self, turn: TurnResult) -> None:
        """Append a completed turn to the conversation log."""
        self.conversation.append(
            {
                "turn": turn.turn,
                "role": "tester",
                "content": turn.tester_message,
                "active_agent": None,
            }
        )
        self.conversation.append(
            {
                "turn": turn.turn,
                "role": "bot",
                "content": turn.bot_response,
                "active_agent": turn.active_agent,
                "guardrail_triggered": turn.guardrail_triggered,
                "guardrail_type": turn.guardrail_type,
            }
        )
        self.total_turns = turn.turn


# ---------------------------------------------------------------------------
# Session Log Persistence
# ---------------------------------------------------------------------------


def _save_log(log: SessionLog, log_path: Path) -> None:
    """Serialize and write the SessionLog to disk as formatted JSON."""
    QA_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(asdict(log), f, indent=2, ensure_ascii=False)
    logger.info("Session log saved: %s", log_path)


def _build_log_path(persona_id: str, started_at: datetime) -> Path:
    """Build a deterministic, collision-resistant log file path."""
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    filename = f"qa_{persona_id}_{timestamp}.json"
    return QA_LOGS_DIR / filename


# ---------------------------------------------------------------------------
# Main Orchestration Function
# ---------------------------------------------------------------------------


async def run_automated_session(
    persona_id: str,
    max_turns: int = 7,
    on_turn_complete: Callable[[TurnResult], None] | None = None,
) -> str:
    """
    Run a full automated QA test session for the given persona.

    Orchestration flow per turn:
      1. TesterAgent generates the next simulated user message.
      2. Message is passed to the Restaurant Bot via bot_engine.process_message().
      3. Bot response and active agent are captured.
      4. Turn is logged and the on_turn_complete callback is fired (if set).
      5. If TesterAgent output contains TEST_COMPLETE → break loop.
      6. Otherwise continue until max_turns is reached.

    Args:
        persona_id:        Key from test_config.PERSONAS.
        max_turns:         Hard cap on conversation turns (default 7, max 10).
        on_turn_complete:  Optional callback fired after each completed turn.
                           Receives a TurnResult; use for real-time Streamlit updates.

    Returns:
        The absolute path (as a string) to the saved JSON log file.

    Raises:
        KeyError:    If persona_id is not found in PERSONAS.
        RuntimeError: If the TesterAgent fails after max retries.
    """
    max_turns = min(max_turns, 10)  # Hard ceiling per spec

    persona = get_persona(persona_id)
    started_at = datetime.now(tz=timezone.utc)
    log_path = _build_log_path(persona_id, started_at)

    # --- Initialise isolated components --------------------------------

    tester = TesterAgent(persona_id)

    # Unique session ID per test run — ensures the bot sees a clean slate
    # and test sessions never pollute each other or the production session.
    session_id = f"qa-{persona_id}-{started_at.strftime('%Y%m%d%H%M%S')}"
    session = SQLiteSession(session_id, "restaurant-memory.db")

    ctx = RestaurantContext(customer_name="Test Customer")

    # Active agent starts at triage; updated after handoffs via last_agent.
    current_agent = triage_agent

    session_log = SessionLog(
        persona_id=persona_id,
        persona_display_name=persona["display_name"],
        max_turns=max_turns,
        test_started_at=started_at.isoformat(),
    )

    logger.info(
        "Starting automated session | persona=%s | max_turns=%d | session_id=%s",
        persona_id,
        max_turns,
        session_id,
    )

    termination_reason = "MAX_TURNS_REACHED"

    # --- Main interaction loop -----------------------------------------

    bot_reply: str = ""  # Empty string triggers the opener on turn 1

    for turn_number in range(1, max_turns + 1):
        logger.debug("Turn %d / %d", turn_number, max_turns)

        # 1. TesterAgent generates next message.
        try:
            tester_message = tester.generate_next_message(bot_reply)
        except RuntimeError as exc:
            logger.error("TesterAgent failed on turn %d: %s", turn_number, exc)
            termination_reason = "ERROR"
            break

        # 2. Check for termination signal BEFORE sending to bot.
        #    (The agent signals done; no need to send TEST_COMPLETE to the bot.)
        if TERMINATION_SIGNAL in tester_message:
            logger.info(
                "TEST_COMPLETE signal received on turn %d — stopping loop.",
                turn_number,
            )
            # Log the signal turn without a bot response for completeness.
            session_log.conversation.append(
                {
                    "turn": turn_number,
                    "role": "tester",
                    "content": tester_message,
                    "active_agent": None,
                }
            )
            session_log.total_turns = turn_number
            termination_reason = "TEST_COMPLETE"
            break

        # 3. Send tester message to the Restaurant Bot.
        bot_response, current_agent, guardrail_triggered, guardrail_type = (
            await process_message(tester_message, current_agent, session, ctx)
        )

        active_agent_name = getattr(current_agent, "name", "Unknown Agent")

        # 4. Build TurnResult and append to log.
        turn_result = TurnResult(
            turn=turn_number,
            tester_message=tester_message,
            bot_response=bot_response,
            active_agent=active_agent_name,
            guardrail_triggered=guardrail_triggered,
            guardrail_type=guardrail_type,
        )
        session_log.append_turn(turn_result)

        # 5. Fire real-time callback (drives Streamlit UI updates).
        if on_turn_complete is not None:
            try:
                on_turn_complete(turn_result)
            except Exception as cb_exc:
                logger.warning("on_turn_complete callback raised: %s", cb_exc)

        # 6. Prepare bot reply for next TesterAgent turn.
        bot_reply = bot_response

        logger.debug(
            "Turn %d complete | agent=%s | guardrail=%s",
            turn_number,
            active_agent_name,
            guardrail_type or "none",
        )

    # --- Finalise and persist log -------------------------------------

    session_log.test_completed_at = datetime.now(tz=timezone.utc).isoformat()
    session_log.termination_reason = termination_reason

    _save_log(session_log, log_path)

    logger.info(
        "Session complete | reason=%s | turns=%d | log=%s",
        termination_reason,
        session_log.total_turns,
        log_path,
    )

    return str(log_path.resolve())
