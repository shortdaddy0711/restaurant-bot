# menu_data.py
"""
Single Source of Truth for all menu items, prices, allergens, and daily specials.

Every module that needs menu information (display, ordering, allergen checks)
MUST import from here — never hard-code menu data elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MenuItem:
    """An immutable menu item definition."""

    name: str
    price: float
    emoji: str
    description: str
    allergens: list[str]
    is_vegetarian: bool = False
    is_vegan: bool = False


# ---------------------------------------------------------------------------
# Menu Catalogue  (grouped by category)
# ---------------------------------------------------------------------------

MENU: dict[str, list[MenuItem]] = {
    "appetizers": [
        MenuItem(
            name="Caesar Salad",
            price=12.00,
            emoji="🥗",
            description="Romaine lettuce, parmesan, croutons",
            allergens=["gluten (croutons)", "dairy (parmesan)", "eggs (dressing)", "fish (anchovies)"],
            is_vegetarian=True,
        ),
        MenuItem(
            name="French Onion Soup",
            price=10.00,
            emoji="🍲",
            description="Gruyère cheese, toasted baguette",
            allergens=["gluten (baguette)", "dairy (gruyère)"],
            is_vegetarian=True,
        ),
        MenuItem(
            name="Shrimp Cocktail",
            price=16.00,
            emoji="🦐",
            description="Chilled shrimp, cocktail sauce",
            allergens=["shellfish"],
        ),
        MenuItem(
            name="Onion Rings",
            price=8.00,
            emoji="🧅",
            description="Beer-battered, ranch dipping sauce",
            allergens=["gluten (batter)", "dairy (ranch)"],
            is_vegetarian=True,
        ),
        MenuItem(
            name="Thai Peanut Noodles",
            price=14.00,
            emoji="🥜",
            description="Rice noodles, crushed peanuts, lime",
            allergens=["peanuts", "soy"],
            is_vegetarian=True,
            is_vegan=True,
        ),
    ],
    "mains": [
        MenuItem(
            name="Ribeye Steak",
            price=42.00,
            emoji="🥩",
            description="12oz, served with seasonal vegetables",
            allergens=[],
        ),
        MenuItem(
            name="Grilled Chicken",
            price=24.00,
            emoji="🍗",
            description="Herb-marinated, mashed potatoes",
            allergens=[],
        ),
        MenuItem(
            name="Pan-Seared Salmon",
            price=32.00,
            emoji="🐟",
            description="Lemon butter sauce, asparagus",
            allergens=["fish"],
        ),
        MenuItem(
            name="Mushroom Pasta",
            price=18.00,
            emoji="🍝",
            description="Porcini, truffle oil, parmesan",
            allergens=["gluten (pasta)", "dairy (parmesan)"],
            is_vegetarian=True,
        ),
    ],
    "desserts": [
        MenuItem(
            name="New York Cheesecake",
            price=9.00,
            emoji="🍰",
            description="Berry compote",
            allergens=["dairy", "gluten", "eggs"],
        ),
        MenuItem(
            name="Chocolate Lava Cake",
            price=10.00,
            emoji="🍫",
            description="Vanilla ice cream",
            allergens=["dairy", "gluten", "eggs"],
        ),
        MenuItem(
            name="Crème Brûlée",
            price=9.00,
            emoji="🍨",
            description="Classic French custard",
            allergens=["dairy", "eggs"],
        ),
        MenuItem(
            name="Apple Tart",
            price=8.00,
            emoji="🥧",
            description="Caramel sauce, whipped cream",
            allergens=["gluten", "dairy"],
        ),
    ],
    "drinks": [
        MenuItem(
            name="House Red Wine",
            price=10.00,
            emoji="🍷",
            description="glass",
            allergens=["sulfites"],
        ),
        MenuItem(
            name="Classic Mojito",
            price=12.00,
            emoji="🍸",
            description="",
            allergens=[],
        ),
        MenuItem(
            name="Fresh Lemonade",
            price=5.00,
            emoji="🧃",
            description="",
            allergens=[],
        ),
        MenuItem(
            name="Espresso",
            price=4.00,
            emoji="☕",
            description="",
            allergens=[],
        ),
    ],
    "vegetarian": [
        # References to items already defined above — kept as full objects
        # so the vegetarian view is self-contained.
        MenuItem(
            name="Caesar Salad",
            price=12.00,
            emoji="🥗",
            description="can be made vegan on request",
            allergens=["gluten (croutons)", "dairy (parmesan)", "eggs (dressing)", "fish (anchovies)"],
            is_vegetarian=True,
        ),
        MenuItem(
            name="Mushroom Pasta",
            price=18.00,
            emoji="🍝",
            description="Porcini, truffle oil, parmesan",
            allergens=["gluten (pasta)", "dairy (parmesan)"],
            is_vegetarian=True,
        ),
        MenuItem(
            name="Veggie Burger",
            price=16.00,
            emoji="🥕",
            description="Beyond Meat patty, avocado, sprouts",
            allergens=["gluten (bun)", "soy (patty)"],
            is_vegetarian=True,
            is_vegan=True,
        ),
        MenuItem(
            name="Lentil Stew",
            price=15.00,
            emoji="🫕",
            description="Moroccan spiced, served with pita",
            allergens=["gluten (pita)"],
            is_vegetarian=True,
            is_vegan=True,
        ),
    ],
}

# ---------------------------------------------------------------------------
# Daily Specials
# ---------------------------------------------------------------------------

DAILY_SPECIALS: list[MenuItem] = [
    MenuItem(
        name="Lobster Bisque",
        price=22.00,
        emoji="🌟",
        description="Fresh Maine lobster, cream, sherry",
        allergens=["shellfish", "dairy"],
    ),
    MenuItem(
        name="Grilled Sea Bass",
        price=36.00,
        emoji="🌟",
        description="Mediterranean herbs, capers, olives",
        allergens=["fish"],
    ),
    MenuItem(
        name="Truffle Tagliatelle",
        price=24.00,
        emoji="🌟",
        description="Black truffle shavings, butter sauce",
        allergens=["gluten (pasta)", "dairy (butter)"],
        is_vegetarian=True,
    ),
    MenuItem(
        name="Tiramisu",
        price=11.00,
        emoji="🌟",
        description="House-made, espresso-soaked ladyfingers",
        allergens=["dairy", "gluten", "eggs"],
    ),
]


# ---------------------------------------------------------------------------
# Derived look-ups (built once at import time)
# ---------------------------------------------------------------------------

def _build_price_lookup() -> dict[str, float]:
    """Build a lowercase name → price lookup from all menu items + specials."""
    lookup: dict[str, float] = {}
    for items in MENU.values():
        for item in items:
            lookup[item.name.lower()] = item.price
    for item in DAILY_SPECIALS:
        lookup[item.name.lower()] = item.price
    # Common aliases (e.g. without accents)
    lookup["creme brulee"] = lookup.get("crème brûlée", 9.00)
    return lookup


def _build_allergen_lookup() -> dict[str, list[str]]:
    """Build a lowercase name → allergens lookup from all menu items + specials."""
    lookup: dict[str, list[str]] = {}
    for items in MENU.values():
        for item in items:
            lookup[item.name.lower()] = item.allergens
    for item in DAILY_SPECIALS:
        lookup[item.name.lower()] = item.allergens
    lookup["creme brulee"] = lookup.get("crème brûlée", [])
    return lookup


#: Lowercase item name → price  (covers all categories + specials)
PRICE_LOOKUP: dict[str, float] = _build_price_lookup()

#: Lowercase item name → allergen list  (covers all categories + specials)
ALLERGEN_LOOKUP: dict[str, list[str]] = _build_allergen_lookup()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def format_menu_item(item: MenuItem) -> str:
    """Format a single MenuItem for customer-facing display."""
    price_str = f"${item.price:.2f}"
    if item.description:
        return f"{item.emoji} {item.name} - {price_str} ({item.description})"
    return f"{item.emoji} {item.name} - {price_str}"


def format_daily_special(item: MenuItem) -> str:
    """Format a daily special for customer-facing display."""
    label_map = {
        "Lobster Bisque": "Chef's Special",
        "Grilled Sea Bass": "Today's Fish",
        "Truffle Tagliatelle": "Pasta of the Day",
        "Tiramisu": "Dessert Special",
    }
    label = label_map.get(item.name, "Special")
    return f"{item.emoji} **{label}**: {item.name} - ${item.price:.2f} ({item.description})"
