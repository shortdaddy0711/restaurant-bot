# 🍽️ Restaurant Bot

A multi-agent restaurant assistant built with the **OpenAI Agents SDK**, featuring intelligent handoffs between specialized agents for menu inquiries, order taking, and table reservations.

## Overview

Restaurant Bot demonstrates the **handoff** pattern from the OpenAI Agents SDK. A Triage Agent acts as the front door — understanding what the customer wants and routing them seamlessly to the right specialist. Each specialist can also route directly to other specialists when the conversation topic changes, enabling smooth multi-topic interactions.

## Architecture

```
                        ┌─────────────────────┐
                        │   Triage Agent       │
                        │  (Restaurant         │
                        │   Assistant)         │
                        │                      │
                        │  • Input guardrail   │
                        │  • Smart routing     │
                        └──────────┬───────────┘
               ┌──────────────────┼──────────────────┐
               ▼                  ▼                  ▼
   ┌───────────────────┐ ┌────────────────┐ ┌─────────────────────┐
   │   Menu Specialist  │ │Order Specialist│ │Reservation Specialist│
   │                   │ │                │ │                     │
   │ • lookup_menu_    │ │ • add_to_order │ │ • check_availability│
   │   items           │ │ • get_order_   │ │ • make_reservation  │
   │ • check_allergens │ │   summary      │ │ • cancel_reservation│
   │ • get_daily_      │ │ • confirm_order│ │                     │
   │   specials        │ │                │ │                     │
   └───────────────────┘ └────────────────┘ └─────────────────────┘
          ↕ cross-handoffs between all specialist agents ↕
```

## Agents

### 🔀 Triage Agent — `Restaurant Assistant`
The entry point for every conversation. Understands the customer's intent and routes to the appropriate specialist. Includes an **input guardrail** that blocks off-topic requests (e.g., weather, coding questions).

### 🍽️ Menu Specialist
Handles all food-related questions: menu categories, dish descriptions, ingredient inquiries, allergen checks, and daily specials.

| Tool | Description |
|------|-------------|
| `lookup_menu_items` | Browse items by category (appetizers, mains, desserts, drinks, vegetarian) |
| `check_allergens` | Check allergen info for any dish |
| `get_daily_specials` | Fetch today's chef specials and happy hour deals |

### 📋 Order Specialist
Takes and manages food orders, tracks the order summary, and confirms orders to the kitchen.

| Tool | Description |
|------|-------------|
| `add_to_order` | Add a menu item with quantity to the current order |
| `get_order_summary` | View current order with subtotal, tax, and total |
| `confirm_order` | Finalize and send the order to the kitchen |

### 📅 Reservation Specialist
Handles all table booking flows — checking availability, collecting guest details, making reservations, and cancellations.

| Tool | Description |
|------|-------------|
| `check_availability` | Check available tables for a date, time, and party size |
| `make_reservation` | Book a table (requires name, phone, date, time, party size) |
| `cancel_reservation` | Cancel an existing reservation by confirmation ID |

**Reservation flow:**
1. Guest full name
2. Contact phone number
3. Preferred date & time
4. Party size
5. Availability check → Confirmation

## Key Features

- **Handoff routing** — Triage routes to the right specialist; specialists can hand off to each other when the topic changes
- **Input guardrail** — Blocks non-restaurant questions before they reach any agent
- **Context persistence** — Reservation confirmation IDs are stored in `RestaurantContext` and survive cross-agent handoffs (no awkward "please provide your confirmation ID" after you just got one)
- **Conversation memory** — Full chat history persisted via `SQLiteSession` across browser refreshes
- **Streaming UI** — Real-time response streaming with live handoff announcements in chat
- **Tool activity log** — Sidebar shows which tools each agent called and their outputs

## Project Structure

```
restaurant-bot/
├── main.py                    # Streamlit UI with streaming + handoff display
├── models.py                  # RestaurantContext, HandoffData, InputGuardRailOutput
├── tools.py                   # 9 function tools + AgentToolUsageLoggingHooks
├── my_agents/
│   ├── __init__.py
│   ├── triage_agent.py        # Entry point agent + guardrail + cross-handoff setup
│   ├── menu_agent.py          # Menu & allergen specialist
│   ├── order_agent.py         # Order management specialist
│   └── reservation_agent.py  # Table reservation specialist
├── pyproject.toml
├── .python-version            # Python 3.13
└── restaurant-memory.db       # Auto-created SQLite session store
```

## Getting Started

### Prerequisites
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI API key

### Installation

```bash
git clone <repo-url>
cd restaurant-bot

# Install dependencies
uv sync
```

### Configuration

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...
```

### Run

```bash
uv run streamlit run main.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

## Example Interactions

```
User:  메뉴 좀 보고 싶어요
Triage: 🍽️ Connecting you to our Menu Specialist...
Menu:  저희 메뉴를 안내해 드릴게요! 어떤 카테고리가 궁금하신가요?
       (appetizers, mains, desserts, drinks, vegetarian)

---

User:  오늘 저녁 4명 예약하고 싶어요
Triage: 🍽️ Connecting you to our Reservation Specialist...
Res:   예약을 도와드리겠습니다! 먼저 성함을 알려주시겠어요?
User:  홍길동이에요
Res:   감사합니다! 연락 가능한 전화번호도 알려주시겠어요?
User:  010-1234-5678
Res:   희망하시는 날짜와 시간을 알려주세요!

---

User:  아, 그전에 채식 메뉴 있는지 알려줘
Res:   🍽️ Connecting you to our Menu Specialist...
Menu:  네! 여러 가지 채식 메뉴가 있습니다...
```

## Tech Stack

| Library | Purpose |
|---------|---------|
| [`openai-agents`](https://github.com/openai/openai-agents-python) | Multi-agent orchestration, handoffs, guardrails |
| [`streamlit`](https://streamlit.io) | Web UI with streaming support |
| [`python-dotenv`](https://github.com/theskumar/python-dotenv) | Environment variable management |
| `SQLiteSession` | Persistent conversation memory (built into openai-agents) |
