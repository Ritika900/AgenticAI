# ╔══════════════════════════════════════════════════════════╗
# ║  FILE 1: HR MCP Server                                 ║
# ║  Run: python 1_HR_MCP_Server.py                        ║
# ║  Port: 8010                                            ║
# ╚══════════════════════════════════════════════════════════╝
#
#  WHAT:  The HR data layer — turns HR data into tools agents can call.
#  ROLE:  This is an MCP Server (not A2A).
#         The HR Agent (file 3) connects here to look up
#         leave, CATS, and project data.
#
#  KEY IDEA:
#    @mcp.tool() turns any Python function into a tool on the network.
#    The docstring becomes the tool's description.
#    The type hints tell callers what inputs to send.
#    That's it — one decorator does all the wiring!
#
# ─────────────────────────────────────────────────────────────

from fastmcp import FastMCP

mcp = FastMCP("HR Data Server")


# ─────────────────────────────────────────────────────────────
# SECTION 1: Fake Database
# Replace these dictionaries with real DB calls in production.
# ─────────────────────────────────────────────────────────────

EMPLOYEES = {
    "EMP001": {"name": "Sanjay Mehta",  "manager": "Priya Sharma", "team": "Engineering"},
    "EMP002": {"name": "Anita Rao",     "manager": "Priya Sharma", "team": "Engineering"},
    "EMP003": {"name": "Ravi Kumar",    "manager": "Arjun Nair",   "team": "Design"},
}

LEAVE = {
    "EMP001": {"casual": 6, "sick": 7, "earned": 15},
    "EMP002": {"casual": 2, "sick": 5, "earned": 10},
    "EMP003": {"casual": 8, "sick": 8, "earned": 18},
}

PROJECTS = [
    {"code": "PHOENIX",  "name": "Project Phoenix",  "active": True},
    {"code": "HORIZON",  "name": "Project Horizon",  "active": True},
    {"code": "CATALYST", "name": "Project Catalyst", "active": True},
]

CATS = {
    "EMP001": {"week": "2024-W14", "hours": 32, "status": "draft",     "missing": ["Friday"]},
    "EMP002": {"week": "2024-W14", "hours": 40, "status": "submitted", "missing": []},
    "EMP003": {"week": "2024-W14", "hours": 0,  "status": "pending",   "missing": ["Mon","Tue","Wed","Thu","Fri"]},
}


# ─────────────────────────────────────────────────────────────
# SECTION 2: MCP Tools
#
# Each @mcp.tool() becomes a tool the agent can call over the network.
# The HR Agent (file 3) finds and uses these automatically.
# Add a new function here → the agent sees it right away.
# ─────────────────────────────────────────────────────────────

@mcp.tool()
def check_leave_balance(employee_id: str) -> dict:
    """Check remaining leave days."""
    bal = LEAVE.get(employee_id.upper())
    if not bal:
        return {"error": f"{employee_id} not found"}
    return {"employee_id": employee_id.upper(), "balance": bal}


@mcp.tool()
def apply_leave(employee_id: str, leave_type: str, from_date: str, to_date: str, reason: str = "Personal") -> dict:
    """Apply for leave."""
    bal = LEAVE.get(employee_id.upper(), {}).get(leave_type.lower(), 0)
    mgr = EMPLOYEES.get(employee_id.upper(), {}).get("manager", "Manager")
    if bal > 0:
        return {"status": "approved", "ref": f"LV-{employee_id[-3:]}-{from_date.replace('-','')}", "manager": mgr}
    return {"status": "rejected", "reason": f"No {leave_type} leave left", "manager": mgr}


@mcp.tool()
def get_valid_projects() -> list:
    """List active projects."""
    return [p for p in PROJECTS if p["active"]]


@mcp.tool()
def log_hours(employee_id: str, project_code: str, date: str, hours: float, description: str = "") -> dict:
    """Log hours on a project."""
    valid = [p["code"] for p in PROJECTS if p["active"]]
    if project_code.upper() not in valid:
        return {"error": f"Invalid project. Valid: {valid}"}
    return {"status": "logged", "message": f"{hours}h logged on {project_code.upper()} for {date}"}


@mcp.tool()
def submit_cats(employee_id: str, week: str) -> dict:
    """Submit weekly CATS (time sheet)."""
    ts = CATS.get(employee_id.upper())
    if not ts:
        return {"error": f"No CATS entry for {employee_id}"}
    if ts["missing"]:
        return {"status": "incomplete", "missing_days": ts["missing"]}
    mgr = EMPLOYEES.get(employee_id.upper(), {}).get("manager", "Manager")
    return {"status": "submitted", "ref": f"TS-{employee_id[-3:]}-{week}", "submitted_to": mgr}


# ─────────────────────────────────────────────────────────────
# SECTION 3: Start the MCP Server
#
# Starts a lightweight HTTP server on port 8010.
# The HR Agent connects to http://localhost:8010/sse
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("HR MCP Server running at http://localhost:8010/sse")
    mcp.run(transport="sse", host="0.0.0.0", port=8010)
