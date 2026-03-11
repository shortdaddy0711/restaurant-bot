import dotenv

dotenv.load_dotenv()

import asyncio
import streamlit as st
from agents import Runner, SQLiteSession, InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered
from models import RestaurantContext
from my_agents.triage_agent import triage_agent, input_guardrail_agent

restaurant_ctx = RestaurantContext(
    customer_name="Guest",
)

if "session" not in st.session_state:
    st.session_state["session"] = SQLiteSession(
        "chat-history",
        "restaurant-memory.db",
    )
session = st.session_state["session"]

if "agent" not in st.session_state:
    st.session_state["agent"] = triage_agent


async def paint_history():
    messages = await session.get_items()
    for message in messages:
        if "role" in message:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.write(message["content"])
                else:
                    if message.get("type") == "message":
                        content = message.get("content", [])
                        if isinstance(content, list) and content:
                            text = content[0].get("text", "") if isinstance(content[0], dict) else ""
                        elif isinstance(content, str):
                            text = content
                        else:
                            text = ""
                        if text:
                            st.write(text.replace("$", "\\$"))


asyncio.run(paint_history())


async def run_agent(message):
    with st.chat_message("ai"):
        text_placeholder = st.empty()
        response = ""

        st.session_state["text_placeholder"] = text_placeholder

        # Pre-flight input guardrail check — runs synchronously BEFORE the stream
        # starts so the triage agent never emits tokens for a blocked message.
        # Only applied when the active agent carries input guardrails (triage agent).
        active_agent = st.session_state["agent"]
        if active_agent.input_guardrails:
            guardrail_result = await Runner.run(
                input_guardrail_agent,
                message,
                context=restaurant_ctx,
            )
            if guardrail_result.final_output.is_off_topic:
                text_placeholder.write(
                    "I'm sorry, I can only assist with restaurant-related inquiries. "
                    "I can help you view the menu, make a reservation, or place an order. 🍽️"
                )
                return

        try:
            stream = Runner.run_streamed(
                st.session_state["agent"],
                message,
                session=session,
                context=restaurant_ctx,
            )

            async for event in stream.stream_events():
                if event.type == "raw_response_event":
                    if event.data.type == "response.output_text.delta":
                        response += event.data.delta
                        text_placeholder.write(response.replace("$", "\\$"))

                elif event.type == "agent_updated_stream_event":
                    if st.session_state["agent"].name != event.new_agent.name:
                        st.write(
                            f"🍽️ Connecting you to our {event.new_agent.name}..."
                        )

                        st.session_state["agent"] = event.new_agent

                        text_placeholder = st.empty()
                        st.session_state["text_placeholder"] = text_placeholder
                        response = ""

        except InputGuardrailTripwireTriggered:
            # Safety net — should not be reached due to pre-flight check above,
            # but kept in case the guardrail fires during streaming for edge cases.
            text_placeholder.write(
                "I'm sorry, I can only assist with restaurant-related inquiries. "
                "I can help you view the menu, make a reservation, or place an order. 🍽️"
            )

        except OutputGuardrailTripwireTriggered:
            text_placeholder.write(
                "⚠️ I wasn't able to generate an appropriate response. Please try rephrasing your question, "
                "and I'll do my best to help!"
            )


message = st.chat_input("Ask about our menu, place an order, or make a reservation!")

if message:
    with st.chat_message("human"):
        st.write(message)
    asyncio.run(run_agent(message))


with st.sidebar:
    st.title("🍽️ Restaurant Bot")
    reset = st.button("Reset memory")
    if reset:
        asyncio.run(session.clear_session())
        st.session_state["agent"] = triage_agent
    st.write(asyncio.run(session.get_items()))
