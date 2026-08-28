"""The graph, discovered from the BUILT object rather than from the specs it was built from.

A tree of one agent is where an attachment test is easiest to write as a tautology, so this file
reads what `build_graph` actually produced.

MUTATION CHECK, to be re-run whenever this is touched: pass `input_screen=lambda *a: None` in
`aziza_adk/agents/sales.py`, or strip the callback off the built agent by hand, and the first
test below MUST go red. If it stays green it is asserting nothing.
"""

import pytest
from agent_adk import every_agent, input_screens, turn_owning_agents

from aziza_adk import guards, tools
from aziza_adk.agent import root_agent


def test_every_agent_that_can_own_a_turn_is_screened():
    """ADK resumes the LAST ACTING AGENT on the next user turn, so an unscreened leaf owns every
    turn after a transfer — which is why the screen is the factory's argument and not a field."""
    owners = turn_owning_agents(root_agent)
    assert owners, "no agent can own a turn — the graph is not built"
    for agent in owners:
        assert guards.before_model_safety in input_screens(agent), agent.name


def test_the_tree_is_one_agent_and_that_is_deliberate():
    """There is nothing to route between: every turn is about one specialist's current sale. A
    coordinator arrives when a second concern does, not before."""
    assert [a.name for a in every_agent(root_agent)] == ["sales_agent"]


def test_the_root_is_the_name_adk_resolves():
    assert root_agent.name == "sales_agent"


def test_the_tool_guard_is_attached():
    """It is what refuses a session with no specialist behind it, which is the money-critical
    check in this service."""
    assert root_agent.before_tool_callback is not None


def test_generation_is_deterministic():
    assert root_agent.generate_content_config.temperature == 0.0


def test_a_model_call_has_a_deadline():
    """The Gemini SSE stream has none of its own, so a server that stops emitting parks the turn
    forever — and `adk web` and the eval never reach the channel's whole-turn cap."""
    assert root_agent.generate_content_config.http_options.timeout > 0


@pytest.mark.parametrize("name", sorted(tools.SPECIALIST_TOOL_NAMES))
def test_every_tool_the_guard_knows_about_is_actually_on_the_agent(name):
    """A guard naming a tool the agent does not have protects nothing, and the two lists drift
    silently — one is edited and the other is not."""
    assert name in {getattr(t, "__name__", "") for t in root_agent.tools}


def test_the_agent_has_no_tool_the_guard_does_not_know_about():
    """The other direction, which is the one that leaves a tool unauthorized."""
    on_agent = {getattr(t, "__name__", "") for t in root_agent.tools}
    assert on_agent == set(tools.SPECIALIST_TOOL_NAMES)
