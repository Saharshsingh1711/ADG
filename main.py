"""
Autonomous Database Guardian — Interactive CLI Harness
Runs the LangGraph orchestrator, detects interrupt breakpoints for
destructive queries, prompts the human operator, and resumes execution.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from orchestrator import compile_graph

# ── ANSI Colors ──────────────────────────────────────────────────────────────

class Colors:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"
    BG_RED  = "\033[41m"


# ── Banner ───────────────────────────────────────────────────────────────────

BANNER = f"""
{Colors.CYAN}{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗
║         🛡️  AUTONOMOUS DATABASE GUARDIAN  🛡️                 ║
║         AI-Powered Database Interaction Engine               ║
╠══════════════════════════════════════════════════════════════╣
║  • Natural language → SQL with safety guardrails             ║
║  • Destructive queries require human approval                ║
║  • Powered by MCP + LangGraph                                ║
╠══════════════════════════════════════════════════════════════╣
║  Commands:                                                   ║
║    Type your question in plain English                       ║
║    'schema'  — Show database schema                          ║
║    'help'    — Show this help                                ║
║    'quit'    — Exit the guardian                              ║
╚══════════════════════════════════════════════════════════════╝{Colors.RESET}
"""

HELP_TEXT = f"""
{Colors.YELLOW}📖 Usage Examples:{Colors.RESET}
  • "How many users are there?"
  • "Show me the top 5 orders by amount"
  • "What are the error-level system logs?"
  • "Insert a new user named 'test_user' with email 'test@example.com'"
  • "Delete all system logs with level DEBUG"
  • "Show me the database schema"

{Colors.DIM}Read-only queries execute immediately.
Destructive queries (INSERT/UPDATE/DELETE/ALTER/DROP) require your approval.{Colors.RESET}
"""


# ── Core CLI Loop ────────────────────────────────────────────────────────────

async def run_cli() -> None:
    """Main interactive CLI loop."""

    # Pre-flight checks
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(f"\n{Colors.RED}{Colors.BOLD}⚠️  OPENAI_API_KEY not set!{Colors.RESET}")
        print(f"{Colors.DIM}Set it with: set OPENAI_API_KEY=sk-...{Colors.RESET}")
        print(f"{Colors.DIM}Or export OPENAI_API_KEY=sk-... on Linux/macOS{Colors.RESET}\n")
        sys.exit(1)

    # Compile the graph with MemorySaver
    graph, checkpointer = compile_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print(BANNER)
    print(f"{Colors.DIM}Session ID: {thread_id}{Colors.RESET}")
    print(f"{Colors.DIM}LLM Model:  {os.environ.get('LLM_MODEL', 'gpt-4o-mini')}{Colors.RESET}")
    print()

    while True:
        try:
            # Read user input
            user_input = input(f"{Colors.GREEN}{Colors.BOLD}🗣️  You: {Colors.RESET}").strip()

            if not user_input:
                continue

            # Handle special commands
            if user_input.lower() in ("quit", "exit", "q"):
                print(f"\n{Colors.CYAN}👋 Goodbye! Database Guardian shutting down.{Colors.RESET}\n")
                break

            if user_input.lower() == "help":
                print(HELP_TEXT)
                continue

            if user_input.lower() == "schema":
                user_input = "Show me the complete database schema with all table definitions"

            # Prepare input state
            input_state = {
                "messages": [HumanMessage(content=user_input)],
                "schema_ddl": "",
                "sql_query": "",
                "risk_level": "",
                "human_approved": False,
                "result_data": "",
                "final_answer": "",
                "error": "",
            }

            print(f"\n{Colors.DIM}⏳ Processing...{Colors.RESET}")

            # Run the graph — may halt at safety_gate interrupt
            try:
                result = await graph.ainvoke(input_state, config=config)
            except Exception as invoke_exc:
                # Check if this is an interrupt-related issue
                print(f"{Colors.RED}❌ Invocation error: {invoke_exc}{Colors.RESET}\n")
                continue

            # Check for pending interrupts (destructive query approval)
            state_snapshot = await graph.aget_state(config)

            while state_snapshot.next:
                # There are pending nodes — the graph was interrupted
                # Extract interrupt data from the state
                interrupt_data = None
                if hasattr(state_snapshot, "tasks") and state_snapshot.tasks:
                    for task in state_snapshot.tasks:
                        if hasattr(task, "interrupts") and task.interrupts:
                            for intr in task.interrupts:
                                interrupt_data = intr.value if hasattr(intr, "value") else intr
                                break

                if interrupt_data and isinstance(interrupt_data, dict):
                    sql_query = interrupt_data.get("sql_query", "N/A")
                    risk = interrupt_data.get("risk_level", "UNKNOWN")

                    print(f"\n{Colors.BG_RED}{Colors.WHITE}{Colors.BOLD}"
                          f" ⚠️  DESTRUCTIVE QUERY DETECTED "
                          f"{Colors.RESET}")
                    print(f"{Colors.YELLOW}┌─────────────────────────────────────────────┐{Colors.RESET}")
                    print(f"{Colors.YELLOW}│ Risk Level: {Colors.RED}{risk}{Colors.RESET}")
                    print(f"{Colors.YELLOW}│ SQL Query:{Colors.RESET}")
                    print(f"{Colors.YELLOW}│   {Colors.WHITE}{sql_query}{Colors.RESET}")
                    print(f"{Colors.YELLOW}└─────────────────────────────────────────────┘{Colors.RESET}")

                    approval = input(
                        f"{Colors.MAGENTA}{Colors.BOLD}   Approve execution? [Y/n]: {Colors.RESET}"
                    ).strip().lower()

                    if approval in ("y", "yes", ""):
                        print(f"{Colors.GREEN}   ✅ Approved — executing...{Colors.RESET}")
                        resume_value = "approved"
                    else:
                        print(f"{Colors.RED}   🚫 Denied — query will not execute.{Colors.RESET}")
                        resume_value = "denied"

                    # Resume the graph with the approval decision
                    result = await graph.ainvoke(
                        Command(resume=resume_value),
                        config=config,
                    )

                    # Check if there are more interrupts
                    state_snapshot = await graph.aget_state(config)
                else:
                    # Unknown interrupt — break to avoid infinite loop
                    print(f"{Colors.RED}⚠️  Unknown interrupt state. Skipping.{Colors.RESET}")
                    break

            # Display final answer
            final_answer = ""
            if isinstance(result, dict):
                final_answer = result.get("final_answer", "")

            if not final_answer:
                # Try to get from latest state
                latest_state = await graph.aget_state(config)
                if hasattr(latest_state, "values"):
                    final_answer = latest_state.values.get("final_answer", "")

            if final_answer:
                print(f"\n{Colors.BLUE}{Colors.BOLD}🤖 Guardian:{Colors.RESET}")
                print(f"{Colors.WHITE}{final_answer}{Colors.RESET}")
            else:
                error = result.get("error", "") if isinstance(result, dict) else ""
                if error:
                    print(f"\n{Colors.RED}❌ {error}{Colors.RESET}")
                else:
                    print(f"\n{Colors.DIM}No result returned.{Colors.RESET}")

            print()  # Blank line before next prompt

            # Generate a new thread_id for the next query to get fresh state
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}

        except KeyboardInterrupt:
            print(f"\n\n{Colors.CYAN}👋 Interrupted. Goodbye!{Colors.RESET}\n")
            break
        except EOFError:
            print(f"\n{Colors.CYAN}👋 EOF reached. Goodbye!{Colors.RESET}\n")
            break


# ── Entrypoint ───────────────────────────────────────────────────────────────

def main() -> None:
    """Entry point for the CLI harness."""
    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
