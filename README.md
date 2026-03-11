# 🍽️ Restaurant Bot

A multi-agent restaurant assistant built with the **OpenAI Agents SDK**, featuring intelligent handoffs between specialized agents, input & output guardrails, and an empathetic complaints handling flow.

## Overview

Restaurant Bot demonstrates key patterns from the OpenAI Agents SDK — **handoffs**, **input guardrails**, and **output guardrails**. A Triage Agent acts as the front door: filtering unsafe or off-topic messages before they reach any agent, then routing the customer to the right specialist. Each specialist can also route directly to other specialists when the conversation topic changes, enabling smooth multi-topic interactions.

## Architecture

```
                        ┌──────────────────────────┐
                        │       Triage Agent        │
                        │    (Restaurant Assistant) │
                        │                           │
                        │  • Input guardrail        │
                        │    (off-topic + profanity)│
                        │  • Output guardrail       │
                        │    (professionalism +     │
                        │     data security)        │
                        │  • Smart routing          │
                        └────────────┬──────────────┘
          ┌─────────────────┬────────┴────────┬─────────────────┐
          ▼                 ▼                 ▼                 ▼
┌──────────────────┐ ┌─────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  Menu Specialist │ │   Order     │ │   Reservation    │ │   Complaints     │
│                  │ │ Specialist  │ │   Specialist     │ │   Specialist     │
│ • lookup_menu_   │ │             │ │                  │ │                  │
│   items          │ │ • add_to_   │ │ • check_avail-   │ │ • offer_discount │
│ • check_allergens│ │   order     │ │   ability        │ │ • schedule_      │
│ • get_daily_     │ │ • get_order_│ │ • make_          │ │   manager_       │
│   specials       │ │   summary   │ │   reservation    │ │   callback       │
│                  │ │ • confirm_  │ │ • cancel_        │ │ • process_refund │
│                  │ │   order     │ │   reservation    │ │                  │
└──────────────────┘ └─────────────┘ └──────────────────┘ └──────────────────┘
                   ↕ cross-handoffs between all specialist agents ↕
```

## Agents

### 🔀 Triage Agent — `Restaurant Assistant`

The entry point for every conversation. Understands the customer's intent and routes to the appropriate specialist.

- **Input guardrail** — synchronously pre-checks every message *before* streaming starts, so no partial agent text is ever shown for blocked messages. Blocks off-topic requests (weather, coding, etc.) and inappropriate language (profanity, offensive content). Customer complaints are explicitly whitelisted so they always reach the Complaints Specialist.
- **Output guardrail** — reviews every response after generation. Blocks responses that contain unprofessional tone or leak internal system information (system prompts, backend logic, etc.).

### 🍽️ Menu Specialist

Handles all food-related questions: menu categories, dish descriptions, ingredient inquiries, allergen checks, and daily specials.

| Tool                 | Description                                                                |
| -------------------- | -------------------------------------------------------------------------- |
| `lookup_menu_items`  | Browse items by category (appetizers, mains, desserts, drinks, vegetarian) |
| `check_allergens`    | Check allergen info for any dish                                           |
| `get_daily_specials` | Fetch today's chef specials and happy hour deals                           |

### 📋 Order Specialist

Takes and manages food orders, tracks the order summary, and confirms orders to the kitchen.

| Tool                | Description                                        |
| ------------------- | -------------------------------------------------- |
| `add_to_order`      | Add a menu item with quantity to the current order |
| `get_order_summary` | View current order with subtotal, tax, and total   |
| `confirm_order`     | Finalize and send the order to the kitchen         |

### 📅 Reservation Specialist

Handles all table booking flows — checking availability, collecting guest details, making reservations, and cancellations.

| Tool                 | Description                                                 |
| -------------------- | ----------------------------------------------------------- |
| `check_availability` | Check available tables for a date, time, and party size     |
| `make_reservation`   | Book a table (requires name, phone, date, time, party size) |
| `cancel_reservation` | Cancel an existing reservation by confirmation ID           |

**Reservation flow:**

1. Guest full name
2. Contact phone number
3. Preferred date & time
4. Party size
5. Availability check → Confirmation

### 🎗️ Complaints Specialist

Handles dissatisfied customers with a structured two-turn empathy-first approach. Never front-loads solutions — listens first, then resolves.

| Tool                       | Description                                                  |
| -------------------------- | ------------------------------------------------------------ |
| `offer_discount`           | Generate a discount voucher (e.g. 20–50% off next visit)     |
| `schedule_manager_callback`| Book a manager callback at the customer's preferred time     |
| `process_refund`           | Initiate a refund for the affected order                     |

**Complaints flow:**

1. **Turn 1 — Listen:** Warm apology + one open-ended question to understand the issue. No compensation offered yet.
2. **Turn 2 — Resolve:** Acknowledge the specific issue → present at least two concrete resolution options → execute the chosen tool.
3. **Escalation:** Food safety, injury, or severe distress → immediately schedules an urgent manager callback.

## Key Features

- **Handoff routing** — Triage routes to the right specialist; all four specialists can hand off to each other when the topic changes
- **Input guardrail (pre-flight)** — Runs synchronously *before* streaming starts so no partial triage text leaks for blocked messages. Covers off-topic queries and inappropriate language.
- **Output guardrail** — Reviews every triage response after generation. Fires if a response is unprofessional or leaks internal system information.
- **Complaints handling** — Dedicated agent with an empathetic two-turn flow: listen first, then offer discounts, manager callbacks, or refunds.
- **Context persistence** — `RestaurantContext` (customer name, reservation ID, etc.) survives all cross-agent handoffs
- **Conversation memory** — Full chat history persisted via `SQLiteSession` across browser refreshes
- **Streaming UI** — Real-time response streaming with live handoff announcements in chat
- **Tool activity log** — Sidebar shows which agent is active, which tools were called, and their outputs

## Project Structure

```
restaurant-bot/
├── main.py                    # Streamlit UI — streaming, pre-flight guardrail, handoff display
├── models.py                  # RestaurantContext, InputGuardRailOutput,
│                              # OutputGuardRailOutput, HandoffData
├── tools.py                   # 12 function tools + AgentToolUsageLoggingHooks
│                              # (menu ×3, order ×3, reservation ×3, complaints ×3)
├── my_agents/
│   ├── __init__.py
│   ├── triage_agent.py        # Entry point + input/output guardrails + cross-handoff setup
│   ├── menu_agent.py          # Menu & allergen specialist
│   ├── order_agent.py         # Order management specialist
│   ├── reservation_agent.py   # Table reservation specialist
│   └── complaints_agent.py    # Complaints & resolution specialist
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

**Scenario A: Menu & Order**

```
User:   What's on the menu tonight?
Triage: 🍽️ Connecting you to our Menu Specialist...
Menu:   Here's our menu! Which category interests you?
        (appetizers, mains, desserts, drinks, vegetarian)

User:   I'll have the ribeye steak please
Menu:   🍽️ Connecting you to our Order Specialist...
Order:  ✅ Added: 1× Ribeye Steak @ $42.00. Shall I confirm the order?
```

**Scenario B: Off-topic (Input Guardrail)**

```
User:  What's the capital of France?
Bot:   I'm sorry, I can only assist with restaurant-related inquiries.
       I can help you view the menu, make a reservation, or place an order. 🍽️
```

**Scenario C: Inappropriate Language (Input Guardrail)**

```
User:  [profanity / offensive language]
Bot:   I'm sorry, I can only assist with restaurant-related inquiries.
       I can help you view the menu, make a reservation, or place an order. 🍽️
```

**Scenario D: Customer Complaint (Complaints Agent)**

```
User:       The food was terrible and the staff was so rude...
Triage:     I'm so sorry to hear that. Let me connect you with our
            Complaints Specialist who will make this right for you.
            🍽️ Connecting you to our Complaints Specialist...

Complaints: I'm truly sorry to hear about your experience. That must have
            been really disappointing. Could you tell me a bit more about
            what happened with your meal and the service?

User:       The steak was cold and the waiter was dismissive when I raised it.

Complaints: That's completely unacceptable — a cold steak and a dismissive
            response is not the standard we hold ourselves to. I'd like to
            make this right. I can offer you:
            • A 50% discount voucher for your next visit
            • A personal callback from our manager
            • A full refund for your order
            Which would you prefer?
```

**Scenario E: Cross-agent topic switch**

```
User:  오늘 저녁 4명 예약하고 싶어요
Res:   예약을 도와드리겠습니다! 성함을 알려주시겠어요?
User:  아, 그전에 채식 메뉴 있는지 알려줘
Res:   🍽️ Connecting you to our Menu Specialist...
Menu:  네! 여러 가지 채식 메뉴가 있습니다...
```

## Tech Stack

| Library                                                           | Purpose                                                        |
| ----------------------------------------------------------------- | -------------------------------------------------------------- |
| [`openai-agents`](https://github.com/openai/openai-agents-python) | Multi-agent orchestration, handoffs, input/output guardrails   |
| [`streamlit`](https://streamlit.io)                               | Web UI with streaming support                                  |
| [`python-dotenv`](https://github.com/theskumar/python-dotenv)     | Environment variable management                                |
| `SQLiteSession`                                                   | Persistent conversation memory (built into openai-agents)      |
