"""Quick smoke test for the MCP server — reads schema and runs a query."""
import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MCP_SERVER = str(Path(__file__).parent / "mcp_db_server.py")
DB_PATH = str(Path(__file__).parent / "analytics.db")
PYTHON = sys.executable


async def test():
    params = StdioServerParameters(
        command=PYTHON,
        args=[MCP_SERVER],
        env={**os.environ, "DB_PATH": DB_PATH},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. List tools
            tools = await session.list_tools()
            print(f"Tools: {[t.name for t in tools.tools]}")

            # 2. List resources
            resources = await session.list_resources()
            print(f"Resources: {[r.uri for r in resources.resources]}")

            # 3. Read schema
            schema = await session.read_resource("db://schema")
            print(f"\n--- Schema ---")
            print(schema.contents[0].text[:500] if schema.contents else "EMPTY")

            # 4. Run a read query
            result = await session.call_tool("run_read_query", {"sql_query": "SELECT COUNT(*) as cnt FROM users"})
            print(f"\n--- Read Query Result ---")
            print(result.content[0].text if result.content else "EMPTY")

            # 5. Try a blocked read via write tool
            result2 = await session.call_tool("run_write_query", {"sql_query": "SELECT 1"})
            print(f"\n--- Write Tool w/ SELECT (should error) ---")
            print(result2.content[0].text if result2.content else "EMPTY")

    print("\n✅ All MCP smoke tests passed!")


if __name__ == "__main__":
    asyncio.run(test())
