from pydantic import BaseModel
from typing import Optional

# ---------------------------------------------------------------------------
# Centralised LLM model configuration
# ---------------------------------------------------------------------------
# APP_MODEL     — used by the Restaurant Bot itself (agents, intent decomposer)
# TESTER_MODEL  — used by QA infrastructure (tester engine, report generator)
# Change these two values to switch models across the entire project.
# ---------------------------------------------------------------------------
APP_MODEL: str = "gpt-5-mini"
TESTER_MODEL: str = "gpt-5-mini"

# ---------------------------------------------------------------------------
# Business constants
# ---------------------------------------------------------------------------
TAX_RATE: float = 0.10  # 10 % sales tax applied to all orders


class OrderItem(BaseModel):
    """A single line item in the customer's live order basket."""

    name: str
    quantity: int
    unit_price: float


class RestaurantContext(BaseModel):

    model_config = {"arbitrary_types_allowed": True}

    customer_name: str = "Guest"
    party_size: Optional[int] = None
    dietary_preferences: Optional[str] = None
    phone_number: Optional[str] = None
    reservation_confirmation_id: Optional[str] = None

    # Intent queue — populated by the test runner when a customer message contains
    # multiple distinct intents. Triage processes each item in order, handing off
    # to the appropriate specialist and cycling back until the list is empty.
    pending_intents: list[str] = []

    # Set to True for the duration of a multi-intent queue session so that
    # Triage generates a combined summary once the queue is exhausted.
    is_queue_session: bool = False

    # Live order basket — persists across handoffs within a session.
    order_items: list[OrderItem] = []


class InputGuardRailOutput(BaseModel):

    is_off_topic: bool
    reason: str


class OutputGuardRailOutput(BaseModel):

    is_unprofessional: bool
    reason: str


class HandoffData(BaseModel):

    to_agent_name: str
    request_type: str
    request_description: str
    reason: str
