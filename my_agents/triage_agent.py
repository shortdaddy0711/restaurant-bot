import streamlit as st
from agents import (
    Agent,
    RunContextWrapper,
    input_guardrail,
    Runner,
    GuardrailFunctionOutput,
    handoff,
)
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from agents.extensions import handoff_filters
from models import RestaurantContext, InputGuardRailOutput, HandoffData
from my_agents.menu_agent import menu_agent
from my_agents.order_agent import order_agent
from my_agents.reservation_agent import reservation_agent


input_guardrail_agent = Agent(
    name="Input Guardrail Agent",
    instructions="""
    Ensure the user's request is related to restaurant topics: menu items, food ingredients, allergens,
    placing orders, table reservations, or general restaurant inquiries. If the request is off-topic
    (e.g., weather, politics, coding help, unrelated services), return is_off_topic=True with a reason.
    You can make small friendly conversation at the start, but only assist with restaurant-related topics.
""",
    output_type=InputGuardRailOutput,
)


@input_guardrail
async def off_topic_guardrail(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent[RestaurantContext],
    input: str,
):
    result = await Runner.run(
        input_guardrail_agent,
        input,
        context=wrapper.context,
    )

    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=result.final_output.is_off_topic,
    )


def dynamic_triage_agent_instructions(
    wrapper: RunContextWrapper[RestaurantContext],
    agent: Agent[RestaurantContext],
):
    return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    You are a friendly restaurant assistant. You ONLY help with restaurant-related topics:
    menu questions, placing orders, and table reservations.

    Always address the customer by their name: {wrapper.context.customer_name}.

    YOUR MAIN JOB: Understand the customer's need and route them to the right specialist.

    ROUTING GUIDE:

    🍽️ MENU SPECIALIST — Route here for:
    - Questions about menu items, dishes, categories
    - Ingredient or recipe inquiries
    - Allergen and dietary restriction questions (vegetarian, vegan, gluten-free)
    - Daily specials and chef's recommendations
    - "What do you have for dessert?", "Is there anything vegetarian?", "Does the pasta have nuts?"

    📋 ORDER SPECIALIST — Route here for:
    - Placing a new food order
    - Adding items to an existing order
    - Reviewing or confirming an order
    - "I'd like to order...", "Can I get the steak?", "What's in my order so far?"

    📅 RESERVATION SPECIALIST — Route here for:
    - Booking a table
    - Checking availability for a date/time
    - Cancelling an existing reservation
    - "I want to make a reservation", "Do you have a table for 4 tonight?", "Cancel my booking"

    ROUTING PROCESS:
    1. Greet the customer warmly by name
    2. Understand their request
    3. Ask a quick clarifying question if the category isn't clear
    4. Announce the transfer: "I'll connect you with our [specialist] right away!"
    5. Route to the appropriate specialist

    Keep your responses brief — your job is to route, not to answer directly.
    """


def handle_handoff(
    wrapper: RunContextWrapper[RestaurantContext],
    input_data: HandoffData,
):
    with st.sidebar:
        st.write(
            f"""
            Handing off to {input_data.to_agent_name}
            Reason: {input_data.reason}
            Request Type: {input_data.request_type}
            Description: {input_data.request_description}
        """
        )


def make_handoff(agent):
    return handoff(
        agent=agent,
        on_handoff=handle_handoff,
        input_type=HandoffData,
        input_filter=handoff_filters.remove_all_tools,
    )


triage_agent = Agent(
    name="Restaurant Assistant",
    instructions=dynamic_triage_agent_instructions,
    input_guardrails=[
        off_topic_guardrail,
    ],
    handoffs=[
        make_handoff(menu_agent),
        make_handoff(order_agent),
        make_handoff(reservation_agent),
    ],
)

# Enable cross-agent handoffs so each specialist can route to another
# when the customer switches topics (e.g., reservation → menu question).
# This is done here to avoid circular imports between specialist modules.
menu_agent.handoffs = [make_handoff(order_agent), make_handoff(reservation_agent)]
order_agent.handoffs = [make_handoff(menu_agent), make_handoff(reservation_agent)]
reservation_agent.handoffs = [make_handoff(menu_agent), make_handoff(order_agent)]
