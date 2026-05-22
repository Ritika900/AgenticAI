from flask import Flask, request, jsonify, render_template_string
from main import triage_bug
import hashlib
import re

app = Flask(__name__)

# ── Server-side deduplication cache ─────────────────────────────────────────
# Maps normalised_message_hash -> triage result dict.
# Cleared only on server restart (swap for Redis/DB for persistence).
_triage_cache: dict[str, dict] = {}

def _normalise(text: str) -> str:
    """Lowercase, strip punctuation/extra spaces for fuzzy dedup."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text

def _cache_key(message: str) -> str:
    return hashlib.md5(_normalise(message).encode()).hexdigest()

# ─────────────────────────────────────────────────────────────────────────────

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Bug Triage · Support</title>
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@300;400;500&display=swap" rel="stylesheet"/>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:        #0a0a0f;
      --surface:   #12121a;
      --border:    #1e1e2e;
      --accent:    #ff5f40;
      --accent2:   #ffb340;
      --text:      #e8e8f0;
      --muted:     #6b6b80;
      --user-bg:   #1a1a2e;
      --bot-bg:    #12121a;
      --radius:    14px;
      --mono:      'DM Mono', monospace;
      --sans:      'Syne', sans-serif;
    }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    /* ── Header ── */
    header {
      display: flex;
      align-items: center;
      gap: 14px;
      padding: 18px 28px;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
      flex-shrink: 0;
    }

    .logo {
      width: 36px; height: 36px;
      background: var(--accent);
      border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 18px;
    }

    header h1 { font-size: 1.1rem; font-weight: 700; letter-spacing: -0.02em; }
    header h1 span { color: var(--accent); }

    .status-pill {
      margin-left: auto;
      background: #0d2b1a;
      color: #3ddc84;
      font-family: var(--mono);
      font-size: 0.7rem;
      padding: 4px 10px;
      border-radius: 20px;
      border: 1px solid #1a4d30;
      display: flex; align-items: center; gap: 6px;
    }

    .status-pill::before {
      content: '';
      width: 6px; height: 6px;
      background: #3ddc84;
      border-radius: 50%;
      animation: pulse 2s infinite;
    }

    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.3; }
    }

    /* ── Chat area ── */
    #chat {
      flex: 1;
      overflow-y: auto;
      padding: 28px 20px;
      display: flex;
      flex-direction: column;
      gap: 20px;
      scroll-behavior: smooth;
    }

    #chat::-webkit-scrollbar { width: 4px; }
    #chat::-webkit-scrollbar-track { background: transparent; }
    #chat::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

    /* ── Messages ── */
    .msg {
      display: flex;
      gap: 12px;
      max-width: 780px;
      animation: fadeUp 0.3s ease forwards;
      opacity: 0;
    }

    @keyframes fadeUp {
      from { opacity: 0; transform: translateY(10px); }
      to   { opacity: 1; transform: translateY(0); }
    }

    .msg.user { margin-left: auto; flex-direction: row-reverse; }

    .avatar {
      width: 34px; height: 34px;
      border-radius: 10px;
      flex-shrink: 0;
      display: flex; align-items: center; justify-content: center;
      font-size: 15px;
      font-weight: 700;
    }

    .msg.bot  .avatar { background: #1a1a2e; border: 1px solid var(--border); }
    .msg.user .avatar { background: var(--accent); color: #fff; }

    .bubble {
      padding: 14px 18px;
      border-radius: var(--radius);
      font-size: 0.92rem;
      line-height: 1.65;
      max-width: 640px;
    }

    .msg.bot  .bubble { background: var(--bot-bg);  border: 1px solid var(--border); border-top-left-radius: 4px; }
    .msg.user .bubble { background: var(--user-bg); border: 1px solid #2a2a45;      border-top-right-radius: 4px; }

    /* ── Ticket card ── */
    .ticket-card {
      margin-top: 14px;
      background: #0d0d14;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px 16px;
      font-family: var(--mono);
      font-size: 0.8rem;
    }

    /* new  = orange-red left accent */
    .ticket-card.is-new  { border-left: 3px solid var(--accent); }
    /* dupe = amber left accent */
    .ticket-card.is-dupe { border-left: 3px solid var(--accent2); }

    .ticket-card .tc-header {
      font-weight: 500;
      font-size: 0.75rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 10px;
    }

    .ticket-card.is-new  .tc-header { color: var(--accent); }
    .ticket-card.is-dupe .tc-header { color: var(--accent2); }

    .ticket-card .tc-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 6px 0;
      border-bottom: 1px solid var(--border);
      color: var(--muted);
    }

    .ticket-card .tc-row:last-child { border-bottom: none; }
    .ticket-card .tc-row span:last-child { color: var(--text); text-align: right; word-break: break-word; }

    /* ServiceNow button */
    .snow-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      margin-top: 12px;
      padding: 9px 14px;
      background: #150d2a;
      border: 1px solid #3a1f6e;
      border-radius: 8px;
      color: #c084fc;
      font-family: var(--mono);
      font-size: 0.77rem;
      text-decoration: none;
      transition: background 0.2s, border-color 0.2s, color 0.2s;
    }

    .snow-btn:hover { background: #1f1040; border-color: #7c3aed; color: #e9d5ff; }

    .snow-btn svg { width: 14px; height: 14px; fill: currentColor; flex-shrink: 0; }

    .priority-badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 0.72rem;
      font-weight: 500;
    }

    .p1 { background: #3d0a0a; color: #ff5f5f; }
    .p2 { background: #3d2200; color: #ffaa40; }
    .p3 { background: #1a2d00; color: #88dd44; }
    .p4 { background: #0a1a2d; color: #44aaff; }

    /* ── Typing indicator ── */
    .typing { display: flex; gap: 5px; align-items: center; padding: 6px 0; }
    .typing span {
      width: 7px; height: 7px;
      background: var(--muted);
      border-radius: 50%;
      animation: bounce 1.2s infinite;
    }
    .typing span:nth-child(2) { animation-delay: 0.2s; }
    .typing span:nth-child(3) { animation-delay: 0.4s; }

    @keyframes bounce {
      0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
      40%            { transform: translateY(-6px); opacity: 1; }
    }

    /* ── Input area ── */
    #input-area {
      padding: 16px 20px;
      border-top: 1px solid var(--border);
      background: var(--surface);
      flex-shrink: 0;
    }

    .input-row {
      display: flex;
      gap: 10px;
      align-items: flex-end;
      max-width: 860px;
      margin: 0 auto;
    }

    #msg-input {
      flex: 1;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 13px 16px;
      color: var(--text);
      font-family: var(--sans);
      font-size: 0.92rem;
      resize: none;
      min-height: 50px;
      max-height: 140px;
      outline: none;
      transition: border-color 0.2s;
      line-height: 1.5;
    }

    #msg-input:focus { border-color: var(--accent); }
    #msg-input::placeholder { color: var(--muted); }

    #send-btn {
      background: var(--accent);
      border: none;
      border-radius: var(--radius);
      width: 50px; height: 50px;
      cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      transition: background 0.2s, transform 0.1s;
      flex-shrink: 0;
    }

    #send-btn:hover   { background: #ff7a60; }
    #send-btn:active  { transform: scale(0.95); }
    #send-btn:disabled { background: var(--border); cursor: not-allowed; }
    #send-btn svg { width: 20px; height: 20px; fill: #fff; }

    .hint {
      text-align: center;
      font-family: var(--mono);
      font-size: 0.7rem;
      color: var(--muted);
      margin-top: 8px;
    }

    /* ── Welcome ── */
    .welcome {
      margin: auto;
      text-align: center;
      padding: 40px 20px;
      animation: fadeUp 0.5s ease forwards;
    }

    .welcome .icon { font-size: 3rem; margin-bottom: 16px; }

    .welcome h2 {
      font-size: 1.6rem;
      font-weight: 800;
      letter-spacing: -0.03em;
      margin-bottom: 8px;
    }

    .welcome h2 span { color: var(--accent); }

    .welcome p {
      color: var(--muted);
      font-size: 0.9rem;
      max-width: 380px;
      margin: 0 auto 24px;
      line-height: 1.6;
    }

    .chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }

    .chip {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 7px 14px;
      font-size: 0.82rem;
      color: var(--muted);
      cursor: pointer;
      transition: all 0.2s;
      font-family: var(--mono);
    }

    .chip:hover { border-color: var(--accent); color: var(--accent); }
  </style>
</head>
<body>

<header>
  <div class="logo">🐛</div>
  <h1>Bug <span>Triage</span></h1>
  <div class="status-pill">system online</div>
</header>

<div id="chat">
  <div class="welcome" id="welcome">
    <div class="icon">🔍</div>
    <h2>Report a <span>Bug</span></h2>
    <p>Describe your issue and I'll analyze it, search for matches, and create a support ticket automatically.</p>
    <div class="chips">
      <div class="chip" onclick="prefill('Login page crashes after resetting my password')">Login crash after reset</div>
      <div class="chip" onclick="prefill('Dashboard not loading for some users')">Dashboard not loading</div>
      <div class="chip" onclick="prefill('API timeout on checkout page')">API timeout on checkout</div>
      <div class="chip" onclick="prefill('App freezes on mobile when uploading files')">Mobile upload freeze</div>
    </div>
  </div>
</div>

<div id="input-area">
  <div class="input-row">
    <textarea id="msg-input" placeholder="Describe your bug or issue..." rows="1"></textarea>
    <button id="send-btn" onclick="sendMessage()">
      <svg viewBox="0 0 24 24"><path d="M2 21l21-9L2 3v7l15 2-15 2z"/></svg>
    </button>
  </div>
  <div class="hint">Press Enter to send &nbsp;·&nbsp; Shift+Enter for new line</div>
</div>

<script>
  const chat  = document.getElementById('chat');
  const input = document.getElementById('msg-input');
  const btn   = document.getElementById('send-btn');

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 140) + 'px';
  });

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  function prefill(text) {
    input.value = text;
    input.focus();
    input.dispatchEvent(new Event('input'));
  }

  function removeWelcome() {
    const w = document.getElementById('welcome');
    if (w) w.remove();
  }

  function appendMsg(role, html) {
    removeWelcome();
    const isUser = role === 'user';
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.innerHTML = `
      <div class="avatar">${isUser ? 'U' : '🤖'}</div>
      <div class="bubble">${html}</div>
    `;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
  }

  function showTyping() {
    return appendMsg('bot', '<div class="typing"><span></span><span></span><span></span></div>');
  }

  function priorityBadge(p) {
    const labels = { 1: 'P1 Critical', 2: 'P2 High', 3: 'P3 Medium', 4: 'P4 Low' };
    return `<span class="priority-badge p${p}">${labels[p] || 'P' + p}</span>`;
  }

  // ── Format the full bot response ──────────────────────────────────────────
  function formatResponse(data) {
    if (typeof data === 'string') return `<div>${data}</div>`;

    // /triage wraps in { result: ... }
    const r = data.result || data.response || data;

    const isDupe     = !!r.duplicate;
    const ticketNum  = r.ticket_number || r.incident_number || r.ticket_id;
    const priority   = r.priority;
    const reasoning  = r.priority_reasoning || r.reasoning;
    const resolution = r.resolution || r.suggested_resolution;
    const githubLink = r.github_issue_url || r.github_url;
    const snowUrl    = r.incident_url || r.servicenow_url;   // ServiceNow link

    let html = '';

    // ── Summary line ─────────────────────────────────────────────────────────
    if (isDupe) {
      html += `<div>⚠️ This issue was already reported. Linked to the existing ticket below — no new ticket created.</div>`;
    } else if (r.message || r.summary) {
      html += `<div>${r.message || r.summary}</div>`;
    } else {
      html += `<div>Your bug report has been processed.</div>`;
    }

    // ── Ticket card ──────────────────────────────────────────────────────────
    if (ticketNum || priority) {
      const cardCls = isDupe ? 'is-dupe' : 'is-new';
      const header  = isDupe ? '🔁 Existing Ticket' : '⚡ Ticket Created';

      html += `<div class="ticket-card ${cardCls}">
        <div class="tc-header">${header}</div>`;

      if (ticketNum)  html += row('Ticket #', ticketNum);
      if (priority)   html += row('Priority', priorityBadge(priority));
      if (reasoning)  html += row('Reason',   reasoning);
      if (resolution) html += row('Resolution', resolution);
      if (githubLink) html += row('GitHub', `<a href="${githubLink}" target="_blank" style="color:var(--accent2)">View Issue ↗</a>`);

      // ── ServiceNow button (prominent, full-width) ─────────────────────────
      if (snowUrl) {
        html += `
          <a class="snow-btn" href="${snowUrl}" target="_blank" rel="noopener">
            <svg viewBox="0 0 24 24">
              <path d="M14 3v2H7v14h10v-4h2v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h8zm5 7v2h-7v3l-4-4 4-4v3h7z"/>
            </svg>
            Open in ServiceNow ↗
          </a>`;
      }

      html += `</div>`;

    } else {
      // Fallback: pretty-print raw response
      html += `<div class="ticket-card is-new">
        <div class="tc-header">📋 Response</div>
        <pre style="white-space:pre-wrap;font-family:var(--mono);font-size:0.78rem;color:var(--muted)">${JSON.stringify(r, null, 2)}</pre>
      </div>`;
    }

    return html;
  }

  // Helper: one table row
  function row(label, value) {
    return `<div class="tc-row"><span>${label}</span><span>${value}</span></div>`;
  }

  // ── Send ──────────────────────────────────────────────────────────────────
  async function sendMessage() {
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    input.style.height = 'auto';
    btn.disabled = true;

    appendMsg('user', text);
    const typingEl = showTyping();

    try {
      const res = await fetch('/triage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, reporter: 'web_user' })
      });

      const data = await res.json();
      typingEl.remove();
      appendMsg('bot', formatResponse(data));

    } catch (err) {
      typingEl.remove();
      appendMsg('bot', `<span style="color:var(--accent)">⚠ Error connecting to server.</span> Please try again.`);
    }

    btn.disabled = false;
    input.focus();
  }
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/webhook", methods=["POST"])
def handle_chat():
    """Endpoint for chat integrations (Slack, Teams, etc.)"""
    data    = request.json
    message = data.get("text", "")
    user    = data.get("user", "unknown")

    key = _cache_key(message)
    if key in _triage_cache:
        cached = dict(_triage_cache[key])
        cached["duplicate"] = True
        return jsonify({"response": cached})

    result = triage_bug(message, user)
    _triage_cache[key] = result
    return jsonify({"response": result})

@app.route("/triage", methods=["POST"])
def triage():
    """Main triage endpoint — deduplicates repeated reports."""
    data     = request.json
    message  = data.get("message", "")
    reporter = data.get("reporter", "api_user")

    key = _cache_key(message)

    # ── Duplicate: return cached result, no new ticket ───────────────────────
    if key in _triage_cache:
        cached = dict(_triage_cache[key])
        cached["duplicate"] = True
        return jsonify({"result": cached})

    # ── New report: run full workflow ────────────────────────────────────────
    result = triage_bug(message, reporter)
    _triage_cache[key] = result
    return jsonify({"result": result})


if __name__ == "__main__":
    app.run(port=5000, debug=True)