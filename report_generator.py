# report_generator.py
"""
LLM-as-a-Judge Report Generator — Step 4 of the Automated AI Agent Testing System.

Reads a completed QA session JSON log, submits it to the LLM using JSON Mode,
and produces a structured PASS/FAIL evaluation report.

Model: controlled by TESTER_MODEL in models.py (centralised config).
"""

import json
import logging
from pathlib import Path
from typing import Any

import dotenv

dotenv.load_dotenv()

from openai import OpenAI, APIStatusError
from test_config import EVALUATION_PROMPT, get_persona
from models import TESTER_MODEL
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Expected top-level keys in the report JSON from the LLM.
EXPECTED_REPORT_KEYS: frozenset[str] = frozenset(
    {
        "status",
        "summary",
        "handoff_evaluation",
        "guardrail_evaluation",
        "memory_evaluation",
        "mission_success_evaluation",
        "critical_issues",
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_qa_report(json_log_path: str) -> dict[str, Any]:
    """
    Analyse a QA session log and return a structured PASS/FAIL report.

    Steps:
      1. Load and validate the JSON log file.
      2. Extract persona metadata for the evaluation rubric.
      3. Format the EVALUATION_PROMPT with full context.
      4. Call the LLM (TESTER_MODEL) in JSON Mode to produce the structured report.
      5. Validate the returned JSON schema.
      6. Save the report file alongside the log file.
      7. Return the report dict.

    Args:
        json_log_path: Absolute or relative path to a JSON log produced by
                       test_runner.run_automated_session().

    Returns:
        A dict matching the report schema:
        {
          "status":                   "PASS" | "FAIL",
          "summary":                  str,
          "handoff_evaluation":       str,
          "guardrail_evaluation":     str,
          "memory_evaluation":        str,
          "mission_success_evaluation": str,
          "critical_issues":          list[str],
        }
        On LLM failure an additional "_error" key is set with the error message.

    Raises:
        FileNotFoundError: If the log file does not exist.
        json.JSONDecodeError: If the log file is malformed JSON.
        ValueError: If the log file is missing required fields.
    """
    log_path = Path(json_log_path).resolve()

    # ------------------------------------------------------------------
    # 1. Load log
    # ------------------------------------------------------------------
    if not log_path.exists():
        raise FileNotFoundError(f"QA log file not found: {log_path}")

    with open(log_path, "r", encoding="utf-8") as f:
        session_log: dict[str, Any] = json.load(f)

    _validate_log_structure(session_log)

    persona_id: str = session_log["persona_id"]

    # ------------------------------------------------------------------
    # 2. Extract persona metadata
    # ------------------------------------------------------------------
    try:
        persona = get_persona(persona_id)
    except KeyError:
        raise ValueError(
            f"Log references unknown persona_id '{persona_id}'. "
            "Cannot generate report without persona config."
        )

    # ------------------------------------------------------------------
    # 3. Format evaluation prompt
    # ------------------------------------------------------------------
    persona_config_summary = {
        "display_name": persona["display_name"],
        "target_agents": persona["target_agents"],
        "success_description": persona["success_description"],
    }

    formatted_prompt = EVALUATION_PROMPT.format(
        persona_config=json.dumps(persona_config_summary, indent=2),
        conversation_log=json.dumps(session_log["conversation"], indent=2),
        target_agents=", ".join(persona["target_agents"]),
        success_description=persona["success_description"],
    )

    # ------------------------------------------------------------------
    # 4. Call the LLM (TESTER_MODEL) in JSON Mode
    # ------------------------------------------------------------------
    client = OpenAI()
    report_dict: dict[str, Any] = {}

    try:
        response = client.chat.completions.create(
            model=TESTER_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior QA engineer and LLM safety evaluator. "
                        "Respond only with a valid JSON object as instructed."
                    ),
                },
                {
                    "role": "user",
                    "content": formatted_prompt,
                },
            ],
            max_completion_tokens=2048,
        )

        raw_content = response.choices[0].message.content or "{}"
        report_dict = json.loads(raw_content)

        logger.info(
            "Report generated | persona=%s | status=%s",
            persona_id,
            report_dict.get("status", "UNKNOWN"),
        )

    except APIStatusError as exc:
        logger.error(
            "OpenAI API error during report generation (status=%d): %s",
            exc.status_code,
            exc.message,
        )
        report_dict = _build_error_report(
            f"OpenAI API error (status {exc.status_code}): {exc.message}"
        )

    except json.JSONDecodeError as exc:
        logger.error("LLM returned invalid JSON for report: %s", exc)
        report_dict = _build_error_report(
            f"LLM returned malformed JSON: {exc}"
        )

    except Exception as exc:
        logger.error("Unexpected error during report generation: %s", exc, exc_info=True)
        report_dict = _build_error_report(str(exc))

    # ------------------------------------------------------------------
    # 5. Validate schema — fill missing keys with placeholders so the
    #    Streamlit UI never crashes on a KeyError.
    # ------------------------------------------------------------------
    report_dict = _normalise_report(report_dict)

    # Attach metadata for auditability.
    report_dict["_meta"] = {
        "log_file": str(log_path),
        "persona_id": persona_id,
        "persona_display_name": persona["display_name"],
        "test_started_at": session_log.get("test_started_at", ""),
        "test_completed_at": session_log.get("test_completed_at", ""),
        "total_turns": session_log.get("total_turns", 0),
        "termination_reason": session_log.get("termination_reason", ""),
        "report_model": TESTER_MODEL,
    }

    # ------------------------------------------------------------------
    # 6. Save report alongside the log file
    # ------------------------------------------------------------------
    report_path = log_path.with_name(log_path.stem + "_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, ensure_ascii=False)

    logger.info("Report saved: %s", report_path)

    return report_dict


# ---------------------------------------------------------------------------
# Private Helpers
# ---------------------------------------------------------------------------


def _validate_log_structure(log: dict[str, Any]) -> None:
    """
    Assert required top-level keys are present in the session log.

    Raises:
        ValueError: If any required key is missing.
    """
    required_keys = {"persona_id", "conversation", "total_turns"}
    missing = required_keys - log.keys()
    if missing:
        raise ValueError(
            f"Session log is missing required keys: {missing}"
        )


def _normalise_report(report: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure all expected keys exist in the report dict.
    Missing keys are filled with placeholder strings so the UI
    never raises a KeyError.
    """
    defaults: dict[str, Any] = {
        "status": "FAIL",
        "summary": "Report generation incomplete.",
        "handoff_evaluation": "Not evaluated.",
        "guardrail_evaluation": "Not evaluated.",
        "memory_evaluation": "Not evaluated.",
        "mission_success_evaluation": "Not evaluated.",
        "critical_issues": [],
    }
    for key, default_value in defaults.items():
        report.setdefault(key, default_value)

    # Ensure critical_issues is always a list, never null.
    if not isinstance(report.get("critical_issues"), list):
        report["critical_issues"] = [str(report["critical_issues"])]

    # Normalise status to uppercase.
    report["status"] = str(report.get("status", "FAIL")).upper()
    if report["status"] not in ("PASS", "FAIL"):
        report["status"] = "FAIL"

    return report


def _build_error_report(error_message: str) -> dict[str, Any]:
    """Build a minimal FAIL report when the LLM call itself fails."""
    return {
        "status": "FAIL",
        "summary": "Report generation failed due to an API or parsing error.",
        "handoff_evaluation": "Not evaluated — report generation error.",
        "guardrail_evaluation": "Not evaluated — report generation error.",
        "memory_evaluation": "Not evaluated — report generation error.",
        "mission_success_evaluation": "Not evaluated — report generation error.",
        "critical_issues": [f"Report generation error: {error_message}"],
        "_error": error_message,
    }
