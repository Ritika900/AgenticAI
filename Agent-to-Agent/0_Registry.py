# ============================================================
#   FILE 0: Agent Registry                                
#   Run FIRST: python 0_Registry.py                       
#   Port: 9000                                            
# ============================================================
#
#  WHAT:  A central phone book for all agents.
#         Every agent registers here on startup.
#         Others look up agent URLs from here.
#
#  WHY:   Without a registry, every agent needs to know
#         every other agent's URL. Add a new agent?
#         You'd have to edit every file.
#         With a registry, agents only need ONE address.
#
#  API:
#    POST /register    ->  {"name": "HR Agent", "url": "http://..."}
#    GET  /agents      ->  {"HR Agent": "http://...", ...}
#    POST /trace       ->  agents push trace events here
#    GET  /trace       ->  UI fetches trace events
#    DELETE /trace     ->  clear trace buffer
#    POST /query       ->  forward query to agent via A2A
#    GET  /            ->  dashboard UI
#    GET  /agent-card  ->  proxy to agent's /.well-known/agent-card.json
#
#  START ORDER:
#    0_Registry -> 1_HR_MCP -> 2_IT_MCP -> 3_HR_Agent -> 4_IT_Agent -> 5_Orchestrator
#
# -------------------------------------------------------------

import uvicorn, httpx, time
from uuid import uuid4
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse


# -------------------------------------------------------------
# SECTION 1: In-Memory Storage
# -------------------------------------------------------------

# Agent registry -- maps agent name -> URL
# Example: {"HR Agent": "http://localhost:8001", ...}
registry = {}

# Trace buffer -- agents push events here, UI polls to display
trace_events = []


# -------------------------------------------------------------
# SECTION 2: API Endpoints
# -------------------------------------------------------------

async def register(request: Request):
    """Agent calls this on startup to register itself."""
    data = await request.json()
    name = data["name"]
    url = data["url"]
    registry[name] = url
    print(f"  [OK] Registered: {name} -> {url}")
    return JSONResponse({"status": "ok", "name": name})


async def list_agents(request: Request):
    """Return all registered agents."""
    return JSONResponse(registry)


# -------------------------------------------------------------
# SECTION 3: Trace Buffer
#
# Agents send status updates here as they work.
# The dashboard checks this regularly to show a live timeline.
# -------------------------------------------------------------

async def trace_handler(request: Request):
    """POST = push event, GET = read all events, DELETE = clear."""
    if request.method == "POST":
        event = await request.json()
        event["ts"] = time.time()
        trace_events.append(event)
        return JSONResponse({"status": "ok"})
    elif request.method == "DELETE":
        trace_events.clear()
        return JSONResponse({"status": "cleared"})
    return JSONResponse(trace_events)


# -------------------------------------------------------------
# SECTION 4: Query Proxy
#
# The dashboard sends user queries here.
# Picks the right agent, or defaults to the Orchestrator.
# Talks to agents using plain HTTP POST (no SDK needed).
# -------------------------------------------------------------

ORCHESTRATOR_NAME = "Smart Office Orchestrator"

async def query_agent(request: Request):
    """Forward a query via A2A. If agent specified, send direct; otherwise use Orchestrator."""
    data = await request.json()
    message = data["message"]
    agent_name = data.get("agent", ORCHESTRATOR_NAME)

    url = registry.get(agent_name)
    if not url:
        return JSONResponse({"error": f"Agent '{agent_name}' not registered. Start it first!"}, status_code=404)

    # Send A2A JSON-RPC message/send
    msg_id = str(uuid4())
    payload = {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": message}],
            }
        },
    }
    try:
        async with httpx.AsyncClient(verify=False, timeout=120) as http:
            resp = await http.post(url, json=payload)
            result = resp.json()

            # Extract text from A2A response
            r = result.get("result", {})
            # Task response -> status.message.parts
            parts = (r.get("status", {}).get("message", {}) or {}).get("parts", [])
            # Message response -> result.parts
            if not parts:
                parts = r.get("parts", [])
            text = " ".join(p.get("text", "") for p in parts if p.get("kind") == "text" or "text" in p)
            return JSONResponse({"response": text or str(result)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# -------------------------------------------------------------
# SECTION 5: Dashboard UI
# -------------------------------------------------------------

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Smart Office &mdash; Multi-Agent System</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#06090f;color:#c9d1d9;min-height:100vh}

/* â”€â”€ Topbar â”€â”€ */
.topbar{background:linear-gradient(90deg,#0d1117,#161b22);border-bottom:1px solid #21262d;padding:14px 28px;display:flex;align-items:center;gap:14px}
.topbar-icon{width:34px;height:34px;background:linear-gradient(135deg,#58a6ff,#bc8cff);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:17px}
.topbar h1{font-size:16px;font-weight:600;color:#e6edf3}
.topbar .sep{color:#30363d;font-size:14px}
.topbar .sub{font-size:13px;color:#8b949e;font-weight:400}
.topbar-right{margin-left:auto;display:flex;align-items:center;gap:12px}
.badge{font-size:10px;padding:3px 10px;border-radius:99px;font-weight:600;border:1px solid #21262d;background:#161b22;color:#8b949e;display:flex;align-items:center;gap:5px}
.badge .dot{width:6px;height:6px;border-radius:50%;background:#3fb950;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}

.layout{display:grid;grid-template-columns:300px 1fr;grid-template-rows:auto 1fr;height:calc(100vh - 63px);overflow:hidden}

/* â”€â”€ Left Sidebar â”€â”€ */
.sidebar{grid-row:1/3;background:#0d1117;border-right:1px solid #21262d;display:flex;flex-direction:column;overflow-y:auto}
.sb-section{padding:16px}
.sb-title{font-size:10px;font-weight:700;color:#484f58;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.sb-title .cnt{background:#21262d;color:#8b949e;border-radius:99px;padding:0 7px;font-size:9px;line-height:18px}

/* Agent list */
.agent-item{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:10px 12px;margin-bottom:8px;transition:border-color .2s;cursor:pointer}
.agent-item:hover{border-color:#58a6ff}

/* Agent Card Modal */
.ac-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100;display:none;align-items:center;justify-content:center}
.ac-overlay.open{display:flex}
.ac-modal{background:#161b22;border:1px solid #30363d;border-radius:12px;width:520px;max-width:90vw;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 16px 48px rgba(0,0,0,.4)}
.ac-hdr{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid #21262d}
.ac-hdr-title{font-size:13px;font-weight:700;color:#e6edf3;flex:1}
.ac-hdr .ac-close{background:none;border:none;color:#8b949e;font-size:18px;cursor:pointer;padding:4px 8px;border-radius:6px}
.ac-hdr .ac-close:hover{color:#e6edf3;background:#21262d}
.ac-body{padding:16px 18px;overflow-y:auto;flex:1}
.ac-body pre{font-family:'Cascadia Code','Fira Code',monospace;font-size:11px;color:#c9d1d9;white-space:pre-wrap;word-break:break-word;line-height:1.6;margin:0}
.ac-loading{color:#484f58;font-size:12px;text-align:center;padding:30px}
.agent-top{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.agent-icon{width:26px;height:26px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0}
.agent-icon.hr{background:rgba(63,185,80,.12)}
.agent-icon.it{background:rgba(88,166,255,.12)}
.agent-icon.orch{background:rgba(188,140,255,.12)}
.agent-icon.other{background:rgba(210,153,34,.12)}
.agent-nm{font-size:12px;font-weight:600;color:#e6edf3;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.agent-status{font-size:9px;font-weight:700;padding:2px 7px;border-radius:99px;text-transform:uppercase;letter-spacing:.3px}
.agent-status.on{background:rgba(63,185,80,.12);color:#3fb950}
.agent-status.off{background:rgba(248,81,73,.1);color:#f85149}
.agent-url{font-size:10px;color:#484f58;font-family:'Cascadia Code','Fira Code',monospace}
.agent-skills{display:flex;flex-wrap:wrap;gap:3px;margin-top:5px}
.skill{font-size:9px;background:#21262d;color:#8b949e;padding:2px 7px;border-radius:99px}
.no-agents{color:#484f58;font-size:12px;text-align:center;padding:20px}

/* Test Scenarios */
.test-card{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:9px 12px;cursor:pointer;transition:all .15s;display:flex;align-items:center;gap:8px;margin-bottom:6px}
.test-card:hover{border-color:#58a6ff;background:#161b2e}
.test-card.active{border-color:#58a6ff;background:#161b2e}
.test-em{font-size:14px;flex-shrink:0}
.test-card>div{min-width:0;overflow:hidden}
.test-txt{font-size:11px;color:#8b949e;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.test-card:hover .test-txt{color:#c9d1d9}
.test-lbl{font-size:9px;color:#484f58;text-transform:uppercase;letter-spacing:.5px;font-weight:700}

/* Register form */
.reg-form{display:flex;flex-direction:column;gap:6px}
.reg-row{display:flex;gap:6px}
.reg-row input{flex:1;background:#0d1117;color:#c9d1d9;border:1px solid #21262d;border-radius:6px;padding:6px 10px;font-size:11px;outline:none}
.reg-row input:focus{border-color:#58a6ff}
.btn-reg{background:#238636;color:#fff;border:none;border-radius:6px;padding:6px 14px;font-size:11px;font-weight:600;cursor:pointer}
.btn-reg:hover{background:#2ea043}
.reg-msg{font-size:10px;min-height:14px}

/* â”€â”€ Top area: Flow Diagram â”€â”€ */
.flow-area{background:#0d1117;border-bottom:1px solid #21262d;padding:20px 28px;position:relative;overflow:hidden;min-height:220px}
.flow-title{font-size:10px;font-weight:700;color:#484f58;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:14px}

/* SVG Flow Canvas */
.flow-canvas{width:100%;height:180px;position:relative}
.flow-canvas svg{width:100%;height:100%}
.flow-node{cursor:default}
.flow-node rect{rx:10;ry:10;stroke-width:1.5;transition:all .3s}
.flow-node text{font-family:'Segoe UI',system-ui,sans-serif;font-weight:600;fill:#e6edf3}
.flow-node .fn-sub{font-weight:400;fill:#8b949e}
.flow-node.active rect{filter:drop-shadow(0 0 8px rgba(88,166,255,.4))}
.flow-arrow{stroke-width:2;fill:none;opacity:0;transition:opacity .4s}
.flow-arrow.visible{opacity:.35}
.flow-arrow.active{opacity:1}
.flow-arrow.active.rev{opacity:.7;stroke-dasharray:3 4}
.flow-arrow.a2a{stroke:#bc8cff}
.flow-arrow.mcp{stroke:#f0883e}
.flow-arrow.peer{stroke:#d2a8ff}
.flow-arrow.fwd{marker-end:url(#ah-a2a)}
.flow-arrow.fwd.mcp{marker-end:url(#ah-mcp)}
.flow-arrow.fwd.peer{marker-end:url(#ah-peer)}
.flow-arrow.rev{marker-start:url(#ah-a2a-rev)}
.flow-arrow.rev.mcp{marker-start:url(#ah-mcp-rev)}
.flow-arrow.rev.peer{marker-start:url(#ah-peer-rev)}
.flow-arrow.active.a2a{stroke-dasharray:8 4;animation:flowDash .8s linear infinite}
.flow-arrow.active.mcp{stroke-dasharray:6 4;animation:flowDash .6s linear infinite}
.flow-arrow.active.peer{stroke-dasharray:5 5;animation:flowDash 1s linear infinite}
@keyframes flowDash{to{stroke-dashoffset:-12}}
.flow-label{font-family:'Cascadia Code',monospace;font-size:9px;fill:#8b949e;opacity:0;transition:opacity .3s}
.flow-label.visible{opacity:1}
.flow-step{font-family:'Segoe UI',sans-serif;font-size:8px;font-weight:700;fill:#fff}
.flow-step-bg{rx:7;ry:7}
.flow-legend{display:flex;gap:16px;position:absolute;bottom:6px;left:28px;z-index:5}
.flow-legend-item{display:flex;align-items:center;gap:5px;font-size:10px;color:#8b949e}
.flow-legend-item .swatch{width:18px;height:3px;border-radius:2px}

/* â”€â”€ Bottom area: Chat + Trace Timeline â”€â”€ */
.main-area{display:grid;grid-template-columns:1fr 1fr;gap:0;overflow:hidden}
.panel{display:flex;flex-direction:column;overflow:hidden}
.panel+.panel{border-left:1px solid #21262d}
.panel-hdr{background:#161b22;padding:8px 16px;border-bottom:1px solid #21262d;display:flex;align-items:center;gap:10px;flex-shrink:0}
.panel-hdr-title{font-size:11px;font-weight:600;color:#8b949e;flex:1}
.panel-hdr select{background:#0d1117;color:#c9d1d9;border:1px solid #21262d;border-radius:5px;padding:3px 8px;font-size:11px;outline:none}
.panel-hdr .btn-s{background:#21262d;color:#8b949e;border:none;border-radius:5px;padding:3px 10px;font-size:10px;font-weight:600;cursor:pointer}
.panel-hdr .btn-s:hover{color:#c9d1d9;background:#30363d}

/* Chat */
.chat-body{flex:1;padding:14px 16px;overflow-y:auto;display:flex;flex-direction:column;gap:8px}
.msg{max-width:80%;padding:9px 13px;border-radius:12px;font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-word;animation:fadeUp .2s ease-out}
@keyframes fadeUp{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
.msg.user{background:#1f6feb;color:#fff;align-self:flex-end;border-bottom-right-radius:4px}
.msg.agent{background:#161b22;border:1px solid #21262d;color:#c9d1d9;align-self:flex-start;border-bottom-left-radius:4px}
.msg.error{background:rgba(248,81,73,.08);border:1px solid rgba(248,81,73,.2);color:#ffa198;align-self:flex-start}
.msg.thinking{color:#484f58;font-style:italic;align-self:flex-start;background:transparent}
.chat-placeholder{text-align:center;color:#30363d;font-size:11px;padding:40px 20px;line-height:1.8}
.chat-input{display:flex;border-top:1px solid #21262d;flex-shrink:0}
.chat-input input{flex:1;background:#0d1117;color:#c9d1d9;border:none;padding:12px 16px;font-size:12px;outline:none}
.chat-input input::placeholder{color:#30363d}
.chat-input button{background:#1f6feb;color:#fff;border:none;padding:12px 18px;font-size:12px;font-weight:600;cursor:pointer}
.chat-input button:hover{background:#388bfd}
.chat-input button:disabled{background:#21262d;color:#484f58;cursor:not-allowed}

/* â”€â”€ Trace Timeline â”€â”€ */
.trace-body{flex:1;padding:0;overflow-y:auto}
.trace-empty{color:#30363d;text-align:center;padding:40px 20px;font-size:11px;line-height:2}
.tl-event{display:flex;align-items:stretch;padding:0 16px;animation:fadeUp .15s ease-out}
.tl-event.child{opacity:.75}
.tl-event.child .tl-left{border-right-style:dashed}
.tl-event.child .tl-left::after{width:6px;height:6px;top:13px}
.tl-event.child .tl-step{width:14px;height:14px;line-height:14px;font-size:7px}
.tl-event.child .tl-right{padding-left:32px}
.tl-event.child .tl-msg{font-size:10px}
.tl-left{width:90px;flex-shrink:0;display:flex;flex-direction:column;align-items:flex-end;padding:8px 12px 8px 0;border-right:2px solid #21262d;position:relative}
.tl-left::after{content:'';position:absolute;right:-5px;top:12px;width:8px;height:8px;border-radius:50%;border:2px solid #21262d;background:#0d1117}
.tl-step{display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;border-radius:50%;font-size:9px;font-weight:700;color:#fff;margin-bottom:2px}
.tl-step.s-a2a{background:#bc8cff}
.tl-step.s-mcp{background:#f0883e}
.tl-step.s-peer{background:#d2a8ff}
.tl-step.s-llm{background:#8b949e}
.tl-step.s-info{background:#30363d}
.tl-src{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.3px}
.tl-src.orchestrator{color:#bc8cff}
.tl-src.hr{color:#3fb950}
.tl-src.it{color:#58a6ff}
.tl-right{flex:1;padding:6px 0 6px 16px;min-height:32px;display:flex;align-items:center}
.tl-content{font-size:11px;color:#8b949e;display:flex;align-items:center;gap:6px}
.tl-icon{font-size:12px;flex-shrink:0}
.tl-msg{flex:1}

/* Event type coloring */
.tl-event.t-a2a .tl-left::after{border-color:#bc8cff;background:#bc8cff}
.tl-event.t-a2a .tl-left{border-right-color:#bc8cff}
.tl-event.t-mcp .tl-left::after{border-color:#f0883e;background:#f0883e}
.tl-event.t-mcp .tl-left{border-right-color:#f0883e}
.tl-event.t-peer .tl-left::after{border-color:#d2a8ff;background:#d2a8ff}
.tl-event.t-peer .tl-left{border-right-color:#d2a8ff}
.tl-event.t-llm .tl-left::after{border-color:#8b949e;background:#8b949e}
.tl-event.t-llm .tl-left{border-right-color:#8b949e}
.tl-event.t-info .tl-left::after{border-color:#30363d;background:#30363d}

/* A2A send/receive gets highlighted detail */
.tl-event.t-a2a .tl-msg{color:#d2a8ff}
.tl-event.t-mcp .tl-msg{color:#f0883e}
.tl-event.t-peer .tl-msg{color:#d2a8ff}
</style>
</head>
<body>

<!-- SVG marker defs are now created dynamically inside the flow SVG -->

<div class="topbar">
  <div class="topbar-icon">&#x26a1;</div>
  <h1>Smart Office</h1>
  <span class="sep">|</span>
  <span class="sub">Multi-Agent System</span>
  <div class="topbar-right">
    <div class="badge"><span class="dot"></span> Registry</div>
  </div>
</div>

<div class="layout">
  <!-- â”€â”€ LEFT SIDEBAR â”€â”€ -->
  <div class="sidebar">
    <div class="sb-section">
      <div class="sb-title">Agents <span class="cnt" id="agent-count">0</span></div>
      <div id="agents-list"><div class="no-agents">No agents yet. Start your services.</div></div>
    </div>
    <div class="sb-section" style="border-top:1px solid #21262d">
      <div class="sb-title">Test Scenarios</div>
      <div class="test-card" onclick="runTest(this,0)"><span class="test-em">&#x1f4cb;</span><div><div class="test-lbl">HR Only</div><div class="test-txt">How many casual leaves do I have left?</div></div></div>
      <div class="test-card" onclick="runTest(this,1)"><span class="test-em">&#x1f4bb;</span><div><div class="test-lbl">IT Only</div><div class="test-txt">What laptop am I assigned?</div></div></div>
      <div class="test-card" onclick="runTest(this,2)"><span class="test-em">&#x1f500;</span><div><div class="test-lbl">HR &#x2192; IT</div><div class="test-txt">Check my leave balance and also show my IT assets</div></div></div>
      <div class="test-card" onclick="runTest(this,3)"><span class="test-em">&#x1f504;</span><div><div class="test-lbl">IT &#x2192; HR</div><div class="test-txt">What are my IT assets and how many leaves do I have?</div></div></div>
      <div class="test-card" onclick="runTest(this,4)"><span class="test-em">&#x2b50;</span><div><div class="test-lbl">Workflow</div><div class="test-txt">Apply 2 days sick leave from 2024-05-10 to 2024-05-11</div></div></div>
    </div>
    <div class="sb-section" style="border-top:1px solid #21262d">
      <div class="sb-title">Register Agent</div>
      <div class="reg-form">
        <div class="reg-row"><input id="reg-name" placeholder="Name" /><input id="reg-url" placeholder="http://localhost:8003" /></div>
        <div class="reg-row"><button class="btn-reg" onclick="registerAgent()">Register</button></div>
        <div class="reg-msg" id="reg-msg"></div>
      </div>
    </div>
  </div>

  <!-- â”€â”€ FLOW DIAGRAM â”€â”€ -->
  <div class="flow-area">
    <div class="flow-title">Live Agent Communication Flow</div>
    <div class="flow-canvas" id="flow-canvas">
      <svg id="flow-svg" viewBox="0 0 800 170"></svg>
    </div>
  </div>

  <!-- â”€â”€ CHAT + TRACE â”€â”€ -->
  <div class="main-area">
    <div class="panel">
      <div class="panel-hdr">
        <span class="panel-hdr-title">Chat</span>
        <select id="agent-select"><option value="">Loading...</option></select>
      </div>
      <div class="chat-body" id="chat-messages">
        <div class="chat-placeholder">Select an agent and type a query,<br>or click a test scenario to start.</div>
      </div>
      <div class="chat-input">
        <input type="text" id="chat-input" placeholder="Type a query..." autocomplete="off" />
        <button id="send-btn" onclick="sendQuery()">Send</button>
      </div>
    </div>
    <div class="panel">
      <div class="panel-hdr">
        <span class="panel-hdr-title">Trace Timeline</span>
        <button class="btn-s" onclick="clearTrace()">Clear</button>
      </div>
      <div class="trace-body" id="trace-body">
        <div class="trace-empty">Send a query to see the full<br>agent communication timeline here.<br><br><span style="color:#484f58">Orchestrator &#8594; Agent &#8594; MCP &#8594; Peer A2A</span></div>
      </div>
    </div>
  </div>
</div>

<script>
const TESTS = [
  "How many casual leaves do I have left?",
  "What laptop am I assigned?",
  "Check my leave balance and also show my IT assets",
  "What are my IT assets and how many leaves do I have?",
  "Apply 2 days sick leave from 2024-05-10 to 2024-05-11",
];

// â”€â”€ Helpers â”€â”€
function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML}
function agentType(n){const s=n.toLowerCase();if(s.includes("hr"))return"hr";if(s.includes("it"))return"it";if(s.includes("orchestrator"))return"orch";return"other"}
const AGENT_ICONS={hr:"\\ud83d\\udc65",it:"\\ud83d\\udcbb",orch:"\\u26a1",other:"\\ud83e\\udd16"};

// â”€â”€ Flow Diagram State â”€â”€
let flowNodes = {};  // name -> {x,y,w,h,type}
let flowArrows = []; // [{from,to,cls,label,el,labelEl}]
let activeNodes = new Set();

function buildFlowDiagram(agents) {
  const svg = document.getElementById("flow-svg");
  svg.innerHTML = "";
  flowNodes = {};
  flowArrows = [];
  activeNodes.clear();

  const names = Object.keys(agents);
  if (names.length === 0) {
    svg.setAttribute("viewBox","0 0 800 170");
    svg.innerHTML = '<text x="400" y="85" text-anchor="middle" fill="#30363d" font-size="12" font-family="Segoe UI">Start agents to see the flow diagram</text>';
    return;
  }

  // -- Create SVG marker defs (fwd + reverse arrowheads inside same SVG) --
  const defs = document.createElementNS("http://www.w3.org/2000/svg","defs");
  const markerCfg = {"ah-a2a":"#bc8cff","ah-mcp":"#f0883e","ah-peer":"#d2a8ff"};
  for (const [id,color] of Object.entries(markerCfg)) {
    // Forward arrowhead (at end)
    const mf = document.createElementNS("http://www.w3.org/2000/svg","marker");
    mf.setAttribute("id",id); mf.setAttribute("markerWidth","10"); mf.setAttribute("markerHeight","8");
    mf.setAttribute("refX","9"); mf.setAttribute("refY","4"); mf.setAttribute("orient","auto");
    mf.setAttribute("markerUnits","userSpaceOnUse");
    const pf = document.createElementNS("http://www.w3.org/2000/svg","polygon");
    pf.setAttribute("points","0 1, 10 4, 0 7"); pf.setAttribute("fill",color);
    mf.appendChild(pf); defs.appendChild(mf);
    // Reverse arrowhead (at start, pointing backwards)
    const mr = document.createElementNS("http://www.w3.org/2000/svg","marker");
    mr.setAttribute("id",id+"-rev"); mr.setAttribute("markerWidth","10"); mr.setAttribute("markerHeight","8");
    mr.setAttribute("refX","1"); mr.setAttribute("refY","4"); mr.setAttribute("orient","auto");
    mr.setAttribute("markerUnits","userSpaceOnUse");
    const pr = document.createElementNS("http://www.w3.org/2000/svg","polygon");
    pr.setAttribute("points","10 1, 0 4, 10 7"); pr.setAttribute("fill",color);
    mr.appendChild(pr); defs.appendChild(mr);
  }
  svg.appendChild(defs);

  // -- Layout calculation --
  const nodeW = 130, nodeH = 46, pad = 20;
  const orchIdx = names.findIndex(n => n.toLowerCase().includes("orchestrator"));
  const agentNames = names.filter((_,i) => i !== orchIdx);

  // User node (virtual)
  flowNodes["User"] = {x:pad, y:0, w:70, h:40, type:"user"};

  // Orchestrator
  const orchName = orchIdx >= 0 ? names[orchIdx] : null;
  if (orchName) flowNodes[orchName] = {x:160, y:0, w:nodeW+10, h:nodeH, type:"orch"};

  // Agent nodes
  const agentX = 420;
  const gapY = Math.max(16, Math.min(34, 80 / agentNames.length));
  const totalH = agentNames.length * nodeH + (agentNames.length - 1) * gapY;
  const agentStartY = pad;
  agentNames.forEach((name, i) => {
    flowNodes[name] = {x:agentX, y:agentStartY + i * (nodeH + gapY), w:nodeW, h:nodeH, type:agentType(name)};
  });

  // MCP server nodes (virtual, next to agents)
  const mcpX = 660;
  agentNames.forEach(name => {
    const tp = agentType(name);
    const mName = tp === "hr" ? "HR MCP" : tp === "it" ? "IT MCP" : name + " MCP";
    flowNodes[mName] = {x:mcpX, y:flowNodes[name].y, w:100, h:nodeH, type:"mcp"};
  });

  // Center User & Orchestrator vertically relative to agents
  const agentMidY = agentStartY + totalH / 2 - nodeH / 2;
  flowNodes["User"].y = agentMidY + (nodeH - 40) / 2;
  if (orchName) flowNodes[orchName].y = agentMidY;

  // -- Dynamic viewBox --
  let maxX = 0, maxY = 0;
  for (const n of Object.values(flowNodes)) { maxX = Math.max(maxX, n.x + n.w); maxY = Math.max(maxY, n.y + n.h); }
  svg.setAttribute("viewBox", `0 0 ${maxX + pad*2} ${maxY + pad*2}`);

  // -- Colors --
  const fills   = {user:"#161b22",orch:"#1c1432",hr:"#0d2818",it:"#0d1f30",mcp:"#1a1610",other:"#1a1a10"};
  const strokes = {user:"#30363d",orch:"#bc8cff",hr:"#3fb950",it:"#58a6ff",mcp:"#f0883e",other:"#d29922"};
  const icons   = {user:"\\ud83d\\udc64",orch:"\\u26a1",hr:"\\ud83d\\udc65",it:"\\ud83d\\udcbb",mcp:"\\ud83d\\udce6",other:"\\ud83e\\udd16"};

  // -- Draw nodes --
  for (const [name, n] of Object.entries(flowNodes)) {
    const g = document.createElementNS("http://www.w3.org/2000/svg","g");
    g.setAttribute("class","flow-node"); g.setAttribute("data-name", name);
    const rect = document.createElementNS("http://www.w3.org/2000/svg","rect");
    rect.setAttribute("x",n.x); rect.setAttribute("y",n.y);
    rect.setAttribute("width",n.w); rect.setAttribute("height",n.h);
    rect.setAttribute("fill",fills[n.type]||fills.other);
    rect.setAttribute("stroke",strokes[n.type]||strokes.other);
    g.appendChild(rect);

    const ic = document.createElementNS("http://www.w3.org/2000/svg","text");
    ic.setAttribute("x",n.x+12); ic.setAttribute("y",n.y+n.h/2+1);
    ic.setAttribute("font-size","13"); ic.setAttribute("dominant-baseline","middle");
    ic.textContent = icons[n.type]||""; g.appendChild(ic);

    const txt = document.createElementNS("http://www.w3.org/2000/svg","text");
    txt.setAttribute("x",n.x+28); txt.setAttribute("y",n.y+n.h/2+1);
    txt.setAttribute("font-size", n.type==="mcp"?"10":"11");
    txt.setAttribute("dominant-baseline","middle");
    txt.setAttribute("fill",strokes[n.type]);
    const label = name.length > 16 ? name.slice(0,15)+"\\u2026" : name;
    txt.textContent = label; g.appendChild(txt);
    svg.appendChild(g);
  }

  // -- Helper: draw arrow between two nodes --
  // Each arrow has TWO paths: forward (fwd) and reverse (rev), shown independently
  function addArrow(from, to, cls, direction) {
    const f = flowNodes[from], t = flowNodes[to];
    if (!f || !t) return null;
    let x1,y1,x2,y2,d;
    if (direction === "down") {
      x1 = f.x + f.w/2; y1 = f.y + f.h;
      x2 = t.x + t.w/2; y2 = t.y;
      const cy = (y1 + y2) / 2;
      const cx = Math.max(x1, x2) + 60;
      d = `M ${x1} ${y1} Q ${cx} ${cy}, ${x2} ${y2}`;
    } else {
      x1 = f.x + f.w; y1 = f.y + f.h/2;
      x2 = t.x;       y2 = t.y + t.h/2;
      const gap = x2 - x1;
      if (Math.abs(y2 - y1) < 4) {
        d = `M ${x1} ${y1} L ${x2} ${y2}`;
      } else {
        const cx = gap * 0.45;
        d = `M ${x1} ${y1} C ${x1+cx} ${y1}, ${x2-cx} ${y2}, ${x2} ${y2}`;
      }
    }

    // Forward arrow (from -> to)
    const fwd = document.createElementNS("http://www.w3.org/2000/svg","path");
    fwd.setAttribute("d", d);
    fwd.setAttribute("class","flow-arrow fwd "+cls);
    svg.appendChild(fwd);

    // Reverse arrow (to -> from), same path but reverse marker
    // Offset slightly so both aren't on top of each other
    let d2;
    if (direction === "down") {
      const cx2 = Math.max(x1, x2) + 80;
      d2 = `M ${x1} ${y1} Q ${cx2} ${(y1+y2)/2}, ${x2} ${y2}`;
    } else {
      if (Math.abs(y2 - y1) < 4) {
        d2 = `M ${x1} ${y1+4} L ${x2} ${y2+4}`;
      } else {
        const gap = x2 - x1;
        const cx = gap * 0.45;
        d2 = `M ${x1} ${y1+5} C ${x1+cx} ${y1+5}, ${x2-cx} ${y2+5}, ${x2} ${y2+5}`;
      }
    }
    const rev = document.createElementNS("http://www.w3.org/2000/svg","path");
    rev.setAttribute("d", d2);
    rev.setAttribute("class","flow-arrow rev "+cls);
    svg.appendChild(rev);

    // Label positioned at midpoint
    const lx = (x1+x2)/2 + (direction==="down" ? 55 : 0);
    const ly = direction==="down" ? (y1+y2)/2 : Math.min(y1,y2) - 8;
    const lbl = document.createElementNS("http://www.w3.org/2000/svg","text");
    lbl.setAttribute("x",lx); lbl.setAttribute("y",ly);
    lbl.setAttribute("text-anchor","middle");
    lbl.setAttribute("class","flow-label");
    svg.appendChild(lbl);

    const obj = {from, to, cls, fwd, rev, labelEl:lbl};
    flowArrows.push(obj);
    return obj;
  }

  // -- Draw arrows --
  // User -> Orchestrator
  if (orchName) addArrow("User", orchName, "a2a");

  // Orchestrator -> each agent
  if (orchName) agentNames.forEach(an => addArrow(orchName, an, "a2a"));

  // Agent -> MCP
  agentNames.forEach(name => {
    const tp = agentType(name);
    const mName = tp === "hr" ? "HR MCP" : tp === "it" ? "IT MCP" : name + " MCP";
    addArrow(name, mName, "mcp");
  });

  // Agent <-> Agent (peer) - curves right to avoid overlapping nodes
  for (let i = 0; i < agentNames.length; i++) {
    for (let j = i+1; j < agentNames.length; j++) {
      addArrow(agentNames[i], agentNames[j], "peer", "down");
    }
  }

  // -- Legend --
  let legend = document.getElementById("flow-legend");
  if (!legend) {
    legend = document.createElement("div");
    legend.id = "flow-legend"; legend.className = "flow-legend";
    legend.innerHTML = '<div class="flow-legend-item"><span class="swatch" style="background:#bc8cff"></span>A2A</div>'
      +'<div class="flow-legend-item"><span class="swatch" style="background:#f0883e"></span>MCP</div>'
      +'<div class="flow-legend-item"><span class="swatch" style="background:#d2a8ff"></span>Peer</div>';
    document.querySelector(".flow-area").appendChild(legend);
  }
}

// -- Resolve a hint string to a known flowNode name --
function resolveNodeName(hint) {
  if (!hint) return null;
  const h = hint.toLowerCase().replace(/_/g," ").replace(/^ask /,"");
  // Exact match first
  for (const n of Object.keys(flowNodes)) { if (n.toLowerCase() === h) return n; }
  // Word-level match: all words in hint must appear in node name (or vice versa)
  const hWords = h.split(new RegExp("\\\\s+"));
  const nonMcp = Object.keys(flowNodes).filter(n => !n.includes("MCP"));
  for (const n of nonMcp) {
    const nl = n.toLowerCase();
    if (hWords.every(w => nl.includes(w))) return n;
    if (nl.split(new RegExp("\\\\s+")).every(w => h.includes(w))) return n;
  }
  for (const n of Object.keys(flowNodes)) {
    const nl = n.toLowerCase();
    if (hWords.every(w => nl.includes(w))) return n;
    if (nl.split(new RegExp("\\\\s+")).every(w => h.includes(w))) return n;
  }
  return null;
}

// -- Sequential arrow queue + step counter --
let arrowQueue = [];
let arrowBusy = false;
let stepCounter = 0;   // single shared counter for both trace and flow
let orchestratorSentTo = new Set(); // track direct Orchestrator targets

function queueArrow(fromSrc, toHint, cls, label, direction, stepNum) {
  arrowQueue.push({fromSrc, toHint, cls, label, direction, stepNum});
  drainArrowQueue();
}

function drainArrowQueue() {
  if (arrowBusy || arrowQueue.length === 0) return;
  arrowBusy = true;
  const job = arrowQueue.shift();
  activateArrow(job.fromSrc, job.toHint, job.cls, job.label, job.direction, job.stepNum);
  setTimeout(() => { arrowBusy = false; drainArrowQueue(); }, 400);
}

function activateArrow(fromSrc, toHint, cls, label, direction, stepNum) {
  const dir = direction || "fwd";
  const fromNode = resolveNodeName(fromSrc);
  const toNode   = resolveNodeName(toHint);

  // Highlight source node
  const highlightName = dir === "fwd" ? fromNode : toNode;
  if (highlightName) {
    const srcG = document.querySelector('.flow-node[data-name="'+highlightName+'"]');
    if (srcG) { srcG.classList.add("active"); setTimeout(() => srcG.classList.remove("active"), 2500); }
  }

  // Find best matching arrow
  for (const a of flowArrows) {
    const mFrom = fromNode ? a.from === fromNode : a.from.toLowerCase().includes(fromSrc.toLowerCase());
    const mTo   = toNode   ? a.to === toNode     : a.cls === cls;
    // For peer arrows, also check reversed direction (arrow may be stored as B→A but we want A→B)
    const mRevFrom = fromNode ? a.to === fromNode : false;
    const mRevTo   = toNode   ? a.from === toNode : false;
    const reversed = !mFrom && !mTo && a.cls === "peer" && mRevFrom && mRevTo;
    if ((mFrom && mTo) || reversed) {
      const actualDir = reversed ? (dir === "fwd" ? "rev" : "fwd") : dir;
      const pathEl = actualDir === "rev" ? a.rev : a.fwd;
      pathEl.classList.add("visible");
      pathEl.classList.add("active");

      setTimeout(() => { pathEl.classList.remove("active"); }, 3000);

      // Draw step number badge, spread along path to avoid stacking
      const svg = document.getElementById("flow-svg");
      const colors = {a2a:"#bc8cff",mcp:"#f0883e",peer:"#d2a8ff"};
      const pathLen = pathEl.getTotalLength ? pathEl.getTotalLength() : 0;
      if (pathLen > 0 && stepNum) {
        // Track how many badges are already on this arrow
        if (!a.badgeCount) a.badgeCount = 0;
        a.badgeCount++;
        // Spread badges along the path so they don't stack
        const slots = [0.3, 0.5, 0.7, 0.2, 0.8, 0.4, 0.6];
        const frac = slots[(a.badgeCount - 1) % slots.length];
        const pt = pathEl.getPointAtLength(pathLen * frac);
        // Offset away from the path line to avoid overlapping text
        const offsetY = dir === "rev" ? 16 : -14;
        const bx = pt.x, by = pt.y + offsetY;
        const bg = document.createElementNS("http://www.w3.org/2000/svg","rect");
        bg.setAttribute("class","flow-step-bg");
        bg.setAttribute("x",bx-9); bg.setAttribute("y",by-8);
        bg.setAttribute("width",18); bg.setAttribute("height",16);
        bg.setAttribute("fill",colors[cls]||"#8b949e");
        svg.appendChild(bg);
        const num = document.createElementNS("http://www.w3.org/2000/svg","text");
        num.setAttribute("class","flow-step");
        num.setAttribute("x",bx); num.setAttribute("y",by);
        num.setAttribute("text-anchor","middle"); num.setAttribute("dominant-baseline","middle");
        num.textContent = stepNum;
        svg.appendChild(num);
      }
      return;
    }
  }
}

function resetAllArrows() {
  flowArrows.forEach(a => {
    a.fwd.classList.remove("visible","active");
    a.rev.classList.remove("visible","active");
    a.labelEl.classList.remove("visible");
    a.labelEl.textContent = "";
    a.badgeCount = 0;
  });
  document.querySelectorAll(".flow-step, .flow-step-bg").forEach(el => el.remove());
  stepCounter = 0;
  arrowQueue = [];
  arrowBusy = false;
  orchestratorSentTo.clear();
}

// â”€â”€ Agent Loading (in-place, no flicker) â”€â”€
let agentCache = {};
async function loadAgents() {
  try {
    const r = await fetch("/agents");
    const agents = await r.json();
    const list = document.getElementById("agents-list");
    const select = document.getElementById("agent-select");
    const names = Object.keys(agents);
    document.getElementById("agent-count").textContent = names.length;

    if (names.length === 0) {
      list.innerHTML = '<div class="no-agents">No agents yet. Start your services.</div>';
      select.innerHTML = '<option value="">No agents</option>';
      agentCache = {};
      buildFlowDiagram({});
      return;
    }

    // Remove stale
    for (const n of Object.keys(agentCache)) {
      if (!agents[n]) { agentCache[n].el?.remove(); delete agentCache[n]; }
    }

    // Fetch cards in parallel
    const results = await Promise.allSettled(
      names.map(async name => {
        const url = agents[name];
        try {
          const cr = await fetch("/agent-card?url="+encodeURIComponent(url),{signal:AbortSignal.timeout(4000)});
          if (cr.ok) { const c = await cr.json(); return {name,url,online:true,skills:(c.skills||[]).map(s=>s.name)}; }
        } catch {}
        return {name,url,online:false,skills:agentCache[name]?.skills||[]};
      })
    );

    const prevSel = select.value;
    let needsFlowRebuild = false;

    for (const res of results) {
      if (res.status !== "fulfilled") continue;
      const {name,url,online,skills} = res.value;
      const tp = agentType(name);
      const cached = agentCache[name];

      if (cached && cached.el && cached.el.parentNode) {
        // Update in-place
        const badge = cached.el.querySelector(".agent-status");
        if (badge) { badge.className = "agent-status "+(online?"on":"off"); badge.textContent = online?"Online":"Offline"; }
        cached.online = online;
        if (skills.length) cached.skills = skills;
        continue;
      }

      // New agent
      needsFlowRebuild = true;
      list.querySelector(".no-agents")?.remove();
      const el = document.createElement("div");
      el.className = "agent-item";
      el.dataset.name = name;
      el.onclick = function(){ showAgentCard(name, url); };
      el.innerHTML = '<div class="agent-top"><div class="agent-icon '+tp+'">'+AGENT_ICONS[tp]+'</div><div class="agent-nm">'+esc(name)+'</div><span class="agent-status '+(online?"on":"off")+'">'+(online?"Online":"Offline")+'</span></div><div class="agent-url">'+esc(url)+'</div>'+(skills.length?'<div class="agent-skills">'+skills.map(s=>'<span class="skill">'+esc(s)+'</span>').join('')+'</div>':'');
      list.appendChild(el);
      agentCache[name] = {url,online,skills,el};
    }

    // Dropdown
    const curOpts = [...select.options].map(o=>o.value).sort().join(",");
    const newOpts = names.sort().join(",");
    if (curOpts !== newOpts) {
      select.innerHTML = "";
      names.forEach(n => { const o=document.createElement("option"); o.value=n; o.textContent=n; select.appendChild(o); });
      if (prevSel && names.includes(prevSel)) select.value = prevSel;
    }

    if (needsFlowRebuild) buildFlowDiagram(agents);
  } catch(e) { console.error("loadAgents:",e); }
}

// â”€â”€ Trace Timeline â”€â”€
const TRACE_ICONS = {
  a2a_receive:"\\u2b07\\ufe0f", a2a_send:"\\u2b06\\ufe0f", a2a_reply:"\\u2705",
  mcp_discover:"\\ud83d\\udce6", mcp_call:"\\u27a1\\ufe0f", mcp_result:"\\u2b05\\ufe0f",
  peer_send:"\\ud83d\\udd04", peer_receive:"\\ud83d\\udd04",
  llm:"\\ud83e\\udde0", discover:"\\ud83d\\udd0d", found:"\\u2714\\ufe0f",
  receive:"\\u2b07\\ufe0f", done:"\\u2705", info:"\\u2139\\ufe0f",
};

// Produce a human-friendly description from raw trace event
function friendlyMsg(e) {
  const d = e.detail || "";
  const S = "\\s*";
  const Sr = new RegExp("^Query:" + S, "i");
  const Fr = new RegExp("^Found:" + S, "i");
  const Lr = new RegExp("^LLM picked tool\\\\(s\\\\):" + S, "i");
  const Dr = new RegExp("^Discovered" + S, "i");
  const Rr = new RegExp("^Received:" + S, "i");
  const Mr = /-->\\s*(\\S+)\\((.*)\\)/;
  const Ar = />\\s*(.+?):\\s*(.*)/;
  const Br = /<\\S*\\s+(.+?):\\s*(.*)/;
  switch (e.type) {
    case "receive":    return "Received user query: " + d.replace(Sr,"");
    case "discover":   return "Looking up agents in the registry...";
    case "found":      return "Available agents: " + d.replace(Fr,"");
    case "llm":{
      if (d.toLowerCase().includes("choosing")) return "Asking LLM to pick the best agent...";
      if (d.toLowerCase().includes("directly")) return "LLM answered directly (no tools needed)";
      const tools = d.replace(Lr,"");
      return "LLM selected tool" + (tools.includes(",")?"s":"") + ": " + tools;
    }
    case "a2a_send":{
      const m = d.match(Ar);
      return m ? "Forwarding to " + m[1].replace(/_/g," ") + ': "' + m[2].slice(0,60) + '"' : "Sending A2A request";
    }
    case "a2a_receive":{
      if (d.startsWith("<")) {
        const m = d.match(Br);
        return m ? "Reply from " + m[1].replace(/_/g," ") + ': "' + m[2].slice(0,60) + '"' : "Received A2A reply";
      }
      return 'Incoming query: "' + d.replace(Rr,"").slice(0,60) + '"';
    }
    case "a2a_reply":  return "Sent reply back to caller";
    case "mcp_discover":return "Connected to MCP server (" + d.replace(Dr,"") + ")";
    case "info":       return d;
    case "mcp_call":{
      const m = d.match(Mr);
      return m ? "Calling MCP tool " + m[1] + "(" + m[2].slice(0,40) + ")" : "Calling MCP tool";
    }
    case "mcp_result":{
      const clean = d.replace(/^<--/,"").trim().slice(0,80);
      return "MCP returned: " + clean;
    }
    case "peer_send":{
      const m = d.match(Ar);
      return m ? 'Asking peer ' + m[1] + ': "' + m[2].slice(0,50) + '"' : "Sending peer request";
    }
    case "peer_receive":{
      const m = d.match(Br);
      return m ? 'Peer ' + m[1] + ' replied: "' + m[2].slice(0,50) + '"' : "Received peer reply";
    }
    case "done":       return "Done -- returning final answer to user";
    default:           return d || e.type;
  }
}

function traceStepClass(type) {
  if (type.startsWith("a2a") || type==="receive" || type==="done") return "s-a2a";
  if (type.startsWith("mcp")) return "s-mcp";
  if (type.startsWith("peer")) return "s-peer";
  if (type === "llm") return "s-llm";
  return "s-info";
}
function traceClass(type) {
  if (type.startsWith("a2a") || type==="receive" || type==="done") return "t-a2a";
  if (type.startsWith("mcp")) return "t-mcp";
  if (type.startsWith("peer")) return "t-peer";
  if (type === "llm") return "t-llm";
  return "t-info";
}
function srcCls(s) {
  const l=s.toLowerCase();
  if(l.includes("orchestrator"))return"orchestrator";
  if(l.includes("hr"))return"hr";
  if(l.includes("it"))return"it";
  return"";
}

let lastTraceLen = 0;
let traceTimer = null;

// Events that trigger an arrow in the flow diagram
const ARROW_EVENTS = new Set([
  "receive","a2a_send","mcp_call","mcp_result",
  "peer_send","peer_receive","a2a_reply","done"
]);

function appendTraceEvent(e) {
  const body = document.getElementById("trace-body");
  body.querySelector(".trace-empty")?.remove();

  // Only arrow-triggering events get a step number
  const isArrowEvent = ARROW_EVENTS.has(e.type);
  let myStep = null;
  // Step number assigned below AFTER we confirm an arrow will actually fire

  const row = document.createElement("div");
  row.className = "tl-event " + traceClass(e.type) + " child";

  const left = document.createElement("div");
  left.className = "tl-left";
  // Step badge (numbered for arrow events, bullet for others)
  const step = document.createElement("span");
  step.className = "tl-step " + traceStepClass(e.type);
  step.textContent = myStep || "\\u2022";
  if (!myStep) step.style.opacity = "0.5";
  left.appendChild(step);
  const src = document.createElement("div");
  src.className = "tl-src " + srcCls(e.source);
  src.textContent = e.source;
  left.appendChild(src);

  const right = document.createElement("div");
  right.className = "tl-right";
  const content = document.createElement("div");
  content.className = "tl-content";
  const icon = document.createElement("span");
  icon.className = "tl-icon";
  icon.textContent = TRACE_ICONS[e.type] || "\\u2022";
  const msg = document.createElement("span");
  msg.className = "tl-msg";
  msg.textContent = friendlyMsg(e);
  content.appendChild(icon);
  content.appendChild(msg);
  right.appendChild(content);

  row.appendChild(left);
  row.appendChild(right);
  body.appendChild(row);
  body.scrollTop = body.scrollHeight;

  // Activate flow diagram arrows (queued so they animate sequentially)
  // Step number is assigned only when an arrow is actually queued
  function nextStep() { stepCounter++; myStep = stepCounter; step.textContent = myStep; step.style.opacity = "1"; row.classList.remove("child"); return myStep; }

  if (e.type === "receive") {
    queueArrow("User", e.source, "a2a", "", "fwd", nextStep());
  } else if (e.type === "a2a_send") {
    const m = (e.detail||"").match(/>\\s*(.+?):/);
    const target = m ? m[1].trim() : "";
    const resolved = resolveNodeName(target);
    if (resolved) orchestratorSentTo.add(resolved);
    queueArrow(e.source, target, "a2a", "", "fwd", nextStep());
  } else if (e.type === "mcp_call") {
    const mcpTarget = e.source.toLowerCase().includes("hr") ? "HR MCP" : "IT MCP";
    queueArrow(e.source, mcpTarget, "mcp", "", "fwd", nextStep());
  } else if (e.type === "mcp_result") {
    const mcpTarget = e.source.toLowerCase().includes("hr") ? "HR MCP" : "IT MCP";
    queueArrow(e.source, mcpTarget, "mcp", "", "rev", nextStep());
  } else if (e.type === "peer_send") {
    const m = (e.detail||"").match(/>\\s*(.+?):/);
    const target = m ? m[1].trim() : "";
    queueArrow(e.source, target, "peer", "", "fwd", nextStep());
  } else if (e.type === "peer_receive") {
    const m = (e.detail||"").match(/<\\S*\\s+(.+?):/);
    const target = m ? m[1].trim() : "";
    queueArrow(e.source, target, "peer", "", "rev", nextStep());
  } else if (e.type === "a2a_reply") {
    const agentNode = resolveNodeName(e.source);
    if (agentNode && orchestratorSentTo.has(agentNode)) {
      queueArrow("Orchestrator", e.source, "a2a", "", "rev", nextStep());
    }
  } else if (e.type === "done") {
    queueArrow("User", e.source, "a2a", "", "rev", nextStep());
  }
}

async function pollTrace() {
  try {
    const r = await fetch("/trace");
    const events = await r.json();
    if (events.length > lastTraceLen) {
      for (let i = lastTraceLen; i < events.length; i++) appendTraceEvent(events[i]);
      lastTraceLen = events.length;
    }
  } catch {}
}

async function clearTrace() {
  await fetch("/trace",{method:"DELETE"});
  lastTraceLen = 0;
  document.getElementById("trace-body").innerHTML = '<div class="trace-empty">Trace cleared.</div>';
  resetAllArrows();
}

// â”€â”€ Chat â”€â”€
function addMsg(text, cls) {
  const box = document.getElementById("chat-messages");
  const ph = box.querySelector(".chat-placeholder");
  if (ph) ph.remove();
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}

async function sendQuery() {
  const input = document.getElementById("chat-input");
  const agent = document.getElementById("agent-select").value;
  const text = input.value.trim();
  if (!text || !agent) return;

  input.value = "";
  addMsg(text, "user");
  const thinking = addMsg("Thinking...", "thinking");
  document.getElementById("send-btn").disabled = true;

  await fetch("/trace",{method:"DELETE"});
  lastTraceLen = 0;
  document.getElementById("trace-body").innerHTML = '<div class="trace-empty">Waiting for events...</div>';
  resetAllArrows();
  traceTimer = setInterval(pollTrace, 400);

  try {
    const r = await fetch("/query",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({agent,message:text})});
    const data = await r.json();
    thinking.remove();
    if (data.error) addMsg("Error: "+data.error,"error");
    else addMsg(data.response,"agent");
  } catch(e) {
    thinking.remove();
    addMsg("Network error: "+e.message,"error");
  }
  setTimeout(async()=>{await pollTrace();clearInterval(traceTimer);traceTimer=null;},1500);
  document.getElementById("send-btn").disabled = false;
  input.focus();
}

function runTest(card, idx) {
  document.querySelectorAll(".test-card").forEach(c=>c.classList.remove("active"));
  card.classList.add("active");
  document.getElementById("chat-input").value = TESTS[idx];
  const sel = document.getElementById("agent-select");
  for (const o of sel.options) { if (o.value.includes("Orchestrator")) { sel.value=o.value; break; } }
  sendQuery();
}

async function registerAgent() {
  const name=document.getElementById("reg-name").value.trim();
  const url=document.getElementById("reg-url").value.trim();
  const msg=document.getElementById("reg-msg");
  if(!name||!url){msg.textContent="Both fields required.";msg.style.color="#f0883e";return}
  try{
    const r=await fetch("/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,url})});
    if(r.ok){msg.textContent="Registered: "+name;msg.style.color="#3fb950";document.getElementById("reg-name").value="";document.getElementById("reg-url").value="";loadAgents();}
    else{msg.textContent="Failed.";msg.style.color="#f85149";}
  }catch(e){msg.textContent="Error: "+e.message;msg.style.color="#f85149";}
}

document.getElementById("chat-input").addEventListener("keydown",e=>{if(e.key==="Enter")sendQuery()});
// -- Agent Card Modal --
function showAgentCard(name, url) {
  const overlay = document.getElementById('ac-overlay');
  document.getElementById('ac-title').textContent = name + ' — Agent Card';
  const body = document.getElementById('ac-body');
  body.innerHTML = '<div class="ac-loading">Loading agent card...</div>';
  overlay.classList.add('open');
  fetch('/agent-card?url='+encodeURIComponent(url), {signal:AbortSignal.timeout(5000)})
    .then(r => r.json())
    .then(card => { body.innerHTML = '<pre>'+esc(JSON.stringify(card,null,2))+'</pre>'; })
    .catch(e => { body.innerHTML = '<div class="ac-loading" style="color:#f85149">Could not load agent card.<br>'+esc(e.message)+'</div>'; });
}
function closeAgentCard() { document.getElementById('ac-overlay').classList.remove('open'); }

loadAgents();
setInterval(loadAgents,10000);

// Attach overlay click-to-close after DOM is ready
document.addEventListener('DOMContentLoaded', function() {
  var ov = document.getElementById('ac-overlay');
  if(ov) ov.addEventListener('click', function(e){ if(e.target===this) closeAgentCard(); });
});
</script>

<div class="ac-overlay" id="ac-overlay">
  <div class="ac-modal">
    <div class="ac-hdr"><span class="ac-hdr-title" id="ac-title">Agent Card</span><button class="ac-close" onclick="closeAgentCard()">&times;</button></div>
    <div class="ac-body" id="ac-body"></div>
  </div>
</div>
</body>
</html>"""


# -------------------------------------------------------------
# SECTION 6: Dashboard & Helper Endpoints
# -------------------------------------------------------------

async def dashboard(request: Request):
    """Serve the registry dashboard UI."""
    return HTMLResponse(HTML_PAGE)


async def agent_card_proxy(request: Request):
    """Fetch an agent's A2A card on behalf of the browser (avoids CORS)."""
    url = request.query_params.get("url", "")
    if not url:
        return JSONResponse({"error": "missing url"}, status_code=400)
    try:
        async with httpx.AsyncClient(verify=False, timeout=5) as http:
            r = await http.get(f"{url.rstrip('/')}/.well-known/agent-card.json")
            return JSONResponse(r.json())
    except:
        return JSONResponse({"error": "offline"}, status_code=503)


# -------------------------------------------------------------
# SECTION 7: Start the Registry
# -------------------------------------------------------------

app = Starlette(routes=[
    Route("/", dashboard),
    Route("/register", register, methods=["POST"]),
    Route("/agents", list_agents),
    Route("/trace", trace_handler, methods=["GET", "POST", "DELETE"]),
    Route("/query", query_agent, methods=["POST"]),
    Route("/agent-card", agent_card_proxy),
])

if __name__ == "__main__":
    print("Agent Registry running at http://localhost:9000")
    print("Dashboard UI:  http://localhost:9000")
    print("Agents will register here on startup.\n")
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="warning")
