"""
Autonomous Database Guardian — Interactive CLI Harness
Runs the LangGraph orchestrator, detects interrupt breakpoints for
destructive queries, prompts the human operator, and resumes execution.
Uses Rich for sleek, professional terminal UI with formatted tables & markdown.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

from dotenv import load_dotenv

# Load .env file automatically (override stale env vars)
load_dotenv(override=True)

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table

from orchestrator import compile_graph

console = Console()

# ── Help & Banner ────────────────────────────────────────────────────────────

def print_banner(session_id: str, model_name: str) -> None:
    """Print a polished banner using Rich."""
    content = (
        "[bold cyan]AI-Powered Database Interaction Engine with Deterministic Guardrails[/bold cyan]\n\n"
        "• [green]Natural language ➔ SQL[/green] with automatic risk classification\n"
        "• [yellow]Destructive queries[/yellow] require explicit human approval via LangGraph interrupts\n"
        "• [magenta]MCP Stdio Server[/magenta] for clean tool & schema resource decoupling\n\n"
        f"[dim]Session: {session_id} | Model: {model_name}[/dim]\n"
        "[dim]Commands: Type your query | 'schema' for DDL | 'help' for examples | 'quit' to exit[/dim]"
    )
    console.print(
        Panel(
            content,
            title="[bold yellow]🛡️  AUTONOMOUS DATABASE GUARDIAN  🛡️[/bold yellow]",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def print_help() -> None:
    """Display usage help and example queries."""
    table = Table(title="📖 Example Queries & Expected Behaviors", border_style="dim")
    table.add_column("Query", style="green", no_wrap=False)
    table.add_column("Type", style="cyan")
    table.add_column("Behavior", style="white")

    table.add_row(
        "how many users are there?",
        "READ-ONLY",
        "Executes SELECT COUNT(*) immediately ➔ returns count",
    )
    table.add_row(
        "show top 5 orders with user details",
        "READ-ONLY",
        "Executes multi-table JOIN ➔ returns formatted table",
    )
    table.add_row(
        "insert user 'sam' with email 'sam@test.com'",
        "DESTRUCTIVE",
        "Pauses at safety gate ➔ asks for [Y/n] confirmation",
    )
    table.add_row(
        "delete system logs with level DEBUG",
        "DESTRUCTIVE",
        "Pauses at safety gate ➔ asks for [Y/n] confirmation",
    )
    table.add_row(
        "schema",
        "INSPECTION",
        "Reads full db://schema DDL from MCP server",
    )

    console.print(table)


# ── Core CLI Loop ────────────────────────────────────────────────────────────

async def run_cli() -> None:
    """Main interactive CLI loop."""

    # Pre-flight checks
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
    if not api_key and not base_url:
        console.print(
            Panel(
                "[bold red]OPENAI_API_KEY (or OPENAI_BASE_URL) is not set![/bold red]\n\n"
                "Please configure your .env file with your API key:\n"
                "  OPENAI_API_KEY=your_key_here\n"
                "  OPENAI_BASE_URL=https://api.groq.com/openai/v1 (optional for Groq/Ollama)",
                title="[red]Configuration Error[/red]",
                border_style="red",
            )
        )
        sys.exit(1)

    # Compile the graph with MemorySaver
    graph, checkpointer = compile_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    model_name = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")

    print_banner(thread_id, model_name)
    console.print()

    while True:
        try:
            # Read user input
            user_input = Prompt.ask("\n[bold green]🗣️  You[/bold green]").strip()

            if not user_input:
                continue

            # Handle special commands
            if user_input.lower() in ("quit", "exit", "q"):
                console.print("\n[bold cyan]👋 Goodbye! Database Guardian shutting down.[/bold cyan]\n")
                break

            if user_input.lower() == "help":
                print_help()
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

            console.print("[dim]⏳ Thinking & planning query...[/dim]")

            # Run the graph — may halt at safety_gate interrupt
            try:
                result = await graph.ainvoke(input_state, config=config)
            except Exception as invoke_exc:
                console.print(Panel(f"[red]Invocation error:[/red] {invoke_exc}", border_style="red"))
                continue

            # Check for pending interrupts (destructive query approval)
            state_snapshot = await graph.aget_state(config)

            while state_snapshot.next:
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

                    warning_content = (
                        f"[bold red]RISK LEVEL: {risk}[/bold red]\n\n"
                        f"[bold white]Proposed SQL Query:[/bold white]\n"
                    )
                    console.print(
                        Panel(
                            warning_content + f"```sql\n{sql_query}\n```",
                            title="[bold yellow on red] ⚠️  DESTRUCTIVE QUERY REQUIRING APPROVAL [/bold yellow on red]",
                            border_style="red",
                            padding=(1, 2),
                        )
                    )

                    approved = Confirm.ask("[bold yellow]⚡ Do you authorize execution of this mutation?[/bold yellow]")

                    if approved:
                        console.print("[bold green]   ✅ Authorized — dispatching via MCP...[/bold green]")
                        resume_value = "approved"
                    else:
                        console.print("[bold red]   🚫 Denied — query aborted. No changes made.[/bold red]")
                        resume_value = "denied"

                    # Resume the graph with the approval decision
                    result = await graph.ainvoke(
                        Command(resume=resume_value),
                        config=config,
                    )

                    # Check if there are more interrupts
                    state_snapshot = await graph.aget_state(config)
                else:
                    break

            # Display final answer formatted with Rich Markdown
            final_answer = ""
            if isinstance(result, dict):
                final_answer = result.get("final_answer", "")

            if not final_answer:
                latest_state = await graph.aget_state(config)
                if hasattr(latest_state, "values"):
                    final_answer = latest_state.values.get("final_answer", "")

            if final_answer:
                if final_answer.startswith("❌"):
                    console.print(Panel(final_answer, title="[bold red]Error[/bold red]", border_style="red"))
                elif final_answer.startswith("🚫"):
                    console.print(Panel(final_answer, title="[bold yellow]Action Blocked[/bold yellow]", border_style="yellow"))
                else:
                    console.print(
                        Panel(
                            Markdown(final_answer),
                            title="[bold cyan]🛡️  Guardian[/bold cyan]",
                            border_style="blue",
                            padding=(1, 2),
                        )
                    )
            else:
                error = result.get("error", "") if isinstance(result, dict) else ""
                if error:
                    console.print(Panel(f"[red]{error}[/red]", title="[bold red]Error[/bold red]", border_style="red"))
                else:
                    console.print("[dim]No result returned.[/dim]")

            # Generate a fresh thread_id for the next query
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}

        except KeyboardInterrupt:
            console.print("\n\n[bold cyan]👋 Interrupted. Goodbye![/bold cyan]\n")
            break
        except EOFError:
            console.print("\n[bold cyan]👋 EOF reached. Goodbye![/bold cyan]\n")
            break


# ── Entrypoint ───────────────────────────────────────────────────────────────

def main() -> None:
    """Entry point for the CLI harness."""
    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
