import sys
import os
from pathlib import Path
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession
import asyncio

# ── Point this at your actual server file ──
SERVER_SCRIPT = r"C:\Users\A537510\Desktop\AgenticAI\MCP_Training_Server\server.py"

async def main():
    print("=" * 50)
    print("  MCP Client — Tool Discovery & Execution")
    print("=" * 50)

    server_params = StdioServerParameters(
        command=sys.executable,          # uses the same venv Python
        args=[SERVER_SCRIPT],
        env=None                         # inherits current environment
    )

    print("\n[1] Connecting to MCP Server...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:

            print("[2] Initializing session...")
            await session.initialize()
            print("    Session initialized.\n")

            print("[3] Discovering tools...")
            tools_response = await session.list_tools()
            tools = tools_response.tools
            print(f"    Found {len(tools)} tool(s): {[t.name for t in tools]}\n")

            print("[4] Executing tools...\n")
            for tool in tools:
                inputs = TOOL_INPUTS.get(tool.name, {})
                label = ", ".join(f"{k}={v!r}" for k, v in inputs.items()) or "(no args)"
                print(f"  >> {tool.name}({label})")
                try:
                    result = await session.call_tool(tool.name, inputs)
                    print(f"     Result : {result.content[0].text}\n")
                except Exception as exc:
                    print(f"     ERROR  : {exc}\n")

    print("=" * 50)
    print("  All tools executed.")
    print("=" * 50)

TOOL_INPUTS = {
    "add_numbers":     {"a": 5, "b": 10},
    "current_time":    {},
    "employee_lookup": {"employee_id": "101"},
}

if __name__ == "__main__":
    asyncio.run(main())