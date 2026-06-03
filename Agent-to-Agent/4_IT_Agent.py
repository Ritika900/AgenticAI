# ╔══════════════════════════════════════════════════════════╗
# ║  FILE 4: IT Agent (A2A Server)                         ║
# ║  Run: python 4_IT_Agent.py                             ║
# ║  Port: 8002                                            ║
# ╚══════════════════════════════════════════════════════════╝
#
#  Same pattern as File 3 (HR Agent), just different data.
#  Both agents are peers — each can talk to the other via A2A.
#
#  FLOW:  Anyone --A2A--> IT Agent --MCP--> IT MCP Server
#                         IT Agent --A2A--> peer agents (via registry)
#
# ─────────────────────────────────────────────────────────────

import os, json, uvicorn, httpx
import warnings
warnings.filterwarnings("ignore", message="A2AClient is deprecated")
from dotenv import load_dotenv
load_dotenv()

from uuid import uuid4
from openai import AsyncAzureOpenAI


# ─────────────────────────────────────────────────────────────
# SECTION 1: A2A & MCP Imports
# ─────────────────────────────────────────────────────────────

from mcp import ClientSession
from mcp.client.sse import sse_client

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater, InMemoryTaskStore
from a2a.client import A2AClient            # ← for peer-to-peer A2A calls
from a2a.types import (
    AgentCard, AgentSkill, AgentCapabilities,
    TaskState, UnsupportedOperationError,
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
# SECTION 3: MCP → OpenAI Tool Converter (same as File 3)
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
# SECTION 4: Peer Discovery + A2A (same as File 3)
#
# Asks the registry: "Who else is running?"
# Reads each peer's Agent Card to learn what they can do.
# Turns those cards into tools GPT can call.
# ─────────────────────────────────────────────────────────────

MY_NAME = "IT Support Agent"

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
            if hasattr(result, "status") and result.status.message:
                return " ".join(
                    p.root.text for p in result.status.message.parts
                    if hasattr(p.root, "text")
                )
            if hasattr(result, "parts") and result.parts:
                return " ".join(
                    p.root.text for p in result.parts if hasattr(p.root, "text")
                )
        except:
            pass
        return str(resp)


# ─────────────────────────────────────────────────────────────
# SECTION 5: Agent Logic (same pattern as File 3)
#
#   Step 1 → Find MCP tools + find peer agents
#   Step 2 → GPT picks the right tool(s) — MCP, peer, or both
#   Step 3 → Run them: call MCP server and/or ask a peer via A2A
# ─────────────────────────────────────────────────────────────

class ITExecutor(AgentExecutor):

    async def execute(self, ctx: RequestContext, eq: EventQueue):

        task = ctx.current_task or new_task(ctx.message)
        if not ctx.current_task:
            await eq.enqueue_event(task)
        updater = TaskUpdater(eq, task.id, task.context_id)
        query = ctx.get_user_input()
        print(f"\n  ┌─ [IT Agent] ══ A2A ══ Received: {query}")
        await _trace("IT Agent", "a2a_receive", f"Received: {query[:100]}")

        # Open ONE session to the IT MCP Server (file 2)
        async with sse_client("http://localhost:8011/sse") as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()

                # STEP 1: Discover MCP tools + discover peer agents
                mcp_tools = await session.list_tools()
                openai_tools = mcp_tools_to_openai(mcp_tools.tools)
                print(f"  │  [IT Agent] Discovered {len(openai_tools)} MCP tools")
                await _trace("IT Agent", "mcp_discover", f"Connected to MCP -- {len(openai_tools)} tools available")

                # ⭐ Discover peer agents from registry (no hardcoding!)
                peer_tools, peer_map = await discover_peers()
                openai_tools.extend(peer_tools)
                print(f"  │  [IT Agent] + {len(peer_tools)} peer(s) = {len(openai_tools)} total")
                await _trace("IT Agent", "info", f"Found {len(peer_tools)} peer agent(s) -- {len(openai_tools)} tools ready")

                # Build peer description for system prompt
                peer_desc = "; ".join(
                    f"{t['function']['name']}: {t['function']['description']}"
                    for t in peer_tools
                )

                # STEP 2 + 3: LLM picks tool(s) and we execute — loop until done
                msgs = [
                    {"role": "system", "content": (
                        "You are an IT Support assistant with access to IT tools AND peer agents. "
                        + (f"Peer agents available: {peer_desc}. "
                           "RULES: "
                           "1) For IT data (assets, tickets) -> call YOUR IT tools. "
                           "2) For non-IT data (leave, payroll, employee info) -> call the peer agent tool with a clear question including employee_id=EMP001. "
                           "3) For multi-domain queries -> call BOTH your IT tool AND the peer agent tool in the SAME response. Do NOT defer. "
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
                            await _trace("IT Agent", "llm", "LLM answering directly (no tools needed)")
                        break

                    await _trace("IT Agent", "llm", "LLM picked tool(s): " + ", ".join(tc.function.name for tc in msg.tool_calls))
                    msgs.append(msg)

                    for tc in msg.tool_calls:
                        args = json.loads(tc.function.arguments)

                        if tc.function.name in peer_map:
                            # PEER-TO-PEER A2A
                            peer_name = peer_map[tc.function.name]
                            peer_msg = args.get("message", query)
                            print(f"  │  ══ A2A PEER ══> {peer_name}: {peer_msg[:60]}")
                            await _trace("IT Agent", "peer_send", f"══> {peer_name}: {peer_msg[:80]}")
                            text = await ask_peer(peer_name, peer_msg)
                            print(f"  │  <══ A2A PEER ══ {peer_name}: {text[:60]}")
                            await _trace("IT Agent", "peer_receive", f"<══ {peer_name}: {text[:80]}")
                        else:
                            # MCP call to IT data server
                            print(f"  │  -- MCP --> {tc.function.name}({args})")
                            await _trace("IT Agent", "mcp_call", f"--> {tc.function.name}({args})")
                            result = await session.call_tool(tc.function.name, args)
                            text = result.content[0].text if result.content else "{}"
                            print(f"  │  <-- MCP -- {text[:80]}")
                            await _trace("IT Agent", "mcp_result", f"<-- {text[:100]}")

                        msgs.append({"role": "tool", "tool_call_id": tc.id, "content": text})
                else:
                    # Exhausted rounds — get final answer
                    final = await llm.chat.completions.create(model=MODEL, messages=msgs)
                    reply = final.choices[0].message.content

        print(f"  └─ [IT Agent] ══ A2A ══ Replied\n")
        await _trace("IT Agent", "a2a_reply", "Replied with response")
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
# Served at:  http://localhost:8002/.well-known/agent-card.json
# ─────────────────────────────────────────────────────────────

card = AgentCard(
    name="IT Support Agent",
    url="http://localhost:8002/",
    version="1.0.0",
    description="Handles IT tickets and asset lookups.",
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
    skills=[
        AgentSkill(
            id="ticket",
            name="IT Tickets",
            description="Raise/check tickets",
            tags=["it", "ticket"],
            examples=["My laptop won't connect to WiFi"],
        ),
        AgentSkill(
            id="assets",
            name="IT Assets",
            description="List assigned assets",
            tags=["it", "assets"],
            examples=["What laptop am I assigned?"],
        ),
    ],
    capabilities=AgentCapabilities(streaming=False),
)


# ─────────────────────────────────────────────────────────────
# SECTION 7: Start the A2A Server
# ─────────────────────────────────────────────────────────────

app = A2AStarletteApplication(
    agent_card=card,
    http_handler=DefaultRequestHandler(
        agent_executor=ITExecutor(),
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
    print("IT Agent running at http://localhost:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="warning")
