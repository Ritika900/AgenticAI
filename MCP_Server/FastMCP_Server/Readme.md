# 🔧 MCP Training Server

A minimal [Model Context Protocol (MCP)] server and client built with **FastMCP**, demonstrating tool registration and invocation over `stdio` transport.
---

## 🛠️ Tools Exposed

| Tool              | Input                  | Output                        |
|-------------------|------------------------|-------------------------------|
| `add_numbers`     | `a: int, b: int`       | Sum of the two integers       |
| `current_time`    | *(none)*               | Current ISO datetime string   |
| `employee_lookup` | `employee_id: str`     | Employee name or error msg    |

---


## 📖 How It Works

- The **server** registers tools using FastMCP's `@mcp.tool()` decorator and runs over `stdio`.
- The **client** spawns the server as a subprocess, initializes an MCP session, lists all tools, and calls each one.

---

## 📌 Requirements

- Python 3.10+
- `mcp[cli]` package

---
