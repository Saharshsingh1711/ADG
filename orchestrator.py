"""
Autonomous Database Guardian — LangGraph Orchestrator
Deterministic state machine with MCP client integration,
LLM-powered SQL planning, and interrupt-based HITL safety gate.
"""

from __future__ import annotations

import json
import operator
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# ── Configuration ────────────────────────────────────────────────────────────

from dotenv import load_dotenv

# Load .env if present (override stale env vars)
load_dotenv(override=True)

MCP_SERVER_SCRIPT = str(Path(__file__).parent / "mcp_db_server.py")
DB_PATH = str(Path(__file__).parent / "analytics.db")
PYTHON_EXE = sys.executable


# ── Risk Classification ─────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    DESTRUCTIVE = "DESTRUCTIVE"


# ── Pydantic Models for Structured LLM Output ───────────────────────────────

class SQLPlan(BaseModel):
    """Structured output from the planner LLM."""
    sql_query: str = Field(description="The SQL statement to execute.")
    risk_level: str = Field(
        description="Either 'READ_ONLY' for SELECT/PRAGMA/EXPLAIN or 'DESTRUCTIVE' for INSERT/UPDATE/DELETE/ALTER/DROP."
    )
    explanation: str = Field(description="Brief explanation of what the query does and why.")


# ── Agent State ──────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """Strongly-typed state flowing through the LangGraph state machine."""
    messages: Annotated[list[BaseMessage], operator.add]
    schema_ddl: str
    sql_query: str
    risk_level: str
    human_approved: bool
    result_data: str
    final_answer: str
    error: str


# ── MCP Client Helpers ───────────────────────────────────────────────────────

async def _mcp_read_schema() -> str:
    """Connect to the MCP server and read the db://schema resource."""
    server_params = StdioServerParameters(
        command=PYTHON_EXE,
        args=[MCP_SERVER_SCRIPT],
        env={**os.environ, "DB_PATH": DB_PATH},
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.read_resource("db://schema")
            if result.contents:
                return result.contents[0].text if hasattr(result.contents[0], "text") else str(result.contents[0])
            return "-- Schema unavailable"


async def _mcp_call_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    """Connect to the MCP server and call a tool."""
    server_params = StdioServerParameters(
        command=PYTHON_EXE,
        args=[MCP_SERVER_SCRIPT],
        env={**os.environ, "DB_PATH": DB_PATH},
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)
            if result.content:
                return result.content[0].text if hasattr(result.content[0], "text") else str(result.content[0])
            return "{}"


# ── LLM Instance ─────────────────────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    """Create and return the ChatOpenAI LLM instance with dynamic runtime configuration."""
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")

    # If using local/Ollama endpoints without an explicit key, use dummy key
    if base_url and not api_key:
        api_key = "local-key"

    return ChatOpenAI(
        model=model,
        temperature=0,
        api_key=api_key or None,
        base_url=base_url or None,
    )


# ── Graph Nodes ──────────────────────────────────────────────────────────────

async def schema_fetcher(state: AgentState) -> dict[str, Any]:
    """
    Node: Fetch the database DDL schema via MCP.
    Caches the result — skips if schema is already loaded.
    """
    if state.get("schema_ddl"):
        return {}

    try:
        ddl = await _mcp_read_schema()
        return {"schema_ddl": ddl}
    except Exception as exc:
        return {
            "error": f"Failed to fetch schema: {exc}",
            "schema_ddl": "-- Schema fetch failed",
        }


async def planner(state: AgentState) -> dict[str, Any]:
    """
    Node: Use the LLM to generate an SQL statement from the user's
    natural language input, and classify its risk level.
    """
    # Get the latest human message
    user_messages = [m for m in state["messages"] if isinstance(m, HumanMessage)]
    if not user_messages:
        return {"error": "No user message found in state."}

    user_query = user_messages[-1].content
    schema_ddl = state.get("schema_ddl", "-- No schema available")

    system_prompt = f"""You are a precise SQL query planner for an SQLite analytics database.

DATABASE SCHEMA:
{schema_ddl}

YOUR TASK:
Given a user's natural language question, generate the exact SQL query to answer it.

RULES:
1. Generate valid SQLite SQL syntax.
2. For read operations (fetching data, counting, aggregating), use SELECT statements.
3. For data modifications (inserting, updating, deleting rows), use the appropriate DML statement.
4. For schema changes, use DDL statements.
5. Classify the risk level:
   - "READ_ONLY" for SELECT, PRAGMA, EXPLAIN, WITH statements
   - "DESTRUCTIVE" for INSERT, UPDATE, DELETE, ALTER, DROP, TRUNCATE, CREATE, REPLACE
6. Provide a brief explanation of what the query does.
7. If the user asks to see the schema or table structure, use PRAGMA or SELECT from sqlite_master.
8. Always be precise — do not generate queries that modify data unless explicitly asked."""

    try:
        llm = _get_llm()
        structured_llm = llm.with_structured_output(SQLPlan)
        plan: SQLPlan = await structured_llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_query),
        ])

        return {
            "sql_query": plan.sql_query,
            "risk_level": plan.risk_level,
            "messages": [AIMessage(content=f"📋 Plan: {plan.explanation}\n📝 SQL: `{plan.sql_query}`\n⚡ Risk: {plan.risk_level}")],
        }
    except Exception as exc:
        return {
            "error": f"Planning failed: {exc}",
            "messages": [AIMessage(content=f"❌ Planning failed: {exc}")],
        }


async def safety_gate(state: AgentState) -> dict[str, Any]:
    """
    Node: If the query is DESTRUCTIVE, raise an interrupt() to halt
    execution until the human operator approves.
    READ_ONLY queries pass through immediately.
    """
    risk_level = state.get("risk_level", "READ_ONLY")

    if risk_level == RiskLevel.DESTRUCTIVE.value:
        # Halt execution — surface the query details to the human
        approval = interrupt({
            "type": "destructive_query_approval",
            "sql_query": state.get("sql_query", ""),
            "risk_level": risk_level,
            "prompt": "This query will modify the database. Do you approve execution?",
        })

        # When resumed, `approval` contains the human's response
        if approval == "approved":
            return {"human_approved": True}
        else:
            return {
                "human_approved": False,
                "final_answer": "🚫 Query execution denied by operator. No changes were made to the database.",
                "messages": [AIMessage(content="🚫 Query denied by operator.")],
            }

    # READ_ONLY — auto-approve
    return {"human_approved": True}


def route_after_planner(state: AgentState) -> Literal["safety_gate", "synthesizer"]:
    """Conditional edge: if planning failed or no SQL generated, skip directly to synthesizer."""
    if state.get("error") or not state.get("sql_query"):
        return "synthesizer"
    return "safety_gate"


def route_after_safety_gate(state: AgentState) -> Literal["executor", "__end__"]:
    """Conditional edge: route to executor if approved, otherwise end."""
    if state.get("human_approved", False):
        return "executor"
    return "__end__"


async def executor(state: AgentState) -> dict[str, Any]:
    """
    Node: Dispatch the approved SQL query via MCP client call.
    Routes to run_read_query or run_write_query based on risk level.
    """
    sql_query = state.get("sql_query", "")
    risk_level = state.get("risk_level", "READ_ONLY")

    if not sql_query:
        return {"error": "No SQL query to execute."}

    tool_name = "run_read_query" if risk_level == RiskLevel.READ_ONLY.value else "run_write_query"

    try:
        raw_result = await _mcp_call_tool(tool_name, {"sql_query": sql_query})
        parsed = json.loads(raw_result)

        if parsed.get("error"):
            return {
                "error": parsed.get("message", "Unknown execution error"),
                "result_data": raw_result,
                "messages": [AIMessage(content=f"❌ Execution error: {parsed.get('message')}")],
            }

        return {
            "result_data": raw_result,
            "messages": [AIMessage(content=f"✅ Query executed successfully.")],
        }
    except Exception as exc:
        return {
            "error": f"Execution failed: {exc}",
            "result_data": "{}",
            "messages": [AIMessage(content=f"❌ Execution failed: {exc}")],
        }


async def synthesizer(state: AgentState) -> dict[str, Any]:
    """
    Node: Use the LLM to format raw query results into a clear,
    human-readable summary.
    """
    result_data = state.get("result_data", "{}")
    sql_query = state.get("sql_query", "")
    risk_level = state.get("risk_level", "READ_ONLY")
    error = state.get("error", "")

    # If there was an error, synthesize the error message
    if error:
        return {
            "final_answer": f"❌ Error: {error}",
            "messages": [AIMessage(content=f"❌ Error: {error}")],
        }

    # Get the user's original question
    user_messages = [m for m in state["messages"] if isinstance(m, HumanMessage)]
    user_query = user_messages[-1].content if user_messages else "Unknown query"

    synthesis_prompt = f"""You are an expert data analyst assistant. Summarize the following database query results
in a clean, professional, human-readable format.

USER'S QUESTION: {user_query}
SQL EXECUTED: {sql_query}
OPERATION TYPE: {risk_level}
RAW RESULTS:
{result_data}

FORMATTING RULES:
- If the result contains multiple rows or records, ALWAYS format them as a standard GitHub Markdown table with header dividers (e.g. `| Col 1 | Col 2 |` followed by `|---|---|`).
- If it was a single scalar value (e.g. a count), state it in a clear single sentence.
- If it was a write operation, clearly state what was changed, the table affected, and row count.
- Keep the summary polished, clear, and direct. Do not dump raw JSON.
- If no data matches, state that clearly in plain language."""

    try:
        llm = _get_llm()
        response = await llm.ainvoke([
            SystemMessage(content="You are a helpful data analyst. Format query results clearly."),
            HumanMessage(content=synthesis_prompt),
        ])

        return {
            "final_answer": response.content,
            "messages": [AIMessage(content=response.content)],
        }
    except Exception as exc:
        # Fallback: return raw data if LLM fails
        return {
            "final_answer": f"📊 Raw results:\n{result_data}",
            "messages": [AIMessage(content=f"📊 Raw results:\n{result_data}")],
        }


# ── Graph Construction ───────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """
    Construct and return the compiled LangGraph state machine.

    Topology:
        START → schema_fetcher → planner
            ├─ (planning error / empty SQL) → synthesizer → END
            └─ (valid SQL) → safety_gate
                ├─ (approved) → executor → synthesizer → END
                └─ (denied)  → END
    """
    builder = StateGraph(AgentState)

    # Add nodes
    builder.add_node("schema_fetcher", schema_fetcher)
    builder.add_node("planner", planner)
    builder.add_node("safety_gate", safety_gate)
    builder.add_node("executor", executor)
    builder.add_node("synthesizer", synthesizer)

    # Wire edges
    builder.add_edge(START, "schema_fetcher")
    builder.add_edge("schema_fetcher", "planner")
    builder.add_conditional_edges("planner", route_after_planner)
    builder.add_conditional_edges("safety_gate", route_after_safety_gate)
    builder.add_edge("executor", "synthesizer")
    builder.add_edge("synthesizer", END)

    return builder


def compile_graph(checkpointer: Any | None = None) -> Any:
    """Build and compile the graph with the given checkpointer."""
    builder = build_graph()
    if checkpointer is None:
        checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer), checkpointer


# ── Convenience Export ───────────────────────────────────────────────────────

__all__ = ["AgentState", "RiskLevel", "build_graph", "compile_graph"]
