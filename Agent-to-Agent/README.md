# Smart Office — Multi-Agent System

A production-style demo of a **multi-agent architecture** using two open standards:

- **MCP (Model Context Protocol)** — agents use MCP to talk to data/tool servers
- **A2A (Agent-to-Agent)** — agents use A2A to talk to each other

The system handles HR and IT queries for a fictional company. Agents are smart peers — they discover each other at runtime, call peers directly when needed, and never need hardcoded URLs.

---

## Architecture

```
User / Dashboard
       │  HTTP
       ▼
┌─────────────┐       registers/discovers via
│  Registry   │◄─────────────────────────────┐
│  :9000      │                              │
└─────────────┘                              │
                                             │
       ┌─────────────────────────────────────┼──────────────────────┐
       │                                     │                      │
       ▼  A2A                                ▼  A2A                 ▼  A2A
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│ Orchestrator│         │  HR Agent   │◄────────►│  IT Agent   │
│  :8000      │────────►│  :8001      │  peer    │  :8002      │
└─────────────┘         └─────────────┘  A2A     └─────────────┘
                               │                        │
                           MCP │                    MCP │
                               ▼                        ▼
                        ┌─────────────┐         ┌─────────────┐
                        │ HR MCP Svr  │         │ IT MCP Svr  │
                        │  :8010      │         │  :8011      │
                        └─────────────┘         └─────────────┘
```

### How a query flows

1. **User** types a question in the dashboard (or sends it via the `/query` API).
2. **Orchestrator** reads all registered agent cards, lets the LLM pick the best agent, and forwards the full query via A2A.
3. **HR / IT Agent** connects to its MCP server, discovers tools, discovers peer agents, and lets the LLM call tools in a loop until it has enough data to answer.
4. If a question spans domains (e.g. "show my leave AND my laptop"), the chosen agent calls the peer agent directly — the Orchestrator is not involved in that exchange.
5. The final answer travels back up the chain to the user.

---

## File Overview

| File | Role | Protocol | Port |
|------|------|----------|------|
| `0_Registry.py` | Central agent directory + live dashboard | HTTP (Starlette) | 9000 |
| `1_HR_MCP_Server.py` | HR data layer — leave, CATS, projects | MCP over SSE | 8010 |
| `2_IT_MCP_Server.py` | IT data layer — tickets, assets | MCP over SSE | 8011 |
| `3_HR_Agent.py` | HR A2A agent — queries HR MCP + peers | A2A + MCP | 8001 |
| `4_IT_Agent.py` | IT A2A agent — queries IT MCP + peers | A2A + MCP | 8002 |
| `5_Orchestrator_Client.py` | Entry-point A2A agent — routes queries | A2A | 8000 |

---

## Prerequisites

- **Python 3.10+**
- **Azure OpenAI** account with a deployed model (e.g. `gpt-4o-mini`)
- 6 free terminal windows (one per process)

## Configuration

Create a `.env` file in the same folder:

```env
AZURE_OPENAI_API_KEY=your_api_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2025-04-01-preview
```
### Sample queries to try

| Query | What it exercises |
|-------|-------------------|
| `How many leave days do I have?` | HR Agent → HR MCP |
| `What's the status of ticket INC-001?` | IT Agent → IT MCP |
| `What laptop am I assigned?` | IT Agent → IT MCP |
| `Check my leave and show my IT assets` | HR Agent → HR MCP + peer A2A to IT Agent |
| `Log 8 hours on Project Phoenix for today` | HR Agent → HR MCP (log_hours) |
| `Create an IT ticket — my VPN is not working` | IT Agent → IT MCP (create_ticket) |

---
