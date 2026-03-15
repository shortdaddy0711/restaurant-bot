import streamlit as st
import random
from agents import function_tool, AgentHooks, Agent, Tool, RunContextWrapper
from models import RestaurantContext, OrderItem, TAX_RATE
from menu_data import (
    MENU,
    DAILY_SPECIALS,
    PRICE_LOOKUP,
    ALLERGEN_LOOKUP,
    format_menu_item,
    format_daily_special,
)


# =============================================================================
# Mock behaviour constants (tune for demo / testing)
# =============================================================================

AVAILABILITY_PROBABILITY: float = 0.75  # 75 % chance a requested slot is free
HAPPY_HOUR_DISCOUNTS: list[str] = ["10%", "15%", "20%"]


# =============================================================================
# ORDER HELPERS  (DRY — used by get_order_summary & confirm_order)
# =============================================================================


def _format_order_lines(items: list[OrderItem]) -> list[str]:
    """Return customer-facing line items."""
    return [
        f"• {item.quantity}x {item.name} — ${item.quantity * item.unit_price:.2f}"
        for item in items
    ]


def _compute_totals(items: list[OrderItem]) -> tuple[float, float, float]:
    """Return (subtotal, tax, total) for a list of order items."""
    subtotal = sum(item.quantity * item.unit_price for item in items)
    tax = subtotal * TAX_RATE
    total = subtotal + tax
    return subtotal, tax, total


def _order_summary_block(items: list[OrderItem]) -> str:
    """Build the subtotal / tax / total block used in summaries."""
    lines = _format_order_lines(items)
    subtotal, tax, total = _compute_totals(items)
    return (
        "\n".join(lines)
        + f"\n\n💰 Subtotal: ${subtotal:.2f}"
        + f"\n🧾 Tax ({TAX_RATE:.0%}): ${tax:.2f}"
        + f"\n✅ Total: ${total:.2f}"
    )


# =============================================================================
# MENU AGENT TOOLS
# =============================================================================


@function_tool
def lookup_menu_items(context: RestaurantContext, category: str) -> str:
    """
    Browse our menu by category — see dishes, prices, and descriptions.

    Args:
        category: Menu section to browse (appetizers, mains, desserts, drinks, or vegetarian)
    """
    key = category.lower()
    items = MENU.get(key, MENU.get("mains"))
    label = key if key in MENU else "mains"

    formatted = [format_menu_item(item) for item in items]
    return f"🍽️ {label.title()} Menu:\n" + "\n".join(formatted)


@function_tool
def check_allergens(context: RestaurantContext, dish_name: str) -> str:
    """
    Check allergen information for a specific dish.

    Args:
        dish_name: Name of the dish to check
    """
    key = dish_name.lower()

    # Fuzzy match against the centralised allergen lookup
    for known_name, allergens in ALLERGEN_LOOKUP.items():
        if known_name in key or key in known_name:
            if allergens:
                return (
                    f"⚠️ Allergen info for **{dish_name}**:\n"
                    f"Contains: {', '.join(allergens)}\n"
                    "Please inform your server of any allergies before ordering."
                )
            else:
                return f"✅ **{dish_name}** contains no major allergens. Always inform your server of any specific allergies."

    return (
        f"ℹ️ Allergen info for **{dish_name}** not found in our database.\n"
        "Please ask your server directly for detailed allergen information."
    )


@function_tool
def get_daily_specials(context: RestaurantContext) -> str:
    """
    Get today's daily specials and chef's recommendations.
    """
    formatted = [format_daily_special(item) for item in DAILY_SPECIALS]
    discount = random.choice(HAPPY_HOUR_DISCOUNTS)
    return (
        "🎉 Today's Daily Specials:\n\n"
        + "\n".join(formatted)
        + f"\n\n🏷️ Happy Hour (5–7PM): {discount} off all drinks!"
    )


# =============================================================================
# ORDER AGENT TOOLS
# =============================================================================


@function_tool
def add_to_order(context: RestaurantContext, item_name: str, quantity: int = 1) -> str:
    """
    Add a dish or drink to the guest's current order. The item must be on our menu.

    Args:
        item_name: Name of the menu item to add
        quantity: How many to add (default: 1)
    """
    key = item_name.lower()

    # Fuzzy match against the centralised price lookup
    price = None
    for known_key, known_price in PRICE_LOOKUP.items():
        if known_key in key or key in known_key:
            price = known_price
            break

    # C2 fix: reject unknown items instead of silently billing $20
    if price is None:
        return (
            f"❌ Sorry, '{item_name}' is not on our menu.\n"
            "Please check the menu and try again, or ask me for recommendations!"
        )

    subtotal = price * quantity

    # Persist to context — merge into existing entry if item already in basket
    existing = next(
        (item for item in context.order_items if item.name.lower() == item_name.lower()),
        None,
    )
    if existing:
        existing.quantity += quantity
    else:
        context.order_items.append(
            OrderItem(name=item_name.title(), quantity=quantity, unit_price=price)
        )

    return (
        f"✅ Added to your order:\n"
        f"• {quantity}x {item_name.title()} @ ${price:.2f} each\n"
        f"• Subtotal: ${subtotal:.2f}\n"
        "Use 'get order summary' to see your full order."
    )


@function_tool
def get_order_summary(context: RestaurantContext) -> str:
    """
    Get a summary of the current order with total.
    """
    if not context.order_items:
        return (
            f"📋 Your order is currently empty, {context.customer_name}.\n"
            "Add some items and I'll show you a full summary!"
        )

    return (
        f"📋 Current Order Summary for {context.customer_name}:\n\n"
        + _order_summary_block(context.order_items)
    )


@function_tool
def confirm_order(context: RestaurantContext) -> str:
    """
    Finalize and confirm the current order. This sends the order to the kitchen.
    """
    order_id = f"ORD-{random.randint(1000, 9999)}"
    estimated_time = random.randint(20, 35)

    if context.order_items:
        order_detail = (
            "\n📋 Items Sent to Kitchen:\n"
            + _order_summary_block(context.order_items)
            + "\n"
        )
        # Clear the basket now that the order is confirmed
        context.order_items = []
    else:
        order_detail = "\n(No items in basket — please add items before confirming.)\n"

    return (
        f"🎉 Order Confirmed!\n\n"
        f"📋 Order ID: {order_id}\n"
        f"👤 Customer: {context.customer_name}\n"
        + order_detail
        + f"\n⏱️ Estimated preparation time: {estimated_time} minutes\n"
        f"🔔 Your server will bring your order shortly.\n"
        "Thank you for dining with us!"
    )


# =============================================================================
# RESERVATION AGENT TOOLS
# =============================================================================


@function_tool
def check_availability(
    context: RestaurantContext, date: str, time: str, party_size: int
) -> str:
    """
    Check table availability for a given date, time, and party size.

    Args:
        date: Desired reservation date (e.g., 'March 15' or '2026-03-15')
        time: Desired reservation time (e.g., '7:00 PM')
        party_size: Number of guests
    """
    available_slots = ["6:00 PM", "6:30 PM", "7:00 PM", "8:00 PM", "8:30 PM"]
    is_available = random.random() < AVAILABILITY_PROBABILITY

    if is_available:
        alternatives = random.sample(available_slots, 3)
        return (
            f"✅ Great news! A table for {party_size} is available on {date} at {time}.\n\n"
            f"Alternative slots also available:\n"
            + "\n".join(f"• {slot}" for slot in alternatives)
            + "\n\nWould you like me to confirm this reservation?"
        )
    else:
        alternatives = random.sample(available_slots, 3)
        return (
            f"😔 Unfortunately, {time} on {date} is fully booked for {party_size} guests.\n\n"
            f"Available slots on {date}:\n"
            + "\n".join(f"• {slot}" for slot in alternatives)
            + "\n\nWould you like to book one of these times instead?"
        )


@function_tool
def make_reservation(
    context: RestaurantContext,
    date: str,
    time: str,
    party_size: int,
    guest_name: str,
    phone_number: str,
) -> str:
    """
    Book a table for the guest. All five details must be collected before calling this.

    Args:
        date: Reservation date (e.g., 'March 15' or '2026-03-15')
        time: Reservation time (e.g., '7:00 PM')
        party_size: Number of guests
        guest_name: Name for the reservation
        phone_number: Contact number in case of changes
    """
    confirmation_id = f"RES-{random.randint(10000, 99999)}"

    # Persist the confirmation ID in context so it survives cross-agent handoffs
    context.reservation_confirmation_id = confirmation_id

    return (
        f"🎉 Reservation Confirmed!\n\n"
        f"📋 Confirmation ID: {confirmation_id}\n"
        f"👤 Name: {guest_name}\n"
        f"📞 Phone: {phone_number}\n"
        f"📅 Date: {date}\n"
        f"⏰ Time: {time}\n"
        f"👥 Party size: {party_size}\n\n"
        "📧 A confirmation has been noted.\n"
        "Please arrive 5–10 minutes early. We look forward to seeing you!"
    )


@function_tool
def cancel_reservation(context: RestaurantContext, reservation_id: str) -> str:
    """
    Cancel an existing reservation.

    Args:
        reservation_id: The reservation confirmation ID to cancel (e.g., RES-12345)
    """
    return (
        f"✅ Reservation Cancelled\n\n"
        f"📋 Reservation ID: {reservation_id}\n"
        f"👤 Customer: {context.customer_name}\n\n"
        "Your reservation has been successfully cancelled.\n"
        "We hope to see you again soon! Feel free to make a new reservation anytime."
    )


# =============================================================================
# COMPLAINTS AGENT TOOLS
# =============================================================================


@function_tool
def offer_discount(context: RestaurantContext, percentage: int) -> str:
    """
    Offer the guest a discount voucher as an apology or goodwill gesture.

    Args:
        percentage: Discount percentage to offer (e.g., 10, 20, 50)
    """
    voucher_code = f"SORRY{random.randint(1000, 9999)}"
    return (
        f"🎁 Discount Voucher Created!\n\n"
        f"👤 Customer: {context.customer_name}\n"
        f"🏷️ Voucher Code: {voucher_code}\n"
        f"💰 Discount: {percentage}% off your next visit\n\n"
        "Valid for 30 days. Present this code to your server or use it online.\n"
        "We hope to welcome you back and make it up to you!"
    )


@function_tool
def schedule_manager_callback(
    context: RestaurantContext, phone_number: str, preferred_time: str
) -> str:
    """
    Arrange for our manager to call the guest back at a time that works for them.

    Args:
        phone_number: Guest's phone number for the callback
        preferred_time: When the guest would like the call (e.g., 'today at 3 PM')
    """
    ticket_id = f"MGR-{random.randint(10000, 99999)}"
    return (
        f"📞 Manager Callback Scheduled\n\n"
        f"👤 Customer: {context.customer_name}\n"
        f"📋 Ticket ID: {ticket_id}\n"
        f"📱 Phone: {phone_number}\n"
        f"⏰ Callback Time: {preferred_time}\n\n"
        "A member of our management team will contact you at the specified time.\n"
        "We take your experience very seriously and appreciate you giving us the opportunity to make it right."
    )


@function_tool
def process_refund(context: RestaurantContext, reason: str) -> str:
    """
    Process a refund for the guest's order. Use when the guest has had a bad experience.

    Args:
        reason: Brief reason for the refund (e.g., 'unsatisfactory food quality')
    """
    refund_id = f"REF-{random.randint(10000, 99999)}"
    return (
        f"💳 Refund Initiated\n\n"
        f"👤 Customer: {context.customer_name}\n"
        f"📋 Refund ID: {refund_id}\n"
        f"📝 Reason: {reason}\n\n"
        "Your refund has been submitted and will be processed within 3–5 business days.\n"
        "You will receive a confirmation email shortly.\n"
        "We sincerely apologize for the inconvenience and hope you'll give us another chance."
    )


# =============================================================================
# AGENT HOOKS
# =============================================================================


class AgentToolUsageLoggingHooks(AgentHooks):

    async def on_tool_start(
        self,
        context: RunContextWrapper[RestaurantContext],
        agent: Agent[RestaurantContext],
        tool: Tool,
    ):
        with st.sidebar:
            st.write(f"🔧 **{agent.name}** starting tool: `{tool.name}`")

    async def on_tool_end(
        self,
        context: RunContextWrapper[RestaurantContext],
        agent: Agent[RestaurantContext],
        tool: Tool,
        result: str,
    ):
        with st.sidebar:
            st.write(f"🔧 **{agent.name}** used tool: `{tool.name}`")
            st.code(result)

    async def on_handoff(
        self,
        context: RunContextWrapper[RestaurantContext],
        agent: Agent[RestaurantContext],
        source: Agent[RestaurantContext],
    ):
        with st.sidebar:
            st.write(f"🔄 Handoff: **{source.name}** → **{agent.name}**")

    async def on_start(
        self,
        context: RunContextWrapper[RestaurantContext],
        agent: Agent[RestaurantContext],
    ):
        with st.sidebar:
            st.write(f"🚀 **{agent.name}** activated")

    async def on_end(
        self,
        context: RunContextWrapper[RestaurantContext],
        agent: Agent[RestaurantContext],
        output,
    ):
        with st.sidebar:
            st.write(f"🏁 **{agent.name}** completed")
