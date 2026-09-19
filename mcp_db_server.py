"""
Autonomous Database Guardian — MCP Database Server
FastMCP/MCPServer exposing database schema as a resource and
read/write query tools over stdio transport.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import aiosqlite
from mcp.server.mcpserver import MCPServer

# ── Configuration ────────────────────────────────────────────────────────────

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "analytics.db"))

# SQL keywords considered safe for read-only execution
_READ_SAFE_PREFIXES = frozenset({"SELECT", "PRAGMA", "EXPLAIN", "WITH"})

# SQL keywords that indicate a mutating/destructive operation
_WRITE_PREFIXES = frozenset({"INSERT", "UPDATE", "DELETE", "ALTER", "DROP", "TRUNCATE", "CREATE", "REPLACE"})

# ── Server Instance ─────────────────────────────────────────────────────────

mcp = MCPServer(
    "DatabaseGuardian",
    instructions=(
        "A database guardian MCP server providing safe access to an SQLite "
        "analytics database. Use db://schema to inspect the schema. Use "
        "run_read_query for SELECT/PRAGMA/EXPLAIN statements and "
        "run_write_query for INSERT/UPDATE/DELETE/ALTER operations."
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _first_keyword(sql: str) -> str:
    """Extract the leading SQL keyword from a statement (uppercased)."""
    stripped = sql.strip()
    # Strip leading comments (-- or /* */)
    stripped = re.sub(r"^(--[^\n]*\n|/\*.*?\*/\s*)+", "", stripped, flags=re.DOTALL)
    match = re.match(r"(\w+)", stripped)
    return match.group(1).upper() if match else ""


async def _get_connection() -> aiosqlite.Connection:
    """Open and return an aiosqlite connection with row_factory enabled."""
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON;")
    return db


async def _rows_to_dicts(cursor: aiosqlite.Cursor) -> list[dict[str, Any]]:
    """Convert cursor rows to a list of dictionaries."""
    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    rows = await cursor.fetchall()
    return [dict(zip(columns, row)) for row in rows]


# ── Resource: Database Schema ────────────────────────────────────────────────

@mcp.resource("db://schema")
async def get_database_schema() -> str:
    """
    Returns the complete DDL (CREATE TABLE statements) for every table
    in the analytics database.
    """
    db = await _get_connection()
    try:
        cursor = await db.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name;"
        )
        rows = await cursor.fetchall()

        if not rows:
            return "-- No tables found in the database."

        ddl_parts: list[str] = []
        for row in rows:
            table_name = row[0]
            create_sql = row[1]
            ddl_parts.append(f"-- Table: {table_name}")
            ddl_parts.append(f"{create_sql};")
            ddl_parts.append("")

        return "\n".join(ddl_parts)
    finally:
        await db.close()


# ── Tool: Read Query ─────────────────────────────────────────────────────────

@mcp.tool()
async def run_read_query(sql_query: str) -> str:
    """
    Execute a read-only SQL query against the analytics database.

    Only SELECT, PRAGMA, EXPLAIN, and WITH (CTE) statements are permitted.
    Returns results as a JSON array of row objects.

    Args:
        sql_query: The SQL SELECT/PRAGMA/EXPLAIN statement to execute.
    """
    keyword = _first_keyword(sql_query)

    if keyword not in _READ_SAFE_PREFIXES:
        return json.dumps({
            "error": True,
            "message": (
                f"Blocked: '{keyword}' is not a read-safe operation. "
                f"Allowed prefixes: {sorted(_READ_SAFE_PREFIXES)}. "
                f"Use run_write_query for mutating operations."
            ),
        })

    db = await _get_connection()
    try:
        cursor = await db.execute(sql_query)
        records = await _rows_to_dicts(cursor)
        return json.dumps({
            "error": False,
            "row_count": len(records),
            "data": records,
        })
    except Exception as exc:
        return json.dumps({
            "error": True,
            "message": f"Query execution failed: {exc}",
        })
    finally:
        await db.close()


# ── Tool: Write Query ────────────────────────────────────────────────────────

@mcp.tool()
async def run_write_query(sql_query: str) -> str:
    """
    Execute a mutating SQL statement against the analytics database.

    Supports INSERT, UPDATE, DELETE, ALTER, DROP, CREATE, and REPLACE.
    The orchestrator is responsible for obtaining human approval BEFORE
    calling this tool.

    Args:
        sql_query: The SQL mutation statement to execute.
    """
    keyword = _first_keyword(sql_query)

    if keyword in _READ_SAFE_PREFIXES:
        return json.dumps({
            "error": True,
            "message": (
                f"'{keyword}' is a read-only operation. "
                f"Use run_read_query instead."
            ),
        })

    if keyword not in _WRITE_PREFIXES:
        return json.dumps({
            "error": True,
            "message": f"Unrecognized SQL operation: '{keyword}'.",
        })

    db = await _get_connection()
    try:
        cursor = await db.execute(sql_query)
        await db.commit()
        return json.dumps({
            "error": False,
            "operation": keyword,
            "rows_affected": cursor.rowcount,
            "message": f"Successfully executed {keyword} — {cursor.rowcount} row(s) affected.",
        })
    except Exception as exc:
        return json.dumps({
            "error": True,
            "message": f"Write query failed: {exc}",
        })
    finally:
        await db.close()


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
