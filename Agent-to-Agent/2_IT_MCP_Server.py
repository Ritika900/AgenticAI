# ╔══════════════════════════════════════════════════════════╗
# ║  FILE 2: IT MCP Server                                 ║
# ║  Run: python 2_IT_MCP_Server.py                        ║
# ║  Port: 8011                                            ║
# ╚══════════════════════════════════════════════════════════╝
#
#  WHAT:  The IT data layer — turns ticket & asset data into tools.
#  ROLE:  Same pattern as File 1 (HR MCP), just different data.
#         The IT Agent (file 4) connects here.
#
# ─────────────────────────────────────────────────────────────

import random
from fastmcp import FastMCP

mcp = FastMCP("IT Data Server")


# ─────────────────────────────────────────────────────────────
# SECTION 1: Fake Database
# ─────────────────────────────────────────────────────────────

TICKETS = {
    "INC-001": {"status": "In Progress", "issue": "Laptop slow after update", "assigned_to": "Ravi - IT", "eta": "Today 5 PM"},
    "INC-002": {"status": "Resolved",    "issue": "VPN not connecting",       "assigned_to": "Sunita - IT", "eta": "Resolved"},
    "INC-003": {"status": "Open",        "issue": "Outlook not syncing",      "assigned_to": "Unassigned",  "eta": "Within 4 hours"},
}

ASSETS = {
    "EMP001": {"laptop": "Dell Latitude 5540", "phone": "iPhone 14",   "monitor": "LG 27UK850"},
    "EMP002": {"laptop": "HP EliteBook 840",   "phone": "Samsung S23", "monitor": None},
}


# ─────────────────────────────────────────────────────────────
# SECTION 2: MCP Tools
# ─────────────────────────────────────────────────────────────

@mcp.tool()
def get_ticket_info(ticket_id: str) -> dict:
    """Get ticket status."""
    t = TICKETS.get(ticket_id.upper())
    if not t:
        return {"error": f"Ticket {ticket_id} not found"}
    return {"ticket_id": ticket_id.upper(), **t}


@mcp.tool()
def create_ticket(issue_description: str, category: str, priority: str, employee_id: str = "EMP001") -> dict:
    """Create a new IT ticket."""
    tid = f"INC-{random.randint(100,999)}"
    eta = {"critical": "1h", "high": "4h", "medium": "1 day", "low": "3 days"}.get(priority, "1 day")
    return {"ticket_id": tid, "status": "Open", "eta": eta, "message": f"Ticket {tid} created."}


@mcp.tool()
def get_asset_info(employee_id: str) -> dict:
    """List IT assets for an employee."""
    a = ASSETS.get(employee_id.upper())
    if not a:
        return {"error": f"No assets for {employee_id}"}
    return {"employee_id": employee_id.upper(), "assets": {k: v for k, v in a.items() if v}}


# ─────────────────────────────────────────────────────────────
# SECTION 3: Start the MCP Server
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("IT MCP Server running at http://localhost:8011/sse")
    mcp.run(transport="sse", host="0.0.0.0", port=8011)
