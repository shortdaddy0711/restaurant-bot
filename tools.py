import streamlit as st
import random
from agents import function_tool, AgentHooks, Agent, Tool, RunContextWrapper
from models import RestaurantContext


# =============================================================================
# MENU AGENT TOOLS
# =============================================================================


@function_tool
def lookup_menu_items(context: RestaurantContext, category: str) -> str:
    """
    Look up menu items by category.

    Args:
        category: Menu category (e.g., appetizers, mains, desserts, drinks, vegetarian)
    """
    menus = {
        "appetizers": [
            "🥗 Caesar Salad - $12.00 (Romaine lettuce, parmesan, croutons)",
            "🍲 French Onion Soup - $10.00 (Gruyère cheese, toasted baguette)",
            "🦐 Shrimp Cocktail - $16.00 (Chilled shrimp, cocktail sauce)",
            "🧅 Onion Rings - $8.00 (Beer-battered, ranch dipping sauce)",
        ],
        "mains": [
            "🥩 Ribeye Steak - $42.00 (12oz, served with seasonal vegetables)",
            "🍗 Grilled Chicken - $24.00 (Herb-marinated, mashed potatoes)",
            "🐟 Pan-Seared Salmon - $32.00 (Lemon butter sauce, asparagus)",
            "🍝 Mushroom Pasta - $18.00 (Porcini, truffle oil, parmesan)",
        ],
        "desserts": [
            "🍰 New York Cheesecake - $9.00 (Berry compote)",
            "🍫 Chocolate Lava Cake - $10.00 (Vanilla ice cream)",
            "🍨 Crème Brûlée - $9.00 (Classic French custard)",
            "🥧 Apple Tart - $8.00 (Caramel sauce, whipped cream)",
        ],
        "drinks": [
            "🍷 House Red Wine - $10.00/glass",
            "🍸 Classic Mojito - $12.00",
            "🧃 Fresh Lemonade - $5.00",
            "☕ Espresso - $4.00",
        ],
        "vegetarian": [
            "🥗 Caesar Salad - $12.00 (can be made vegan on request)",
            "🍝 Mushroom Pasta - $18.00 (Porcini, truffle oil, parmesan)",
            "🥕 Veggie Burger - $16.00 (Beyond Meat patty, avocado, sprouts)",
            "🫕 Lentil Stew - $15.00 (Moroccan spiced, served with pita)",
        ],
    }

    key = category.lower()
    items = menus.get(key, menus.get("mains"))
    label = key if key in menus else "mains"

    return f"🍽️ {label.title()} Menu:\n" + "\n".join(items)


@function_tool
def check_allergens(context: RestaurantContext, dish_name: str) -> str:
    """
    Check allergen information for a specific dish.

    Args:
        dish_name: Name of the dish to check
    """
    allergen_db = {
        "caesar salad": ["gluten (croutons)", "dairy (parmesan)", "eggs (dressing)", "fish (anchovies)"],
        "french onion soup": ["gluten (baguette)", "dairy (gruyère)"],
        "shrimp cocktail": ["shellfish"],
        "ribeye steak": [],
        "grilled chicken": [],
        "pan-seared salmon": ["fish"],
        "mushroom pasta": ["gluten (pasta)", "dairy (parmesan)"],
        "new york cheesecake": ["dairy", "gluten", "eggs"],
        "chocolate lava cake": ["dairy", "gluten", "eggs"],
        "veggie burger": ["gluten (bun)", "soy (patty)"],
    }

    key = dish_name.lower()
    for dish, allergens in allergen_db.items():
        if dish in key or key in dish:
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
    specials = [
        "🌟 **Chef's Special**: Lobster Bisque - $22.00 (Fresh Maine lobster, cream, sherry)",
        "🌟 **Today's Fish**: Grilled Sea Bass - $36.00 (Mediterranean herbs, capers, olives)",
        "🌟 **Pasta of the Day**: Truffle Tagliatelle - $24.00 (Black truffle shavings, butter sauce)",
        "🌟 **Dessert Special**: Tiramisu - $11.00 (House-made, espresso-soaked ladyfingers)",
    ]

    discount = random.choice(["15%", "10%", "20%"])
    return (
        "🎉 Today's Daily Specials:\n\n"
        + "\n".join(specials)
        + f"\n\n🏷️ Happy Hour (5–7PM): {discount} off all drinks!"
    )


# =============================================================================
# ORDER AGENT TOOLS
# =============================================================================


@function_tool
def add_to_order(context: RestaurantContext, item_name: str, quantity: int = 1) -> str:
    """
    Add an item to the current order.

    Args:
        item_name: Name of the menu item to add
        quantity: Number of units to add (default: 1)
    """
    item_prices = {
        "caesar salad": 12.00,
        "french onion soup": 10.00,
        "shrimp cocktail": 16.00,
        "ribeye steak": 42.00,
        "grilled chicken": 24.00,
        "pan-seared salmon": 32.00,
        "mushroom pasta": 18.00,
        "new york cheesecake": 9.00,
        "chocolate lava cake": 10.00,
        "veggie burger": 16.00,
        "lentil stew": 15.00,
        "truffle tagliatelle": 24.00,
        "lobster bisque": 22.00,
    }

    key = item_name.lower()
    price = item_prices.get(key, 20.00)
    subtotal = price * quantity

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
    mock_items = [
        ("Ribeye Steak", 1, 42.00),
        ("Caesar Salad", 2, 12.00),
        ("House Red Wine", 2, 10.00),
    ]

    lines = [f"• {qty}x {name} — ${qty * price:.2f}" for name, qty, price in mock_items]
    subtotal = sum(qty * price for _, qty, price in mock_items)
    tax = subtotal * 0.1
    total = subtotal + tax

    return (
        f"📋 Current Order Summary for {context.customer_name}:\n\n"
        + "\n".join(lines)
        + f"\n\n💰 Subtotal: ${subtotal:.2f}"
        + f"\n🧾 Tax (10%): ${tax:.2f}"
        + f"\n✅ Total: ${total:.2f}"
    )


@function_tool
def confirm_order(context: RestaurantContext) -> str:
    """
    Finalize and confirm the current order. This sends the order to the kitchen.
    """
    order_id = f"ORD-{random.randint(1000, 9999)}"
    estimated_time = random.randint(20, 35)

    return (
        f"🎉 Order Confirmed!\n\n"
        f"📋 Order ID: {order_id}\n"
        f"👤 Customer: {context.customer_name}\n"
        f"⏱️ Estimated preparation time: {estimated_time} minutes\n"
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
    is_available = random.choice([True, True, True, False])

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
    Create a table reservation.

    Args:
        date: Reservation date (e.g., 'March 15' or '2026-03-15')
        time: Reservation time (e.g., '7:00 PM')
        party_size: Number of guests
        guest_name: Full name of the person making the reservation
        phone_number: Contact phone number for the reservation
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
