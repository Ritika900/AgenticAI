"""
MCP Training Server
Exposes three tools: add_numbers, current_time, employee_lookup
"""

from mcp.server.fastmcp import FastMCP
from datetime import datetime

mcp = FastMCP("training-mcp-server")

# ── In-memory data store (replace with DB in production) ──
EMPLOYEES: dict[str, str] = {
    "101": "Mahesh",
    "102": "Anita",
    "103": "Rahul",
}


@mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


@mcp.tool()
def current_time() -> str:
    """Return the current date and time as an ISO-formatted string."""
    return datetime.now().isoformat()


@mcp.tool()
def employee_lookup(employee_id: str) -> str:
    """Look up an employee name by their ID. Returns an error message if not found."""
    return EMPLOYEES.get(employee_id, f"Employee '{employee_id}' not found.")


if __name__ == "__main__":
    import sys
    if "--verbose" in sys.argv or "-v" in sys.argv:
        print("=" * 50)
        print("  MCP Server — training-mcp-server")
        print("=" * 50)
        print("\n  Registered Tools:")
        for name in ["add_numbers", "current_time", "employee_lookup"]:
            print(f"    ✓ {name}")
        print("\n  Transport : stdio")
        print("  Status    : Waiting for client connection...\n")
        print("  Tip: Test with MCP Inspector:")
        print("  $ npx @modelcontextprotocol/inspector python server/server.py")
        print("=" * 50 + "\n")
    mcp.run()