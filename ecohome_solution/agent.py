"""
EcoHome Energy Advisor - LangGraph agent.

Graph (explicit StateGraph rather than the prebuilt ReAct helper, so every
node and edge is visible, testable and logged):

    START -> prepare_context -> agent --(tool calls)--> tools -> agent ...
                                  |
                                  +--(no tool calls)-----------> verify --(passed)--> finalize -> END
                                  |                                 +--(issues, 1 revision max)--> agent
                                  +--(iteration budget spent)--> force_answer -> finalize

* prepare_context - builds the runtime context block: current date/time, a
  date table for resolving "tomorrow"/"Wednesday", the caller's context
  string (e.g. location) and the household profile from the database.
* agent           - the LLM with all tools bound; retried with back-off on
  transient API errors; a failure becomes a graceful message, not a crash.
* tools           - executes every tool call, converts exceptions and
  {"error": ...} results into ToolMessages the LLM can recover from, and
  logs name, arguments, status, latency and output size for transparency.
* verify          - deterministic quality gate on the draft answer: the knowledge
  base must have been searched when data tools were used, and every cited
  tip_*.txt file must be one the search actually returned.  Failures go
  back to the LLM with a specific critique (one revision), so the model
  cannot ship invented citations.
* force_answer    - if the tool budget is exhausted, asks for a final answer
  from the evidence gathered so far with tools unbound.
* finalize        - records the final answer and a decision summary.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, Sequence, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage)
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

import config
from energy_model import DEFAULT_HOUSEHOLD_PROFILE, next_days_table
import tools as tools_module
from tools import TOOL_KIT

MAX_TOOL_OUTPUT_CHARS = 24_000  # guardrail against a tool flooding the context window
# Keys seeded from the default profile; anything else in the preferences table was learned from the user.
DEFAULT_KEYS = set(DEFAULT_HOUSEHOLD_PROFILE)


# (question pattern, tool that must have run successfully, critique sent back if it did not).
# Added after review: savings answers were being released without calculate_energy_savings, and
# recent-performance questions were answered from raw usage queries instead of the summary tool.
REQUIRED_TOOL_RULES = [
    (re.compile(r"\b(save|saves|saving|savings|pay (?:off|back)|payback|roi|return on investment)\b", re.I),
     "calculate_energy_savings",
     "This is a savings question, so the figures must come from calculate_energy_savings. Call it with the real "
     "kWh and the effective rates from your tool results (price_per_kwh = current effective rate, "
     "optimized_price_per_kwh = new rate for load shifting; frequency_per_year; upfront_cost_usd if a cost was "
     "given) and state the saving per run/cycle and per year (and the payback period when relevant)."),
    (re.compile(r"\b(last|past)\s+(\d+\s+)?(hours?|day)\b|\btoday so far\b|\bright now\b|\brecent(ly)?\b"
                r"|\bhow (?:is|has|was) my (?:home|house)\b", re.I),
     "get_recent_energy_summary",
     "This asks how the home has been doing recently, so call get_recent_energy_summary (hours=24 unless the "
     "user gave a period) and report consumption, cost, solar generation and self-sufficiency from it."),
    (re.compile(r"(?=.*\b(solar|panels?)\b)(?=.*\b(yesterday|last (week|month)|past (week|month|\d+ days))\b)",
                re.I | re.S),
     "query_solar_generation",
     "This asks about past solar production, so call query_solar_generation for that date range and quote its "
     "totals (and best/worst day where useful)."),
    (re.compile(r"(?=.*\b(use|used|usage|consum\w*|cost)\b)(?=.*\b(yesterday|last (week|month)|past (week|month|\d+ days))\b)",
                re.I | re.S),
     "query_energy_usage",
     "This asks about energy use over a past period, so call query_energy_usage for that date range and quote its "
     "consumption and cost figures."),
]


def _to_builtin(obj: Any) -> Any:
    """json.dumps fallback: numpy/pandas scalars via .item(), everything else as a string."""
    if hasattr(obj, "item"):
        try:
            return obj.item()
        except Exception:
            pass
    return str(obj)


# ---------------------------------------------------------------------------
# Graph schema
# ---------------------------------------------------------------------------
class EnergyAdvisorState(TypedDict, total=False):
    """State carried through the graph for one conversation thread."""
    messages: Annotated[List[AnyMessage], add_messages]  # conversation (human / ai / tool)
    question: str                  # the current user question
    context: Optional[str]         # caller-supplied context, e.g. "Location: San Francisco, CA"
    runtime_context: str           # rendered context block injected into the system prompt
    iterations: int                # LLM calls made for the current question
    tool_log: List[Dict[str, Any]]  # every tool call for the current question (transparency)
    decisions: List[Dict[str, Any]]  # routing decisions taken by the graph
    errors: List[str]              # recoverable errors encountered
    revisions: int                 # quality-gate revisions requested for the current question
    verification: Dict[str, Any]   # outcome of the last quality check
    final_answer: Optional[str]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
class Agent:
    def __init__(self, instructions: str, model: str = config.CHAT_MODEL, temperature: float = 0.0,
                 tools: Optional[Sequence] = None, max_iterations: int = 10, llm: Optional[BaseChatModel] = None,
                 max_retries: int = 3, include_household_profile: bool = True, verify_answers: bool = True,
                 max_revisions: int = 2):
        """
        Args:
            instructions: system prompt describing the Energy Advisor's role and method
            model: OpenAI model name served through the Vocareum gateway (default gpt-4.1-mini: in side-by-side
                runs it followed the setpoint and citation rules that gpt-4o-mini skipped, at similar cost)
            temperature: sampling temperature (0 for reproducible advice)
            tools: tool list (defaults to the full EcoHome TOOL_KIT)
            max_iterations: maximum LLM calls per question before a forced final answer
            llm: optional pre-built chat model (used by the offline tests)
            max_retries: retries for transient LLM errors
            include_household_profile: inject the saved household profile into the context
            verify_answers: run the quality gate (knowledge-base use and citation checks) before finalising
            max_revisions: how many times the quality gate may send an answer back for revision (default 2)
        """
        if not instructions or not instructions.strip():
            raise ValueError("Agent instructions must not be empty - pass ECOHOME_SYSTEM_PROMPT.")
        self.instructions = instructions
        self.model_name = model
        self.tools = list(tools or TOOL_KIT)
        self.tools_by_name = {t.name: t for t in self.tools}
        self.max_iterations = max_iterations
        self.max_retries = max_retries
        self.include_household_profile = include_household_profile
        self.verify_answers = verify_answers
        self.max_revisions = max_revisions

        # Initialize the LLM
        self.llm = llm or ChatOpenAI(
            model=model,
            temperature=temperature,
            timeout=90,
            max_retries=2,
            **config.openai_client_kwargs(),
        )
        self.llm_with_tools = self.llm.bind_tools(self.tools)

        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()

    # ------------------------------------------------------------------ graph
    def _build_graph(self):
        builder = StateGraph(EnergyAdvisorState)
        builder.add_node("prepare_context", self._prepare_context)
        builder.add_node("agent", self._call_model)
        builder.add_node("tools", self._run_tools)
        builder.add_node("verify", self._verify)
        builder.add_node("force_answer", self._force_answer)
        builder.add_node("finalize", self._finalize)

        builder.add_edge(START, "prepare_context")
        builder.add_edge("prepare_context", "agent")
        builder.add_conditional_edges("agent", self._route_after_agent,
                                      {"tools": "tools", "force_answer": "force_answer", "verify": "verify"})
        builder.add_edge("tools", "agent")
        builder.add_conditional_edges("verify", self._route_after_verify, {"agent": "agent", "finalize": "finalize"})
        builder.add_edge("force_answer", "finalize")
        builder.add_edge("finalize", END)
        return builder.compile(checkpointer=self.checkpointer, name="energy_advisor")

    # ------------------------------------------------------------------ nodes
    def _prepare_context(self, state: EnergyAdvisorState) -> Dict[str, Any]:
        now = datetime.now()
        lines = [
            "## Runtime context",
            f"- Current local date/time: {now:%A %Y-%m-%d %H:%M}",
            "- Date lookup (use these exact dates in tool calls):",
        ]
        for row in next_days_table(now, 8):
            label = f" ({row['label']})" if row["label"] else ""
            lines.append(f"  - {row['weekday']}{label}: {row['date']}")
        rng = {}
        try:
            rng = tools_module.db_manager.get_data_range()
        except Exception:
            pass
        if rng.get("first"):
            lines.append(f"- Usage history available: {rng['first'][:10]} to {rng['last'][:16]}")
        if state.get("context"):
            lines.append(f"- Caller context: {state['context']}")
        if self.include_household_profile:
            try:
                prefs = tools_module.db_manager.get_preferences()
            except Exception:
                prefs = {}
            if prefs:
                keep = ["location", "solar_system_kw", "battery_capacity_kwh", "ev_model", "ev_charger_kw",
                        "ev_departure_time", "ev_daily_miles", "hvac_type", "comfort_cooling_setpoint_f",
                        "comfort_heating_setpoint_f", "comfort_min_f", "comfort_max_f", "pool_pump_kw",
                        "optimization_priority", "occupancy"]
                known = {k: prefs[k] for k in keep if k in prefs}
                extra = {k: v for k, v in prefs.items() if k not in DEFAULT_KEYS}
                lines.append(f"- Household profile: {json.dumps(known)}")
                if extra:
                    lines.append(f"- Preferences the user told us: {json.dumps(extra)}")
        return {
            "runtime_context": "\n".join(lines),
            "iterations": 0,
            "tool_log": [],
            "decisions": [{"node": "prepare_context", "at": now.isoformat(timespec="seconds"),
                           "detail": "runtime context built"}],
            "errors": [],
            "revisions": 0,
            "verification": {},
            "final_answer": None,
        }

    def _system_messages(self, state: EnergyAdvisorState) -> List[SystemMessage]:
        return [SystemMessage(content=f"{self.instructions}\n\n{state.get('runtime_context', '')}")]

    def _invoke_with_retry(self, runnable, messages) -> AIMessage:
        delay = 1.5
        last: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return runnable.invoke(messages)
            except Exception as exc:  # rate limit, timeout, gateway hiccup
                last = exc
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
        raise last  # type: ignore[misc]

    def _call_model(self, state: EnergyAdvisorState) -> Dict[str, Any]:
        iterations = state.get("iterations", 0) + 1
        messages = self._system_messages(state) + list(state["messages"])
        try:
            response = self._invoke_with_retry(self.llm_with_tools, messages)
        except Exception as exc:
            msg = (f"I'm sorry - I couldn't reach the language model ({type(exc).__name__}: {exc}). "
                   "Please try again in a moment.")
            return {"messages": [AIMessage(content=msg)], "iterations": iterations,
                    "errors": state.get("errors", []) + [f"llm: {exc}"]}
        calls = [c["name"] for c in getattr(response, "tool_calls", []) or []]
        decision = {"node": "agent", "iteration": iterations,
                    "detail": f"requested tools: {calls}" if calls else "produced final answer"}
        return {"messages": [response], "iterations": iterations,
                "decisions": state.get("decisions", []) + [decision]}

    def _route_after_agent(self, state: EnergyAdvisorState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            if state.get("iterations", 0) >= self.max_iterations:
                return "force_answer"
            return "tools"
        return "verify"

    # Citations look like "tip_hvac_optimization.txt"; anything else after "source:" is not a real file.
    _CITED = re.compile(r"tip_[A-Za-z0-9_]+\.txt")

    def _verify(self, state: EnergyAdvisorState) -> Dict[str, Any]:
        """Quality gate: check knowledge-base use and citations before the answer is released."""
        answer = state["messages"][-1].content if state["messages"] else ""
        answer = answer if isinstance(answer, str) else str(answer)
        log = state.get("tool_log", [])
        issues: List[str] = []
        if self.verify_answers and log:  # an energy question answered with data (out-of-scope replies use no tools)
            searched = [t for t in log if t["tool"] == "search_energy_tips" and t["status"] == "success"]
            retrieved = {tip.get("source") for t in searched for tip in t["output"].get("tips", [])}
            cited = set(self._CITED.findall(answer))
            if not searched:
                issues.append("You gave advice without consulting the knowledge base. Call search_energy_tips for "
                              "the main topic of this question and cite the file names it returns.")
            elif cited - retrieved:
                issues.append(f"You cited {sorted(cited - retrieved)}, which search_energy_tips did not return. "
                              f"Cite only these retrieved files: {sorted(retrieved)}.")
            if re.search(r"source:(?!\s*tip_)", answer, re.I):  # whitespace inside the lookahead: no backtracking
                issues.append("Every citation must be an exact file name returned by search_energy_tips, "
                              "written as (source: tip_name.txt).")
            # Question types that must be backed by a specific tool before the answer can be released.
            succeeded = {t["tool"] for t in log if t["status"] == "success"}
            question = state.get("question") or ""
            for pattern, tool_name, instruction in REQUIRED_TOOL_RULES:
                if pattern.search(question) and tool_name not in succeeded:
                    issues.append(instruction)
        revisions = state.get("revisions", 0)
        decisions = list(state.get("decisions", []))
        if issues and revisions < self.max_revisions:
            critique = HumanMessage(content="(Automated quality check - revise before the answer is sent)\n- "
                                            + "\n- ".join(issues)
                                            + "\nThen reply with the complete revised answer in the same format.")
            decisions.append({"node": "verify", "detail": f"revision requested: {issues}"})
            return {"messages": [critique], "revisions": revisions + 1, "decisions": decisions,
                    "verification": {"passed": False, "issues": issues, "revision": revisions + 1}}
        decisions.append({"node": "verify", "detail": "passed" if not issues else f"accepted with issues: {issues}"})
        return {"decisions": decisions, "verification": {"passed": not issues, "issues": issues, "revision": revisions}}

    def _route_after_verify(self, state: EnergyAdvisorState) -> str:
        return "agent" if isinstance(state["messages"][-1], HumanMessage) else "finalize"

    def _run_tools(self, state: EnergyAdvisorState) -> Dict[str, Any]:
        last: AIMessage = state["messages"][-1]
        outputs, log = [], list(state.get("tool_log", []))
        errors = list(state.get("errors", []))
        for call in last.tool_calls:
            name, args, call_id = call["name"], call.get("args", {}), call["id"]
            started = time.perf_counter()
            tool = self.tools_by_name.get(name)
            if tool is None:
                result: Any = {"error": f"Unknown tool '{name}'. Available: {sorted(self.tools_by_name)}"}
            else:
                try:
                    result = tool.invoke(args)
                except Exception as exc:  # argument validation errors, unexpected failures
                    result = {"error": f"{type(exc).__name__}: {exc}"}
            status = "error" if isinstance(result, dict) and "error" in result else "success"
            if status == "error":
                errors.append(f"{name}: {result['error']}")
            content = json.dumps(result, default=_to_builtin)
            # Round-trip to plain JSON types: numpy/pandas scalars in a tool result would otherwise reach the
            # checkpointer, which cannot serialise them, and crash the whole run.
            result = json.loads(content)
            truncated = len(content) > MAX_TOOL_OUTPUT_CHARS
            if truncated:
                content = content[:MAX_TOOL_OUTPUT_CHARS] + '... [truncated: ask for a narrower range]"'
            outputs.append(ToolMessage(content=content, tool_call_id=call_id, name=name, status=status))
            log.append({
                "tool": name, "args": args, "status": status,
                "latency_ms": round(1000 * (time.perf_counter() - started)),
                "output_chars": len(content), "truncated": truncated,
                "error": result.get("error") if status == "error" else None,
                "output": result,
            })
        return {"messages": outputs, "tool_log": log, "errors": errors,
                "decisions": state.get("decisions", []) + [
                    {"node": "tools", "detail": ", ".join(f"{c['name']}" for c in last.tool_calls)}]}

    def _force_answer(self, state: EnergyAdvisorState) -> Dict[str, Any]:
        """Tool budget spent: answer from the evidence already gathered."""
        last: AIMessage = state["messages"][-1]
        # Every tool call must be answered before the next model turn.
        placeholders = [ToolMessage(content='{"error": "skipped: tool budget exhausted"}',
                                    tool_call_id=c["id"], name=c["name"], status="error")
                        for c in last.tool_calls]
        nudge = HumanMessage(content="(System) Tool budget reached. Give your best final recommendation now "
                                     "using only the data already retrieved; state any assumptions.")
        messages = self._system_messages(state) + list(state["messages"]) + placeholders + [nudge]
        try:
            response = self._invoke_with_retry(self.llm, messages)
        except Exception as exc:
            response = AIMessage(content=f"I gathered data but could not compose an answer ({exc}).")
        content = response.content or ("I ran out of analysis steps before reaching a firm recommendation. "
                                       "Please ask a narrower question (one device and one day).")
        return {"messages": placeholders + [AIMessage(content=content)],
                "decisions": state.get("decisions", []) + [{"node": "force_answer",
                                                             "detail": "iteration budget exhausted"}]}

    def _finalize(self, state: EnergyAdvisorState) -> Dict[str, Any]:
        answer = state["messages"][-1].content if state["messages"] else ""
        if isinstance(answer, list):  # content blocks
            answer = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in answer)
        tools_used = [t["tool"] for t in state.get("tool_log", [])]
        return {"final_answer": answer,
                "decisions": state.get("decisions", []) + [{
                    "node": "finalize",
                    "detail": f"{len(tools_used)} tool call(s): {tools_used}; {state.get('iterations', 0)} LLM call(s)"}]}

    # ------------------------------------------------------------ public API
    def invoke(self, question: str, context: str = None, thread_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Ask the Energy Advisor a question about energy optimization.

        Args:
            question (str): The user's question about energy optimization
            context (str): Extra context such as "Location: San Francisco, CA"
            thread_id (str): Pass the same id on later calls for a multi-turn conversation
                (earlier turns are remembered); omit for an independent question.

        Returns:
            dict: the final graph state. response["messages"][-1].content is the advisor's
            answer; response["tool_log"] and response["decisions"] record what it did.
        """
        if not question or not str(question).strip():
            raise ValueError("question must be a non-empty string")
        thread_id = thread_id or str(uuid.uuid4())
        started = time.perf_counter()
        response = self.graph.invoke(
            input={"messages": [HumanMessage(content=question)], "question": question, "context": context},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 4 * self.max_iterations + 10},
        )
        response = dict(response)
        response["thread_id"] = thread_id
        response["latency_s"] = round(time.perf_counter() - started, 2)
        return response

    def ask(self, question: str, context: str = None, thread_id: Optional[str] = None) -> str:
        """Convenience wrapper returning only the answer text."""
        return self.invoke(question, context, thread_id)["final_answer"]

    def get_agent_tools(self):
        """Get list of available tools for the Energy Advisor"""
        return [t.name for t in self.tools]

    def get_graph_mermaid(self) -> str:
        return self.graph.get_graph().draw_mermaid()

