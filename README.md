# 🛡️ Autonomous Database Guardian (ADG)

> **A production-grade Agentic AI database interaction engine built with the Model Context Protocol (MCP), LangGraph deterministic state machines, and Human-in-the-Loop (HITL) safety guardrails.**

---

## 📌 Table of Contents
- [Overview](#-overview)
- [Why Autonomous Database Guardian?](#-why-autonomous-database-guardian)
- [System Architecture](#-system-architecture)
- [Key Features](#-key-features)
- [Project Structure](#-project-structure)
- [Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Configuration](#configuration)
  - [Database Initialization](#database-initialization)
  - [Running the Guardian](#running-the-guardian)
- [Usage & Live Examples](#-usage--live-examples)
  - [1. Read-Only Query (Auto-Executed)](#1-read-only-query-auto-executed)
  - [2. Destructive Mutation (Human-in-the-Loop Approval)](#2-destructive-mutation-human-in-the-loop-approval)
  - [3. Schema Introspection](#3-schema-introspection)
- [Real-World Engineering: Relational Integrity & FK Constraints](#-real-world-engineering-relational-integrity--fk-constraints)
- [Tech Stack](#-tech-stack)
- [License](#-license)

---

## 🌟 Overview

Connecting LLMs directly to production databases poses severe risks: prompt injection, accidental deletions (e.g. `DELETE FROM users;` without a `WHERE` clause), or corrupted relational state.

**Autonomous Database Guardian (ADG)** solves this by decoupling tool exposure via a standardized **Model Context Protocol (MCP)** server and orchestrating execution through a deterministic **LangGraph** state machine. Safe read queries execute at machine speed, while mutating operations (`INSERT`, `UPDATE`, `DELETE`, `ALTER`, `DROP`) physically halt at the runtime level via LangGraph `interrupt()`, requiring human operator authorization before touching the database.

---

## ⚡ Why Autonomous Database Guardian?

| Traditional "Chat-with-DB" Scripts | **Autonomous Database Guardian (ADG)** |
| :--- | :--- |
| **Soft Prompt Constraints**: Relies on *"please don't delete data"*, easily bypassed by hallucinations or prompt injection. | **Hardcoded State Guardrails**: Execution physically stops at the LangGraph state machine level via `interrupt()`. |
| **Coupled DB Logic**: DB connections and driver calls are tangled inside agent prompts. | **Standardized MCP Protocol**: Database is an isolated MCP server (`db://schema`, `run_read_query`, `run_write_query`). |
| **Silent Failures & Orphaned Data**: Blindly executes queries without schema safeguards. | **Relational Integrity Enforcement**: Enforces `PRAGMA foreign_keys = ON;` and structured dependency validation. |
| **Unstyled Dumps**: Dumps raw JSON and unformatted markdown to terminal. | **Rich Terminal UI**: Polished box-drawing panels, clean tables, and syntax highlighting. |

---

## 🏛️ System Architecture

```
                        User Natural Language Query
                                     │
                                     ▼
                    ┌──────────────────────────────────┐
                    │      schema_fetcher (MCP)        │ ◄── Reads 'db://schema'
                    └────────────────┬─────────────────┘
                                     │
                                     ▼
                    ┌──────────────────────────────────┐
                    │          planner (LLM)           │ ──► Generates SQL & Risk Level
                    └────────────────┬─────────────────┘     (READ_ONLY vs DESTRUCTIVE)
                                     │
                                     ▼
                               ┌───────────┐
                               │ Risk Type?│
                               └─────┬─────┘
                                     │
             ┌───────────────────────┴───────────────────────┐
             ▼                                               ▼
       [ READ_ONLY ]                                  [ DESTRUCTIVE ]
             │                                               │
             │                                               ▼
             │                                ┌─────────────────────────────┐
             │                                │      safety_gate Node       │
             │                                │   (LangGraph interrupt())   │
             │                                └──────────────┬──────────────┘
             │                                               │
             │                              ┌────────────────┴────────────────┐
             │                              ▼                                 ▼
             │                       [ 🚫 Denied ]                     [ ✅ Approved ]
             │                              │                                 │
             │                              ▼                                 │
             │                            [ END ]                             │
             │                                                                │
             └──────────────────────────────┬─────────────────────────────────┘
                                            │
                                            ▼
                    ┌──────────────────────────────────┐
                    │          executor (MCP)          │ ──► Dispatches Tool Call
                    └────────────────┬─────────────────┘     over Stdio Transport
                                     │
                                     ▼
                    ┌──────────────────────────────────┐
                    │        synthesizer (LLM)         │ ──► Formats Results as Tables
                    └────────────────┬─────────────────┘
                                     │
                                     ▼
                        Polished Rich Response Panel
```

---

## ✨ Key Features

- **Interactive Web Dashboard**: Real-time WebSocket-powered glassmorphic web UI with live markdown rendering, visual HITL approval modals, audit log inspector, and schema viewer.
- **MCP Architecture (Model Context Protocol)**: Uses the official MCP Python SDK (`MCPServer`) to expose schema resources and query tools over `stdio`.
- **Deterministic State Graph**: 5-node LangGraph pipeline (`schema_fetcher` ➔ `planner` ➔ `safety_gate` ➔ `executor` ➔ `synthesizer`).
- **Human-in-the-Loop (HITL) Gate**: Destructive queries halt via dynamic `interrupt()` and resume only with an explicit approval token.
- **Audit Logging**: Every query, risk classification, approval status, execution time, and row count is persisted to the `audit_log` table.
- **Multi-Turn Conversation Memory**: Maintains thread context across questions so the LLM remembers previous queries and entities.
- **Dynamic Multi-Provider LLM Support**: Works with **Groq** (free ultra-fast inference), **OpenAI**, **Google Gemini**, or **local Ollama** via standard OpenAI-compatible base URLs.
- **Relational Integrity Protection**: Foreign key enforcement prevents orphaned records and database corruption.
- **Rich Terminal UI & Web UI**: ANSI color banners, styled Markdown tables, and structured warning boxes in terminal + web interface.

---

## 📁 Project Structure

```text
ADG/
├── mcp_db_server.py      # MCP Server: db://schema resource & read/write tools (stdio)
├── orchestrator.py       # LangGraph state machine with planner, safety gate & synthesizer
├── web_server.py         # FastAPI + WebSocket backend for the web dashboard
├── static/               # Glassmorphic frontend (index.html, style.css, app.js)
├── main.py               # Interactive CLI harness with Rich formatting & HITL loop
├── init_db.py            # SQLite seed script (users, orders, system_logs, audit_log)
├── test_server.py        # Automated MCP smoke test suite
├── requirements.txt      # Pinned dependencies
├── .env.example          # Environment variable template
├── .env                  # Local secret configuration (git-ignored)
└── analytics.db          # SQLite database instance (git-ignored)
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+ (tested on Python 3.10 – 3.14)
- Git

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Saharshsingh1711/ADG.git
   cd ADG
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # Windows (PowerShell)
   python -m venv .venv
   .venv\Scripts\activate

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

### Configuration

Create a `.env` file in the project root (you can copy `.env.example`):

**Option A: Using Groq (Free & Fast - Recommended)**
```env
OPENAI_API_KEY=gsk_your_groq_api_key_here
OPENAI_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b
```

**Option B: Using OpenAI**
```env
OPENAI_API_KEY=sk-proj-your_openai_key_here
LLM_MODEL=gpt-4o-mini
```

**Option C: Using Local Ollama (Zero External Cost)**
```env
OPENAI_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3.1
```

### Database Initialization

Pre-seed the SQLite database with sample records (`users`, `orders`, `system_logs`, `audit_log`):

```bash
python init_db.py
```

### Running the Guardian

You can run ADG via the **Web Dashboard** or the **Terminal CLI**:

#### 🌐 Option 1: Web Dashboard (Recommended)
```bash
python web_server.py
```
Open **`http://localhost:8000`** in your browser to interact with the real-time AI dashboard.

#### 💻 Option 2: Terminal CLI
```bash
python main.py
```

---

## 💻 Usage & Live Examples

### 1. Read-Only Query (Auto-Executed)

Safe read queries execute immediately without interrupting the user:

```text
🗣️ You: show all admin users

┌─────────────────────────────── 🛡️  Guardian ────────────────────────────────┐
│ Admin Users (4 records)                                                     │
│                                                                             │
│  id  username  email                role   created_at                       │
│  ─────────────────────────────────────────────────────────────              │
│  1   alice     alice@example.com    admin  2024-01-15 09:30:00              │
│  5   eve       eve@example.com      admin  2024-05-12 08:20:00              │
│  10  judy      judy@example.com     admin  2024-10-01 12:00:00              │
│  11  saharsh   saharsh@example.com  admin  2026-09-19 11:46:32              │
│                                                                             │
│ The query returned four users whose role is set to admin.                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2. Destructive Mutation (Human-in-the-Loop Approval)

When a query attempts to mutate or delete data, the safety gate pauses execution:

```text
🗣️ You: delete all system logs with level DEBUG

┌────────────── ⚠️  DESTRUCTIVE QUERY REQUIRING APPROVAL ──────────────┐
│ RISK LEVEL: DESTRUCTIVE                                              │
│                                                                      │
│ Proposed SQL Query:                                                  │
│ ```sql                                                               │
│ DELETE FROM system_logs WHERE level = 'DEBUG';                       │
│ ```                                                                  │
└──────────────────────────────────────────────────────────────────────┘

⚡ Do you authorize execution of this mutation? [y/n]: y
   ✅ Authorized — dispatching via MCP...

┌─────────────────────────────── 🛡️  Guardian ────────────────────────────────┐
│ Operation: Delete system logs with level DEBUG                              │
│ Type: Destructive (write)                                                   │
│ Result: Successfully executed DELETE — 2 rows removed from system_logs.    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3. Schema Introspection

Type `schema` to view the full DDL retrieved dynamically via MCP resource streaming:

```text
🗣️ You: schema
```

---

## 🛡️ Real-World Engineering: Relational Integrity & FK Constraints

During live execution tests, when deleting a user record (`eve`) who has active order records, SQLite returned:
`❌ Error: Write query failed: FOREIGN KEY constraint failed`

### Why This Matters for Agentic AI:
1. **Defensive Depth**: Prompt guardrails alone cannot guarantee relational integrity. The database schema must enforce hard foreign key constraints (`PRAGMA foreign_keys = ON;`).
2. **Multi-Step Agent Reasoning**: When dealing with relational constraints, the agent is prompted to decompose actions into dependent workflows (e.g., *"delete all orders for user eve, then delete user eve"*).

---

## 🧰 Tech Stack

- **Orchestration**: [LangGraph](https://github.com/langchain-ai/langgraph) (`StateGraph`, `MemorySaver`, `interrupt()`, `Command`)
- **Protocol**: [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) (`MCPServer`, `stdio_client`, `ClientSession`)
- **LLM Layer**: [LangChain Core & OpenAI Client](https://github.com/langchain-ai/langchain)
- **Inference Hardware**: [Groq](https://groq.com/) LPU Cloud (`openai/gpt-oss-120b`) / OpenAI
- **Database**: [aiosqlite](https://github.com/omnilib/aiosqlite) (Async SQLite with Foreign Key PRAGMA)
- **Terminal UI**: [Rich](https://github.com/Textualize/rich) (Markdown, Syntax Highlighting, Panels, Tables)

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
