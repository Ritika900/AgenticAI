# ╔══════════════════════════════════════════════════════════╗
# ║  FILE 3: HR Agent (A2A Server)                         ║
# ║  Run: python 3_HR_Agent.py                             ║
# ║  Port: 8001                                            ║
# ╚══════════════════════════════════════════════════════════╝
#
#  WHAT:  An A2A agent that handles HR queries.
#         Can also talk to other agents directly (no middleman!).
#
#  FLOW:  Anyone --A2A--> HR Agent --MCP--> HR MCP Server
#                         HR Agent --A2A--> peer agents (via registry)
#
#  HOW IT WORKS:
#    1. Gets a message (from user, orchestrator, or another agent)
#    2. Connects to HR MCP Server → finds available tools
#    3. Checks registry → finds other agents → adds them as tools too
#    4. GPT picks the right tool(s) → calls MCP and/or peer agents
#    5. GPT puts together the final answer
#
#  A2A PARTS (from the a2a-sdk):
#    - AgentCard          → "Hi, I'm HR Agent, I handle leave & CATS"
#    - A2AStarletteApp    → serves the card + listens for messages
#    - AgentExecutor      → runs your logic when a message arrives
#
#  YOUR LOGIC (not part of A2A):
#    - MCP list_tools()   → find what HR tools are available
#    - discover_peers()   → find other agents from registry
#    - LLM picks tools    → MCP and/or peer
#    - LLM formats reply  → send back via A2A
#
# ─────────────────────────────────────────────────────────────

import os, json, uvicorn, httpx
import warnings
warnings.filterwarnings("ignore", message="A2AClient is deprecated")
from dotenv import load_dotenv
load_dotenv()                               # reads .env file for API keys

from uuid import uuid4
from openai import AsyncAzureOpenAI


# ─────────────────────────────────────────────────────────────
# SECTION 1: A2A & MCP Imports
# ─────────────────────────────────────────────────────────────

# MCP client — to connect to the HR MCP Server
from mcp import ClientSession
from mcp.client.sse import sse_client

# A2A SDK — to run as an A2A agent and call peers
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater, InMemoryTaskStore
from a2a.client import A2AClient            # ← for peer-to-peer A2A calls
from a2a.types import (
    AgentCard,              # ← "business card" describing this agent
    AgentSkill,             # ← what this agent can do
    AgentCapabilities,      # ← streaming? push notifications?
    TaskState,              # ← completed / failed / cancelled
    UnsupportedOperationError,
    SendMessageRequest, MessageSendParams,
    Message, TextPart, Part, Role,
)
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.errors import ServerError
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler

# Agent Registry — the ONE address every agent needs to know
REGISTRY_URL = "http://localhost:9000"

async def _trace(source, event_type, detail=""):
    """Push a trace event to the registry (for UI visualization)."""
    try:
        async with httpx.AsyncClient(verify=False, timeout=2) as c:
            await c.post(f"{REGISTRY_URL}/trace", json={
                "source": source, "type": event_type, "detail": str(detail)[:200],
            })
    except:
        pass


# ─────────────────────────────────────────────────────────────
# SECTION 2: LLM Setup (Azure OpenAI, credentials from .env)
# ─────────────────────────────────────────────────────────────

llm = AsyncAzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
    http_client=httpx.AsyncClient(verify=False),
)
MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")


# ─────────────────────────────────────────────────────────────
# SECTION 3: MCP → OpenAI Tool Converter
#
# MCP describes tools one way, OpenAI expects another format.
# This converts MCP tools into the format GPT understands.
#
# WHY: We never list tools by hand in the agent code.
#      The MCP Server is the only place tools are defined.
#      Add a new tool there → the agent finds it automatically.
# ─────────────────────────────────────────────────────────────

def mcp_tools_to_openai(mcp_tools):
    """Convert MCP tool list → OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or tool.name,
                "parameters": tool.inputSchema,
            },
        }
        for tool in mcp_tools
    ]


# ─────────────────────────────────────────────────────────────
# SECTION 4: Peer Discovery + A2A
#
# Asks the registry: "Who else is running?"
# Reads each peer's Agent Card to learn what they can do.
# Turns those cards into tools GPT can call.
# Result: GPT treats peer agents just like local MCP tools.
# ─────────────────────────────────────────────────────────────

MY_NAME = "HR Agent"

async def discover_peers():
    """Discover peer agents from registry and build tool definitions."""
    peer_tools = []   # OpenAI tool defs
    peer_map = {}     # tool_name → agent_name (for routing)
    try:
        async with httpx.AsyncClient(verify=False, timeout=5) as http:
            r = await http.get(f"{REGISTRY_URL}/agents")
            all_agents = r.json()
            for agent_name, agent_url in all_agents.items():
                if agent_name == MY_NAME:    # skip self
                    continue
                if "orchestrator" in agent_name.lower():  # skip router
                    continue
                try:
                    cr = await http.get(f"{agent_url.rstrip('/')}/.well-known/agent-card.json", timeout=3)
                    card_data = AgentCard(**cr.json())
                    tool_name = f"ask_{card_data.name.lower().replace(' ', '_')}"
                    skills_desc = ", ".join(s.name for s in card_data.skills)
                    peer_tools.append({
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": f"Ask {card_data.name} about: {skills_desc}",
                            "parameters": {
                                "type": "object",
                                "properties": {"message": {"type": "string", "description": "Question for the peer agent"}},
                                "required": ["message"],
                            },
                        },
                    })
                    peer_map[tool_name] = agent_name
                except:
                    pass
    except:
        pass
    return peer_tools, peer_map

async def ask_peer(agent_name, text):
    """Send an A2A message to a peer agent (looked up from registry)."""
    async with httpx.AsyncClient(verify=False, timeout=120) as http:
        # Look up peer URL from the Agent Registry
        r = await http.get(f"{REGISTRY_URL}/agents")
        peer_url = r.json().get(agent_name)
        if not peer_url:
            return f"Peer agent '{agent_name}' not found in registry"
        client = A2AClient(httpx_client=http, url=peer_url)
        req = SendMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(
                message=Message(
                    parts=[Part(root=TextPart(text=text))],
                    role=Role.user,
                    messageId=str(uuid4()),
                )
            ),
        )
        resp = await client.send_message(req, http_kwargs={"timeout": 120})
        try:
            result = resp.root.result
            # Task → text in status.message.parts
            if hasattr(result, "status") and result.status.message:
                return " ".join(
                    p.root.text for p in result.status.message.parts
                    if hasattr(p.root, "text")
                )
            # Message → text in result.parts
            if hasattr(result, "parts") and result.parts:
                return " ".join(
                    p.root.text for p in result.parts if hasattr(p.root, "text")
                )
        except:
            pass
        return str(resp)


# ─────────────────────────────────────────────────────────────
# SECTION 5: Agent Logic (runs when a message comes in)
#
# The brain of the HR Agent. Three steps:
#   Step 1 → Find MCP tools + find peer agents
#   Step 2 → GPT picks the right tool(s) — MCP, peer, or both
#   Step 3 → Run them: call MCP server and/or ask a peer via A2A
# ─────────────────────────────────────────────────────────────

class HRExecutor(AgentExecutor):

    async def execute(self, ctx: RequestContext, eq: EventQueue):

        # Setup A2A task tracking
        task = ctx.current_task or new_task(ctx.message)
        if not ctx.current_task:
            await eq.enqueue_event(task)
        updater = TaskUpdater(eq, task.id, task.context_id)
        query = ctx.get_user_input()
        print(f"\n  ┌─ [HR Agent] ══ A2A ══ Received: {query}")
        await _trace("HR Agent", "a2a_receive", f"Received: {query[:100]}")

        # Open ONE session to the HR MCP Server (file 1)
        async with sse_client("http://localhost:8010/sse") as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()

                # STEP 1: Discover MCP tools + discover peer agents
                mcp_tools = await session.list_tools()
                openai_tools = mcp_tools_to_openai(mcp_tools.tools)
                print(f"  │  [HR Agent] Discovered {len(openai_tools)} MCP tools")
                await _trace("HR Agent", "mcp_discover", f"Connected to MCP -- {len(openai_tools)} tools available")

                # ⭐ Discover peer agents from registry (no hardcoding!)
                peer_tools, peer_map = await discover_peers()
                openai_tools.extend(peer_tools)
                print(f"  │  [HR Agent] + {len(peer_tools)} peer(s) = {len(openai_tools)} total")
                await _trace("HR Agent", "info", f"Found {len(peer_tools)} peer agent(s) -- {len(openai_tools)} tools ready")

                # Build peer description for system prompt
                peer_desc = "; ".join(
                    f"{t['function']['name']}: {t['function']['description']}"
                    for t in peer_tools
                )

                # STEP 2 + 3: LLM picks tool(s) and we execute — loop until done
                msgs = [
                    {"role": "system", "content": (
                        "You are an HR assistant with access to HR tools AND peer agents. "
                        + (f"Peer agents available: {peer_desc}. "
                           "RULES: "
                           "1) For HR data (leave, payroll, employee info) -> call YOUR HR tools. "
                           "2) For non-HR data (IT assets, tickets) -> call the peer agent tool with a clear question including employee_id=EMP001. "
                           "3) For multi-domain queries -> call BOTH your HR tool AND the peer agent tool in the SAME response. Do NOT defer. "
                           "You CAN and MUST handle everything. Never say you cannot access something. " if peer_desc else "")
                        + "Default employee_id=EMP001."
                    )},
                    {"role": "user", "content": query},
                ]

                # Loop: keep calling tools until the LLM has no more tool_calls
                max_rounds = 5
                for _round in range(max_rounds):
                    response = await llm.chat.completions.create(
                        model=MODEL, messages=msgs, tools=openai_tools, tool_choice="auto"
                    )
                    msg = response.choices[0].message

                    if not msg.tool_calls:
                        reply = msg.content
                        if _round == 0:
                            await _trace("HR Agent", "llm", "LLM answering directly (no tools needed)")
                        break

                    await _trace("HR Agent", "llm", "LLM picked tool(s): " + ", ".join(tc.function.name for tc in msg.tool_calls))
                    msgs.append(msg)

                    for tc in msg.tool_calls:
                        args = json.loads(tc.function.arguments)

                        if tc.function.name in peer_map:
                            # PEER-TO-PEER A2A
                            peer_name = peer_map[tc.function.name]
                            peer_msg = args.get("message", query)
                            print(f"  │  ══ A2A PEER ══> {peer_name}: {peer_msg[:60]}")
                            await _trace("HR Agent", "peer_send", f"══> {peer_name}: {peer_msg[:80]}")
                            text = await ask_peer(peer_name, peer_msg)
                            print(f"  │  <══ A2A PEER ══ {peer_name}: {text[:60]}")
                            await _trace("HR Agent", "peer_receive", f"<══ {peer_name}: {text[:80]}")
                        else:
                            # MCP call to HR data server
                            print(f"  │  -- MCP --> {tc.function.name}({args})")
                            await _trace("HR Agent", "mcp_call", f"--> {tc.function.name}({args})")
                            result = await session.call_tool(tc.function.name, args)
                            text = result.content[0].text if result.content else "{}"
                            print(f"  │  <-- MCP -- {text[:80]}")
                            await _trace("HR Agent", "mcp_result", f"<-- {text[:100]}")

                        msgs.append({"role": "tool", "tool_call_id": tc.id, "content": text})
                else:
                    # Exhausted rounds — get final answer
                    final = await llm.chat.completions.create(model=MODEL, messages=msgs)
                    reply = final.choices[0].message.content

        # Return the answer via A2A (task → completed)
        print(f"  └─ [HR Agent] ══ A2A ══ Replied\n")
        await _trace("HR Agent", "a2a_reply", "Replied with response")
        await updater.update_status(
            state=TaskState.completed,
            message=new_agent_text_message(reply, task.context_id, task.id),
            final=True,
        )

    async def cancel(self, ctx, eq):
        raise ServerError(error=UnsupportedOperationError())


# ─────────────────────────────────────────────────────────────
# SECTION 6: Agent Card — this agent's "business card"
#
# Served at:  http://localhost:8001/.well-known/agent-card.json
#
# Other agents read this to learn:
#   - What this agent can do (skills)
#   - Where to reach it (URL)
#
# Try it: open the URL in your browser after starting!
# ─────────────────────────────────────────────────────────────

card = AgentCard(
    name="HR Agent",
    url="http://localhost:8001/",
    version="1.0.0",
    description="Handles leave and timesheets.",
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
    skills=[
        AgentSkill(
            id="leave",
            name="Leave Management",
            description="Check/apply leave",
            tags=["hr", "leave"],
            examples=["How many leaves do I have?"],
        ),
        AgentSkill(
            id="cats",
            name="CATS",
            description="Log hours & submit CATS",
            tags=["hr", "cats"],
            examples=["Log 8 hours on CATS"],
        ),
    ],
    capabilities=AgentCapabilities(streaming=False),
)


# ─────────────────────────────────────────────────────────────
# SECTION 7: Start the A2A Server
#
# A2AStarletteApplication handles the plumbing:
#   1. Serves the Agent Card at /.well-known/agent-card.json
#   2. Listens for incoming A2A messages
#   3. Sends each message to HRExecutor.execute()
# ─────────────────────────────────────────────────────────────

app = A2AStarletteApplication(
    agent_card=card,
    http_handler=DefaultRequestHandler(
        agent_executor=HRExecutor(),
        task_store=InMemoryTaskStore(),
    ),
).build()

if __name__ == "__main__":
    # Register with Agent Registry on startup
    try:
        httpx.post(f"{REGISTRY_URL}/register",
                   json={"name": card.name, "url": str(card.url)},
                   verify=False)
        print(f"  Registered with registry: {card.name}")
    except:
        print("  Warning: Registry offline (running standalone)")
    print("HR Agent running at http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")
