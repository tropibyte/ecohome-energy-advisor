"""Offline tests for the LangGraph agent, driven by a scripted chat model."""
from datetime import date, timedelta

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agent import Agent
from conftest import tool_call

PROMPT = "You are the EcoHome Energy Advisor."


def test_contract_constructor_and_invoke(scripted):
    llm = scripted("Charge after 22:00.")
    agent = Agent(instructions=PROMPT, model="gpt-4o-mini", llm=llm)
    response = agent.invoke(question="When should I charge?", context="Location: San Francisco, CA")
    assert response["messages"][-1].content == "Charge after 22:00."
    assert response["final_answer"] == "Charge after 22:00."
    assert "get_weather_forecast" in agent.get_agent_tools() and len(agent.get_agent_tools()) == 12


def test_empty_instructions_rejected():
    with pytest.raises(ValueError):
        Agent(instructions="  ")


def test_runtime_context_injected(scripted):
    llm = scripted("ok")
    Agent(instructions=PROMPT, llm=llm).invoke("hi", context="Location: Austin, TX")
    system = llm.received[0][0]
    assert isinstance(system, SystemMessage)
    assert PROMPT in system.content
    assert "Location: Austin, TX" in system.content
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert f"(tomorrow): {tomorrow}" in system.content
    assert "Household profile" in system.content and "solar_system_kw" in system.content


def test_tool_loop_executes_and_logs(scripted):
    llm = scripted(
        AIMessage(content="", tool_calls=[tool_call("get_electricity_prices", {"date": "tomorrow"}, "c1"),
                                          tool_call("get_weather_forecast", {"location": "San Francisco, CA",
                                                                             "days": 2}, "c2")]),
        "Charge from 23:00 to 03:00.",
    )
    r = Agent(instructions=PROMPT, llm=llm, verify_answers=False).invoke("When should I charge my EV tomorrow?")
    tool_msgs = [m for m in r["messages"] if isinstance(m, ToolMessage)]
    assert {m.name for m in tool_msgs} == {"get_electricity_prices", "get_weather_forecast"}
    # the notebook's tool-listing idiom must keep working
    assert [m.name for m in r["messages"] if m.model_dump().get("tool_call_id")] == [
        "get_electricity_prices", "get_weather_forecast"]
    assert [t["tool"] for t in r["tool_log"]] == ["get_electricity_prices", "get_weather_forecast"]
    assert all(t["status"] == "success" and t["latency_ms"] >= 0 for t in r["tool_log"])
    assert r["iterations"] == 2
    assert any(d["node"] == "tools" for d in r["decisions"])
    # second LLM call saw the tool results
    assert any(isinstance(m, ToolMessage) for m in llm.received[1])


def test_tool_errors_are_returned_to_the_model(scripted):
    llm = scripted(
        AIMessage(content="", tool_calls=[tool_call("get_electricity_prices", {"date": "not-a-date"}, "c1"),
                                          tool_call("no_such_tool", {}, "c2"),
                                          tool_call("calculate_energy_savings", {"device_type": "EV"}, "c3")]),
        "Sorry, here is what I could find.",
    )
    r = Agent(instructions=PROMPT, llm=llm, verify_answers=False).invoke("prices?")
    assert [t["status"] for t in r["tool_log"]] == ["error", "error", "error"]
    assert len(r["errors"]) == 3
    assert r["final_answer"] == "Sorry, here is what I could find."


def test_iteration_budget_forces_an_answer(scripted):
    loop = [AIMessage(content="", tool_calls=[tool_call("get_electricity_prices", {}, f"c{i}")]) for i in range(3)]
    llm = scripted(*loop, "Best effort answer.")
    r = Agent(instructions=PROMPT, llm=llm, max_iterations=3).invoke("loop forever")
    assert r["final_answer"] == "Best effort answer."
    assert len(r["tool_log"]) == 2  # the third request was cut off by the budget
    assert any(d["node"] == "force_answer" for d in r["decisions"])
    # every tool call has a matching tool message (valid OpenAI transcript)
    ids = {c["id"] for m in r["messages"] if isinstance(m, AIMessage) for c in m.tool_calls}
    answered = {m.tool_call_id for m in r["messages"] if isinstance(m, ToolMessage)}
    assert ids <= answered


def test_transient_llm_errors_are_retried(scripted, monkeypatch):
    monkeypatch.setattr("agent.time.sleep", lambda s: None)
    llm = scripted("Recovered.", fail_times=2)
    r = Agent(instructions=PROMPT, llm=llm, max_retries=3).invoke("hello")
    assert r["final_answer"] == "Recovered."


def test_persistent_llm_failure_is_graceful(scripted, monkeypatch):
    monkeypatch.setattr("agent.time.sleep", lambda s: None)
    llm = scripted("never", fail_times=10)
    r = Agent(instructions=PROMPT, llm=llm, max_retries=2).invoke("hello")
    assert "couldn't reach the language model" in r["final_answer"]
    assert r["errors"]


def test_multi_turn_memory_with_thread_id(scripted):
    llm = scripted("First answer.", "Second answer.")
    agent = Agent(instructions=PROMPT, llm=llm)
    agent.invoke("My EV leaves at 7.", thread_id="t1")
    r = agent.invoke("And the dishwasher?", thread_id="t1")
    assert r["final_answer"] == "Second answer."
    humans = [m.content for m in llm.received[1] if m.type == "human"]
    assert humans == ["My EV leaves at 7.", "And the dishwasher?"]
    assert r["tool_log"] == []  # per-question log resets each turn


def test_graph_nodes_and_edges(scripted):
    agent = Agent(instructions=PROMPT, llm=scripted())
    g = agent.graph.get_graph()
    assert {"prepare_context", "agent", "tools", "verify", "force_answer", "finalize"} <= set(g.nodes)
    mermaid = agent.get_graph_mermaid()
    assert "prepare_context" in mermaid and "force_answer" in mermaid


# ---------------------------------------------------------------- quality gate
def _prices_call(i="p1"):
    return AIMessage(content="", tool_calls=[tool_call("get_electricity_prices", {"date": "tomorrow"}, i)])


def _tips_call(i="t1"):
    return AIMessage(content="", tool_calls=[tool_call("search_energy_tips", {"query": "EV charging off-peak"}, i)])


def test_verify_requests_knowledge_base_when_skipped(scripted):
    llm = scripted(_prices_call(), "Charge at 23:00. (source: EcoHome best practices)",
                   _tips_call(), "Charge at 23:00. (source: tip_ev_charging_strategies.txt)")
    r = Agent(instructions=PROMPT, llm=llm).invoke("When should I charge?")
    assert r["final_answer"].endswith("(source: tip_ev_charging_strategies.txt)")
    assert r["revisions"] == 1 and r["verification"]["passed"]
    critique = [m for m in r["messages"] if m.type == "human" and "quality check" in m.content]
    assert len(critique) == 1 and "search_energy_tips" in critique[0].content
    assert [t["tool"] for t in r["tool_log"]] == ["get_electricity_prices", "search_energy_tips"]


def test_verify_rejects_invented_citations(scripted):
    llm = scripted(_tips_call(), "Run it at night (source: tip_001.txt).",
                   "Run it at night (source: tip_ev_charging_strategies.txt).")
    r = Agent(instructions=PROMPT, llm=llm).invoke("When should I charge?")
    critique = next(m for m in r["messages"] if m.type == "human" and "quality check" in m.content)
    assert "tip_001.txt" in critique.content
    assert r["verification"]["passed"]


def test_verify_passes_grounded_answer_without_revision(scripted):
    llm = scripted(_tips_call(), "Charge overnight (source: tip_ev_charging_strategies.txt).")
    r = Agent(instructions=PROMPT, llm=llm).invoke("When should I charge?")
    assert r["revisions"] == 0 and r["verification"] == {"passed": True, "issues": [], "revision": 0}


def test_verify_allows_out_of_scope_answers_without_tools(scripted):
    r = Agent(instructions=PROMPT, llm=scripted("I'm EcoHome's energy advisor, so I can't recommend pizza.")) \
        .invoke("Best pizza in SF?")
    assert r["verification"]["passed"] and r["tool_log"] == []


def test_verify_revises_at_most_once(scripted):
    llm = scripted(_prices_call(), "Draft without tips.", "Still without tips.")
    r = Agent(instructions=PROMPT, llm=llm).invoke("When should I charge?")
    assert r["final_answer"] == "Still without tips."
    assert r["revisions"] == 1 and not r["verification"]["passed"]


def test_numpy_tool_output_survives_the_checkpointer(scripted):
    """Regression: predict_energy_usage returned numpy.float64, which crashed the graph's checkpointer."""
    llm = scripted(AIMessage(content="", tool_calls=[tool_call("predict_energy_usage", {"target_date": "tomorrow"}, "m1")]),
                   "Tomorrow: about 35 kWh.")
    r = Agent(instructions=PROMPT, llm=llm, verify_answers=False).invoke("How much will we use tomorrow?")
    assert r["final_answer"] == "Tomorrow: about 35 kWh."
    assert r["tool_log"][0]["status"] == "success"
    assert type(r["tool_log"][0]["output"]["predicted_total_kwh"]) is float
