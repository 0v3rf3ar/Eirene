"""Configured model costs and context limits."""

from __future__ import annotations

from eirene.core.agent import Agent
from eirene.core.config import Config
from eirene.core.session import Message, Session
from eirene.core.usage import Usage
from eirene.tools.sandbox import Sandbox


def test_configured_cost_estimate():
    usage = Usage()
    usage.record(1_000_000, 500_000, 1, "model-a")
    assert usage.estimated_cost({"model-a": {
        "input_per_million": 2, "output_per_million": 8}}) == 6.0


def test_cost_is_unknown_when_a_model_has_no_price():
    usage = Usage()
    usage.record(10, 10, 1, "unknown")
    assert usage.estimated_cost({}) is None


def test_empty_usage_costs_zero():
    assert Usage().estimated_cost({}) == 0.0


def test_model_context_limit_sets_an_eighty_percent_warning(workdir):
    config = Config.load()
    config.set("model_context_limits", {"small": 1000})
    session = Session.create(workdir)
    session.messages = [Message.user("x" * 4000)]
    agent = Agent(session, config, Sandbox(workdir))
    agent.model = "small"
    assert agent.context_is_heavy()


def test_bad_context_limit_falls_back_to_default(workdir):
    config = Config.load()
    config.set("model_context_limits", {"small": "bad"})
    session = Session.create(workdir)
    agent = Agent(session, config, Sandbox(workdir))
    agent.model = "small"
    assert not agent.context_is_heavy()
