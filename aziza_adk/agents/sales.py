"""The agent, and the one place the tree is built.

ONE agent, because there is nothing to route between: every turn is about one specialist's
current sale. It is still built through `agent_adk.build_graph` rather than by hand, because the
input screen is that factory's argument — an agent that can own a turn is screened, and a tree of
one is no exception. A coordinator arrives when a second concern does.

`tests/test_agents.py` asserts the attachment by discovering the agents from the built graph.
"""

from __future__ import annotations

from agent_adk import AgentSpec, build_graph

from aziza_adk import config, guards, tools
from aziza_adk.prompts.common import GENERATE_CONFIG, SALES_BASE, make_instruction

SALES_SPEC = AgentSpec(
    name="sales_agent",
    model=config.AGENT_MODEL,
    description="Records what a specialist did for a client, prices it, charges it and closes it.",
    instruction=make_instruction(SALES_BASE, with_catalog=True),
    tools=(
        tools.start_ticket,
        tools.add_service,
        tools.set_client_gender,
        tools.sell_product,
        tools.show_ticket,
        tools.void_ticket,
        tools.record_payment,
        tools.close_ticket_with_debt,
        tools.settle_client_debt,
        tools.buy_product,
        tools.settle_debt,
        tools.record_loan,
        tools.close_register,
        tools.salon_day,
        tools.my_day,
    ),
    before_tool=guards.before_tool_guard,
    after_tool=guards.log_after_tool,
    before_agent=guards.log_before_agent,
)

sales_agent = build_graph(
    SALES_SPEC,
    input_screen=guards.before_model_safety,
    generate_content_config=GENERATE_CONFIG,
)
