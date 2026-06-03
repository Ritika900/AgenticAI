import asyncio
import json
import os
import re
from dotenv import load_dotenv
from groq import Groq
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import httpx

load_dotenv()

http_client = httpx.Client(verify=False)
client = Groq(api_key=os.getenv("GROQ_API_KEY"), http_client=http_client)

# ─────────────────────────────────────────────
# ✏️  CONFIGURATION — only edit this section
# ─────────────────────────────────────────────
CONFIG = {
    # Target URL to scrape
    "url": "https://www.britannica.com/technology/artificial-intelligence",

    # What you want to extract (plain English — be specific)
    "extraction_goal": "the top 10 story headlines and their links",

    # Fields you expect in each result object
    "fields": ["title", "url"],

    # Optional: CSS selector hint (leave "" to let the LLM decide)
    "css_selector": "",

    # Optional: extra instructions
    "extra_instructions": "",  # e.g. "Ignore sidebar and footer links."

    # Output file path
    "output_file": "results/output.json",

    # Groq model to use
    "model": "llama-3.3-70b-versatile",

    # Max tokens for LLM response
    "max_tokens": 4096,
}
# ─────────────────────────────────────────────

# ── Allowlist: only expose these tools to the LLM ────────────────────────────
# Groq struggles when given 23 complex tool schemas — it generates malformed
# calls. We expose only the 4 simple, safe tools it actually needs.
ALLOWED_TOOLS = {
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
}

def build_extraction_prompt(page_content: str, config: dict) -> str:
    """
    Build a pure-text extraction prompt (no tools needed at this stage).
    The LLM receives the page snapshot as text and just returns JSON.
    """
    fields_desc = ", ".join(f'"{f}"' for f in config["fields"])
    selector_hint = (
        f" Focus on elements matching CSS selector: {config['css_selector']}."
        if config.get("css_selector") else ""
    )
    extra = (
        f"\n\nAdditional instructions: {config['extra_instructions']}"
        if config.get("extra_instructions") else ""
    )
    return (
        f"Below is the raw content of the web page at {config['url']}.\n\n"
        f"---PAGE CONTENT START---\n{page_content[:12000]}\n---PAGE CONTENT END---\n\n"
        f"Extract {config['extraction_goal']}.{selector_hint}\n"
        f"Return ONLY a raw JSON array (no markdown, no explanation, no code fences).\n"
        f"Each item must have exactly these keys: {fields_desc}.\n"
        f"If a value is missing, use null."
        f"{extra}"
    )


def extract_json(text: str) -> list | None:
    """Robustly extract a JSON array from LLM output."""
    if not text:
        return None

    # 1. Strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()

    # 2. Direct parse
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    # 3. Find outermost [...]
    start = cleaned.find("[")
    end = cleaned.rfind("]") + 1
    if start != -1 and end > start:
        try:
            parsed = json.loads(cleaned[start:end])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # 4. Find outermost {...}
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start != -1 and end > start:
        try:
            parsed = json.loads(cleaned[start:end])
            return [parsed]
        except json.JSONDecodeError:
            pass

    return None


def save_results(data: list, output_file: str) -> None:
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"💾 Saved {len(data)} items → {output_file}\n")


def print_results(data: list, fields: list) -> None:
    primary   = fields[0] if fields else "item"
    secondary = fields[1] if len(fields) > 1 else None
    for i, item in enumerate(data, 1):
        print(f"  {i}. {item.get(primary, '(no value)')}")
        if secondary:
            print(f"     {item.get(secondary, '(no value)')}")
        print()


async def get_page_content(session: ClientSession, url: str) -> str:
    """
    Navigate to the URL and take a page snapshot using Playwright MCP directly
    (no LLM involved — avoids Groq tool-call generation errors entirely).
    """
    print(f"   [1/2] Navigating to {url} ...")
    nav_result = await session.call_tool("browser_navigate", {"url": url})
    print(f"   [2/2] Taking page snapshot ...")
    snap_result = await session.call_tool("browser_snapshot", {})

    # Combine both results as page content
    content_parts = []
    for result in [nav_result, snap_result]:
        if result and result.content:
            for block in result.content:
                text = getattr(block, "text", None) or str(block)
                if text:
                    content_parts.append(text)

    return "\n".join(content_parts)


async def scrape(config: dict = CONFIG) -> list:
    """
    Two-phase scraping approach:
      Phase 1 — Playwright navigates & snapshots the page (no LLM tool calls).
      Phase 2 — Groq LLM extracts structured data from the snapshot text.

    This avoids the Groq 400 `tool_use_failed` error caused by the LLM
    generating malformed tool calls with 23 complex schemas.
    """
    print(f"🌐 Target  : {config['url']}")
    print(f"🎯 Goal    : {config['extraction_goal']}")
    print(f"📋 Fields  : {config['fields']}\n")

    server_params = StdioServerParameters(
        command="npx",
        args=["@playwright/mcp", "--headless"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"✅ Connected — {len(tools.tools)} Playwright tools available.")
            print("📸 Phase 1: Fetching page content via Playwright...\n")

            # ── Phase 1: Use Playwright directly (no LLM) ────────────────────
            try:
                page_content = await get_page_content(session, config["url"])
            except Exception as e:
                print(f"❌ Failed to fetch page: {e}")
                return []

            if not page_content.strip():
                print("❌ Page snapshot was empty. Check the URL or try with headful mode.")
                return []

            print(f"   ✅ Got {len(page_content):,} chars of page content.\n")

    # ── Phase 2: LLM extracts from text (outside MCP context — no tools) ─────
    print("🤖 Phase 2: Extracting data with Groq LLM (text-only, no tools)...\n")

    extraction_prompt = build_extraction_prompt(page_content, config)

    try:
        response = client.chat.completions.create(
            model=config["model"],
            max_tokens=config["max_tokens"],
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a precise data extraction assistant. "
                        "You receive web page content and extract structured data. "
                        "You ALWAYS respond with raw JSON only — no markdown, no explanation."
                    ),
                },
                {"role": "user", "content": extraction_prompt},
            ],
            # No tools parameter — pure text completion avoids tool_use_failed errors
        )
    except Exception as e:
        print(f"❌ Groq API error: {e}")
        return []

    raw_output = response.choices[0].message.content
    print("✅ Extraction complete.\n")

    results = extract_json(raw_output)

    if results:
        save_results(results, config["output_file"])
        print_results(results, config["fields"])
        return results
    else:
        print("⚠️  Could not parse JSON from LLM response.")
        print("─── Raw LLM output ───")
        print(raw_output)
        print("──────────────────────")
        return []


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(scrape())