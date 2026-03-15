# tester_engine.py
"""
Tester Agent Engine — Step 2 of the Automated AI Agent Testing System.

Implements the TesterAgent class: a fully independent, black-box QA agent
that simulates customer personas against the Restaurant Bot.

INDEPENDENCE GUARANTEE:
  - Uses its own openai.OpenAI client instance.
  - Maintains its own chat_history list; never shares or reads the bot's session.
  - Only imports config/constants (models.TESTER_MODEL, test_config) — never
    imports bot runtime modules (agents, tools, bot_engine, etc.).
  - Communicates with the bot only via plain text strings (input/output).

Model: controlled by TESTER_MODEL in models.py (centralised config).
"""

import logging
import time

from openai import OpenAI, APITimeoutError, APIConnectionError, RateLimitError, APIStatusError
from test_config import PersonaConfig, get_persona
from models import TESTER_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES: int = 3
RETRY_BASE_DELAY_SECONDS: float = 2.0  # Exponential backoff base

# Sentinel value the persona prompts instruct the agent to emit when done.
TERMINATION_SIGNAL: str = "TEST_COMPLETE"


# ---------------------------------------------------------------------------
# TesterAgent
# ---------------------------------------------------------------------------


class TesterAgent:
    """
    A black-box QA tester that generates simulated user messages for a
    specific persona to test the Restaurant Bot.

    The agent maintains its own isolated OpenAI conversation history and
    calls the LLM (TESTER_MODEL from models.py) independently of any Restaurant Bot infrastructure.

    Attributes:
        persona_id:     The ID of the active persona (key in PERSONAS dict).
        persona:        The full PersonaConfig for this test run.
        _client:        Private OpenAI client — never shared externally.
        _chat_history:  Private conversation history passed to the OpenAI API.
        turn_count:     Number of messages generated so far in this session.
    """

    def __init__(self, persona_id: str) -> None:
        """
        Initialise the TesterAgent with a specific persona.

        Args:
            persona_id: A key from test_config.PERSONAS. Raises KeyError if
                        the persona does not exist.
        """
        self.persona_id: str = persona_id
        self.persona: PersonaConfig = get_persona(persona_id)
        self.turn_count: int = 0

        # Private, isolated OpenAI client — zero coupling with the bot.
        self._client: OpenAI = OpenAI()

        # Seed the conversation with the persona's system prompt.
        self._chat_history: list[dict[str, str]] = [
            {
                "role": "system",
                "content": self.persona["system_prompt"],
            }
        ]

        logger.info(
            "TesterAgent initialised | persona_id=%s | display_name=%s",
            persona_id,
            self.persona["display_name"],
        )

    # ------------------------------------------------------------------
    # Public Interface
    # ------------------------------------------------------------------

    def generate_next_message(self, bot_reply: str) -> str:
        """
        Generate the next simulated user message based on the persona and
        the bot's last reply.

        When called for the very first turn, pass an empty string as
        ``bot_reply``; the agent will produce an opening message based
        solely on its persona system prompt.

        Args:
            bot_reply: The bot's most recent response text. Pass ``""`` to
                       trigger the opening message.

        Returns:
            The generated user message string.  May equal ``TERMINATION_SIGNAL``
            ("TEST_COMPLETE") when the persona determines its mission is done.

        Raises:
            RuntimeError: If all retry attempts fail due to API errors.
        """
        # Inject the bot's reply into our private history so the LLM can
        # see the conversation context — but this history is OURS only.
        #
        # ROLE CONVENTION (critical):
        #   "user"      = the restaurant bot's messages (what we are reacting to)
        #   "assistant" = our own previously generated tester messages (our own voice)
        #
        # This matches the standard OpenAI convention where "assistant" is the LLM's
        # own prior output.  Inverting these caused the model to continue writing in
        # the bot's voice instead of the customer persona's voice.
        if bot_reply:
            self._chat_history.append(
                {
                    "role": "user",   # bot reply = the "user" stimulus we are reacting to
                    "content": bot_reply,
                }
            )
        else:
            # First turn: add a trigger so the LLM knows to send the opener.
            self._chat_history.append(
                {
                    "role": "user",
                    "content": (
                        "[The conversation has just started. "
                        "Generate your opening message now based on your persona mission.]"
                    ),
                }
            )

        generated_message = self._call_openai_with_retry()

        # Record our own output as "assistant" — our own voice in the history.
        self._chat_history.append(
            {
                "role": "assistant",
                "content": generated_message,
            }
        )

        self.turn_count += 1
        logger.debug(
            "Turn %d generated | persona=%s | signal=%s | message_preview=%.80s",
            self.turn_count,
            self.persona_id,
            TERMINATION_SIGNAL in generated_message,
            generated_message,
        )

        return generated_message

    @property
    def is_terminated(self) -> bool:
        """
        Returns True if the last generated message contained the
        TERMINATION_SIGNAL, indicating the persona has finished its mission.

        Checks the last 'assistant' role entry in the private chat history,
        which is where our own generated tester messages are stored.
        """
        tester_messages = [
            m["content"] for m in self._chat_history if m["role"] == "assistant"
        ]
        if not tester_messages:
            return False
        return TERMINATION_SIGNAL in tester_messages[-1]

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _call_openai_with_retry(self) -> str:
        """
        Calls the OpenAI Chat Completions API with exponential backoff retry.

        Retries on transient errors (timeout, connection issues, rate limits).
        Raises RuntimeError after MAX_RETRIES exhausted.

        Returns:
            The message content string from the model.

        Raises:
            RuntimeError: When all retries are exhausted.
        """
        last_exception: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._client.chat.completions.create(
                    model=TESTER_MODEL,
                    messages=self._chat_history,  # type: ignore[arg-type]
                    max_completion_tokens=1024,
                )
                content = response.choices[0].message.content or ""
                return content.strip()

            except (APITimeoutError, APIConnectionError) as exc:
                last_exception = exc
                delay = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "TesterAgent API transient error (attempt %d/%d): %s — "
                    "retrying in %.1fs",
                    attempt,
                    MAX_RETRIES,
                    exc,
                    delay,
                )
                time.sleep(delay)

            except RateLimitError as exc:
                last_exception = exc
                delay = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)) * 2
                logger.warning(
                    "TesterAgent rate-limited (attempt %d/%d) — "
                    "retrying in %.1fs",
                    attempt,
                    MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)

            except APIStatusError as exc:
                # Non-retryable API errors (4xx client errors except 429).
                logger.error(
                    "TesterAgent non-retryable API error (status=%d): %s",
                    exc.status_code,
                    exc.message,
                )
                raise RuntimeError(
                    f"TesterAgent OpenAI API error (status {exc.status_code}): {exc.message}"
                ) from exc

        raise RuntimeError(
            f"TesterAgent failed after {MAX_RETRIES} retries. "
            f"Last error: {last_exception}"
        )
