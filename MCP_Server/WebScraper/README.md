# Agentic Web Scraper

A template-based web scraper that combines Playwright MCP (for browser automation) with Groq LLM.

---

## How It Works

Uses a **2-phase approach** that avoids common Groq tool-call errors:

```
Phase 1 → Playwright navigates the URL and takes a page snapshot (no LLM)
Phase 2 → Groq LLM reads the snapshot text and returns structured JSON (no tools)
```

This separation means the LLM never has to generate browser tool calls — it just extracts data from text, which it does reliably.

---

## Tech Stack

- **[Groq](https://groq.com)** — Fast LLM inference (llama-3.3-70b)
- **[Playwright MCP](https://github.com/microsoft/playwright-mcp)** — Headless browser automation via Model Context Protocol
- **[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)** — MCP client session management
