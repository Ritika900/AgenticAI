# ╔══════════════════════════════════════════════════════════╗
# ║  FILE 5: Orchestrator (A2A Server)                     ║
# ║  Run: python 5_Orchestrator_Client.py                  ║
# ║  Port: 8000                                            ║
# ╚══════════════════════════════════════════════════════════╝
#
#  WHAT:  A thin entry point that picks the best agent and forwards.
#         Agents handle cross-domain queries themselves via peer A2A.
#
#  FLOW:
#    User → Orchestrator → discovers all registered agents
#                        → GPT picks the BEST agent for the query
#                        → forwards the FULL query to that agent
#                        → that agent calls peers if needed
#
#  WHY NOT CENTRAL?
#  ┌─────────────────────────────────────────────────────┐
#  │  The Orchestrator is NOT a central controller.      │
#  │  It's just a "front door" that picks an agent.      │
#  │  Agents are smart peers — they call each other      │
#  │  directly via A2A when they need cross-domain data. │
#  └─────────────────────────────────────────────────────┘
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
# SECTION 1: A2A Imports
# ─────────────────────────────────────────────────────────────

from a2a.client import A2AClient            # ← send A2A messages
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater, InMemoryTaskStore
from a2a.types import (
    AgentCard, AgentSkill, AgentCapabilities,
    SendMessageRequest, MessageSendParams,
    Message, TextPart, Part, Role,
    TaskState, UnsupportedOperationError,
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
# SECTION 3: A2A Discovery
#
# Agents sign up at the registry when they start.
# The Orchestrator asks the registry who's online,
# then reads each agent's A2A card to learn what they do.
# Start a new agent → it registers itself → shows up here.
# ─────────────────────────────────────────────────────────────

async def discover(http):
    """Discover agents from the Agent Registry."""
    # Step 1: Get all registered agent URLs from registry
    try:
        r = await http.get(f"{REGISTRY_URL}/agents", timeout=5)
        all_agents = r.json()
    except:
        print("  Registry offline!")
        return []

    # Step 2: Fetch each agent's A2A card (standard A2A discovery)
    found = []
    for name, url in all_agents.items():
        if name == card.name:     # skip self
            continue
        try:
            response = await http.get(f"{url.rstrip('/')}/.well-known/agent-card.json", timeout=5)
            agent_card = AgentCard(**response.json())
            found.append((url, agent_card))
            print(f"  Found: {agent_card.name} at {url}")
        except:
            print(f"  Offline: {name} at {url}")
    return found


# ─────────────────────────────────────────────────────────────
# SECTION 4: Agent Cards → LLM Tools (your bridge logic)
#
# Turns each Agent Card into a tool GPT can pick from.
# GPT reads the skill names to decide which agent fits best.
# This is YOUR code, not A2A — A2A just gives you the cards.
# ─────────────────────────────────────────────────────────────

def make_tools(agents):
    """Turn Agent Cards into GPT tool definitions."""
    tools = []
    urls = {}
    for url, card in agents:
        name = f"ask_{card.name.lower().replace(' ', '_')}"
        desc = f"Talk to {card.name}: " + ", ".join(s.name for s in card.skills)

        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            },
        })
        urls[name] = url
    return tools, urls


# ─────────────────────────────────────────────────────────────
# SECTION 5: A2A Communication
#
# Sends a message to another agent and reads the reply.
# Under the hood it's a simple HTTP POST (JSON-RPC).
# Works with any A2A agent, no matter what language it's built in.
# ─────────────────────────────────────────────────────────────

def _extract_text(resp):
    """Extract text from an A2A response (handles both Task and Message types)."""
    try:
        result = resp.root.result
        # If result is a Message → text is in result.parts
        if hasattr(result, "parts") and result.parts:
            return " ".join(
                p.root.text for p in result.parts if hasattr(p.root, "text")
            )
        # If result is a Task → text is in result.status.message.parts
        if hasattr(result, "status") and result.status.message:
            return " ".join(
                p.root.text for p in result.status.message.parts
                if hasattr(p.root, "text")
            )
        # Fallback: check artifacts
        if hasattr(result, "artifacts") and result.artifacts:
            return " ".join(
                p.root.text
                for a in result.artifacts for p in a.parts
                if hasattr(p.root, "text")
            )
    except Exception:
        pass
    return str(resp)


async def ask_agent(http, url, text):
    """Send an A2A message to an agent and get the response."""
    client = A2AClient(httpx_client=http, url=url)

    # Build the A2A message
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

    # Send it and get the response
    resp = await client.send_message(req, http_kwargs={"timeout": 120})

    # Extract text from response (handles both Task and Message)
    return _extract_text(resp)


# ─────────────────────────────────────────────────────────────
# SECTION 6: Orchestrator Logic
#
# A simple forwarder — three steps:
#   1. Find agents from registry, read their Agent Cards
#   2. GPT picks the BEST agent for the query
#   3. Pass the FULL query to that agent via A2A
#      (the agent talks to peers itself if it needs more data)
# ─────────────────────────────────────────────────────────────

class OrchestratorExecutor(AgentExecutor):

    async def execute(self, ctx: RequestContext, eq: EventQueue):

        task = ctx.current_task or new_task(ctx.message)
        if not ctx.current_task:
            await eq.enqueue_event(task)
        updater = TaskUpdater(eq, task.id, task.context_id)
        query = ctx.get_user_input()
        print(f"\n  ┌─ [Orchestrator] Got: {query}")
        await _trace("Orchestrator", "receive", f"Query: {query[:100]}")

        async with httpx.AsyncClient(verify=False, timeout=120) as http:

            # ── STEP 1: Discover agents (A2A) ──
            print("  [Orchestrator] Discovering agents...")
            await _trace("Orchestrator", "discover", "Querying registry for agents...")
            agents = await discover(http)
            if not agents:
                await updater.update_status(
                    state=TaskState.completed,
                    message=new_agent_text_message("No agents online.", task.context_id, task.id),
                    final=True,
                )
                return

            # ══ STEP 2: LLM picks the BEST agent ══
            tools, urls = make_tools(agents)
            print(f"  │  [Orchestrator] LLM picking best agent...")
            await _trace("Orchestrator", "found", f"Found: {', '.join(c.name for _,c in agents)}")
            await _trace("Orchestrator", "llm", "LLM choosing best agent...")
            # Build agent description dynamically from discovered cards
            agent_desc = " | ".join(
                f"{c.name}: {', '.join(s.name for s in c.skills)}"
                for _, c in agents
            )
            msgs = [
                {"role": "system", "content": (
                    "You route queries to the best agent. Pick ONE agent. "
                    "Forward the FULL user query — the agent will handle "
                    "cross-domain needs by calling peer agents itself. "
                    f"Available agents: {agent_desc}"
                )},
                {"role": "user", "content": query},
            ]
            response = await llm.chat.completions.create(
                model=MODEL, messages=msgs, tools=tools, tool_choice="auto"
            )
            msg = response.choices[0].message

            # ══ STEP 3: Forward to chosen agent via A2A ══
            # Only use the FIRST tool call — one agent handles cross-domain
            # via its own peer-to-peer A2A capability
            if msg.tool_calls:
                tc = msg.tool_calls[0]
                # Rebuild the assistant message with only the first tool call
                # so the LLM never sees (or echoes) skipped tool calls
                msgs.append({"role": "assistant", "content": None,
                             "tool_calls": [{"id": tc.id, "type": "function",
                                             "function": {"name": tc.function.name,
                                                          "arguments": tc.function.arguments}}]})
                args = json.loads(tc.function.arguments)
                url = urls.get(tc.function.name)
                if not url:
                    reply = "Could not find the selected agent."
                else:
                    # Always forward the FULL original query, not the LLM's rewrite
                    sub_msg = query
                    print(f"  │  ══ A2A ══> {tc.function.name}: {sub_msg[:60]}")
                    await _trace("Orchestrator", "a2a_send", f"══> {tc.function.name}: {sub_msg[:80]}")

                    result = await ask_agent(http, url, sub_msg)
                    print(f"  │  <══ A2A ══ {tc.function.name}: {result[:60]}")
                    await _trace("Orchestrator", "a2a_receive", f"<══ {tc.function.name}: {result[:80]}")

                    msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})

                    # GPT formats the final response for the user
                    final = await llm.chat.completions.create(model=MODEL, messages=msgs)
                    reply = final.choices[0].message.content
            else:
                reply = msg.content

        print(f"  └─ [Orchestrator] Done\n")
        await _trace("Orchestrator", "done", "Returning final response")
        await updater.update_status(
            state=TaskState.completed,
            message=new_agent_text_message(reply, task.context_id, task.id),
            final=True,
        )

    async def cancel(self, ctx, eq):
        raise ServerError(error=UnsupportedOperationError())


# ─────────────────────────────────────────────────────────────
# SECTION 7: Agent Card — the Orchestrator's "business card"
#
# The Orchestrator is itself an A2A agent with its own card.
# Served at:  http://localhost:8000/.well-known/agent-card.json
# ─────────────────────────────────────────────────────────────

card = AgentCard(
    name="Smart Office Orchestrator",
    url="http://localhost:8000/",
    version="1.0.0",
    description="Thin entry point. Picks the best agent and forwards queries.",
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
    skills=[
        AgentSkill(
            id="router",
            name="Smart Router",
            description="Routes to the best agent",
            tags=["router"],
            examples=["Check my leave and show IT assets"],
        ),
    ],
    capabilities=AgentCapabilities(streaming=False),
)

app = A2AStarletteApplication(
    agent_card=card,
    http_handler=DefaultRequestHandler(
        agent_executor=OrchestratorExecutor(),
        task_store=InMemoryTaskStore(),
    ),
).build()


# ─────────────────────────────────────────────────────────────
# SECTION 8: Entry Point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Register with Agent Registry on startup
    try:
        httpx.post(f"{REGISTRY_URL}/register",
                   json={"name": card.name, "url": str(card.url)},
                   verify=False)
        print(f"  Registered with registry: {card.name}")
    except:
        print("  Warning: Registry offline (running standalone)")
    print("Orchestrator running at http://localhost:8000")
    print("Test UI at registry:  http://localhost:9000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
