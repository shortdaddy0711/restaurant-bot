"""
CLI Regression Runner — runs all 8 personas sequentially and prints a summary.
Usage: python run_regression.py [persona_id ...]
       python run_regression.py              # runs all 8 in order
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

import dotenv

dotenv.load_dotenv()

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s — %(message)s",
)
# Quieten noisy SDK loggers
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("openai").setLevel(logging.ERROR)

from test_config import get_persona_ids, get_persona
from test_runner import run_automated_session
# Priority run order: Persona 4 (the target fix), then MEDIUM-risk (6,7,8), then LOW-risk (1,2,3,5)
DEFAULT_ORDER = [
    "persona_4_rushed_executive",   # TARGET FIX — multi-intent queue
    "persona_6_browse_to_buy",      # MEDIUM — Menu → Order handoff
    "persona_7_book_then_browse",   # MEDIUM — Reservation → Menu handoff
    "persona_8_order_then_complain",# MEDIUM — Order → Complaints handoff
    "persona_1_angry_customer",     # LOW
    "persona_2_vegan_allergy",      # LOW
    "persona_3_prompt_injector",    # LOW
    "persona_5_direct_orderer",     # LOW
]

MAX_TURNS = 10   # Hard ceiling per session


async def run_all(persona_ids: list[str]):
    results = []

    for pid in persona_ids:
        persona = get_persona(pid)
        print(f"\n{'='*65}")
        print(f"▶  {persona['display_name']}  ({pid})")
        print(f"{'='*65}")

        try:
            log_path = await run_automated_session(pid, max_turns=MAX_TURNS)

            # Parse the saved log for a quick summary
            with open(log_path, encoding="utf-8") as f:
                log = json.load(f)

            turns = log.get("total_turns", "?")
            reason = log.get("termination_reason", "?")
            conv = log.get("conversation", [])

            # Print each turn
            for entry in conv:
                role_icon = "🧑" if entry["role"] == "tester" else "🤖"
                agent_tag = f" [{entry.get('active_agent', '')}]" if entry["role"] == "bot" else ""
                content = entry["content"] or ""
                # Truncate long responses for readability
                if len(content) > 400:
                    content = content[:400] + "…"
                print(f"\n  {role_icon} Turn {entry['turn']}{agent_tag}")
                print(f"  {content}")

            print(f"\n  ── Result: {reason} in {turns} turn(s) ──")
            results.append({"persona": pid, "status": reason, "turns": turns, "log": log_path})

        except Exception as exc:
            print(f"  ❌ ERROR: {exc}")
            results.append({"persona": pid, "status": "ERROR", "turns": 0, "log": None})

    # Final summary table
    print(f"\n\n{'='*65}")
    print("REGRESSION SUMMARY")
    print(f"{'='*65}")
    print(f"  {'Persona':<42} {'Result':<20} {'Turns'}")
    print(f"  {'-'*42} {'-'*20} {'-'*5}")
    for r in results:
        icon = "✅" if r["status"] == "TEST_COMPLETE" else ("⚠️ " if r["status"] == "MAX_TURNS_REACHED" else "❌")
        print(f"  {icon} {r['persona']:<40} {r['status']:<20} {r['turns']}")
    print()


if __name__ == "__main__":
    ids = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_ORDER
    asyncio.run(run_all(ids))
