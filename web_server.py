"""
Autonomous Database Guardian — Web Dashboard Server
FastAPI backend with WebSocket support for real-time database chat.
Serves the static frontend and exposes REST + WS endpoints.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import aiosqlite
from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from orchestrator import compile_graph

# ── Configuration ────────────────────────────────────────────────────────────

DB_PATH = str(Path(__file__).parent / "analytics.db")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Autonomous Database Guardian", version="2.0.0")

# Serve static assets (CSS, JS)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── REST Endpoints ───────────────────────────────────────────────────────────

@app.get("/")
async def serve_dashboard():
    """Serve the main dashboard HTML."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/schema")
async def get_schema():
    """Return the complete database DDL schema."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name;"
            )
            rows = await cursor.fetchall()

        if not rows:
            return JSONResponse({"ddl": "-- No tables found in the database."})

        ddl_parts: list[str] = []
        for name, create_sql in rows:
            ddl_parts.append(f"-- Table: {name}")
            ddl_parts.append(f"{create_sql};")
            ddl_parts.append("")

        return JSONResponse({"ddl": "\n".join(ddl_parts)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/audit")
async def get_audit_log():
    """Return the most recent audit log entries."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, query_text, risk_level, approved, rows_affected, "
                "result_summary, error, executed_at "
                "FROM audit_log ORDER BY executed_at DESC LIMIT 100"
            )
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = await cursor.fetchall()
            entries = [dict(zip(columns, row)) for row in rows]

        return JSONResponse({"entries": entries})
    except Exception as exc:
        return JSONResponse({"entries": [], "error": str(exc)})


@app.get("/api/stats")
async def get_db_stats():
    """Return live database metrics, table details, and security stats."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name;"
            )
            tables_info = await cursor.fetchall()

            tables = []
            total_records = 0
            for name, sql in tables_info:
                c_count = await db.execute(f"SELECT COUNT(*) FROM `{name}`")
                row = await c_count.fetchone()
                count = row[0] if row else 0
                if name != "audit_log":
                    total_records += count

                c_cols = await db.execute(f"PRAGMA table_info(`{name}`)")
                col_rows = await c_cols.fetchall()
                columns = [
                    {
                        "cid": col[0],
                        "name": col[1],
                        "type": col[2] or "ANY",
                        "notnull": bool(col[3]),
                        "dflt_value": col[4],
                        "pk": bool(col[5]),
                    }
                    for col in col_rows
                ]

                tables.append({
                    "name": name,
                    "row_count": count,
                    "columns": columns,
                    "sql": sql,
                })

            c_audit = await db.execute(
                "SELECT "
                "COUNT(*) as total, "
                "SUM(CASE WHEN risk_level = 'DESTRUCTIVE' THEN 1 ELSE 0 END) as destructive_count, "
                "SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) as blocked_count, "
                "SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) as approved_count "
                "FROM audit_log"
            )
            audit_stats_row = await c_audit.fetchone()
            audit_stats = {
                "total": audit_stats_row[0] if audit_stats_row else 0,
                "destructive": (audit_stats_row[1] if audit_stats_row and audit_stats_row[1] else 0),
                "blocked": (audit_stats_row[2] if audit_stats_row and audit_stats_row[2] else 0),
                "approved": (audit_stats_row[3] if audit_stats_row and audit_stats_row[3] else 0),
            }

            return JSONResponse({
                "tables": tables,
                "total_records": total_records,
                "audit_stats": audit_stats,
                "model": os.environ.get("LLM_MODEL", "openai/gpt-oss-120b"),
                "db_path": os.path.basename(DB_PATH),
                "mcp_status": "online",
            })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── WebSocket Chat Handler ───────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle real-time chat sessions over WebSocket."""
    await websocket.accept()

    # Each connection gets an isolated LangGraph + MemorySaver
    graph, checkpointer = compile_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    model_name = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")

    await websocket.send_json({
        "type": "connected",
        "session_id": thread_id[:8],
        "model": model_name,
    })

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "query":
                await _handle_query(websocket, graph, config, data.get("text", ""))
            elif msg_type == "approve":
                await _handle_approval(websocket, graph, config, data.get("decision", "denied"))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


# ── Internal Handlers ────────────────────────────────────────────────────────

async def _handle_query(ws: WebSocket, graph, config, text: str) -> None:
    """Run a user query through the LangGraph pipeline."""
    text = text.strip()
    if not text:
        return

    if text.lower() == "schema":
        text = "Show me the complete database schema with all table definitions"

    await ws.send_json({"type": "thinking"})

    # schema_ddl is omitted so the cached schema persists across turns
    input_state = {
        "messages": [HumanMessage(content=text)],
        "sql_query": "",
        "risk_level": "",
        "human_approved": False,
        "result_data": "",
        "final_answer": "",
        "error": "",
    }

    start_time = time.time()

    try:
        result = await graph.ainvoke(input_state, config=config)
    except Exception as exc:
        await ws.send_json({"type": "error", "message": f"Invocation error: {exc}"})
        return

    # Check for pending interrupt (destructive query → approval needed)
    state_snapshot = await graph.aget_state(config)

    if state_snapshot.next:
        interrupt_data = _extract_interrupt(state_snapshot)
        if interrupt_data and isinstance(interrupt_data, dict):
            await ws.send_json({
                "type": "approval_required",
                "sql": interrupt_data.get("sql_query", ""),
                "risk": interrupt_data.get("risk_level", "DESTRUCTIVE"),
            })
            return

    elapsed = time.time() - start_time
    await _send_result(ws, result, graph, config, elapsed)


async def _handle_approval(ws: WebSocket, graph, config, decision: str) -> None:
    """Resume the graph after human approval or denial."""
    resume_value = "approved" if decision == "approved" else "denied"

    await ws.send_json({"type": "thinking"})

    start_time = time.time()
    try:
        result = await graph.ainvoke(Command(resume=resume_value), config=config)
    except Exception as exc:
        await ws.send_json({"type": "error", "message": f"Resume error: {exc}"})
        return

    elapsed = time.time() - start_time
    await _send_result(ws, result, graph, config, elapsed)


def _extract_interrupt(state_snapshot) -> dict | None:
    """Pull the interrupt payload from a LangGraph state snapshot."""
    if hasattr(state_snapshot, "tasks") and state_snapshot.tasks:
        for task in state_snapshot.tasks:
            if hasattr(task, "interrupts") and task.interrupts:
                for intr in task.interrupts:
                    return intr.value if hasattr(intr, "value") else intr
    return None


async def _send_result(ws: WebSocket, result, graph, config, elapsed: float) -> None:
    """Extract the final answer from the graph state and send it to the client."""
    final_answer = ""
    if isinstance(result, dict):
        final_answer = result.get("final_answer", "")

    if not final_answer:
        try:
            latest = await graph.aget_state(config)
            if hasattr(latest, "values"):
                final_answer = latest.values.get("final_answer", "")
        except Exception:
            pass

    sql_query = result.get("sql_query", "") if isinstance(result, dict) else ""
    risk_level = result.get("risk_level", "") if isinstance(result, dict) else ""
    error = result.get("error", "") if isinstance(result, dict) else ""

    if error and not final_answer:
        await ws.send_json({"type": "error", "message": error})
    else:
        await ws.send_json({
            "type": "result",
            "answer": final_answer or "No result returned.",
            "sql": sql_query,
            "risk": risk_level,
            "execution_time": round(elapsed, 2),
        })


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8000))
    print(f"\n🚀 ADG Dashboard running at: http://localhost:{port}\n")
    uvicorn.run("web_server:app", host=host, port=port, reload=True)
