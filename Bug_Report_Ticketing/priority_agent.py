"""
priority_agent.py
-----------------
LLM layer that classifies the priority of a bug report.

Uses Azure OpenAI (matches the project's .env) and returns a clean dict.
Replaces the previous version that used eval() (unsafe) and plain OpenAI.
"""

import os
import json
import re
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

_client = AzureOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    azure_endpoint=os.getenv("OPENAI_API_BASE", ""),
    api_version=os.getenv("OPENAI_API_VERSION", "2025-04-01-preview"),
)
_DEPLOYMENT = os.getenv("OPENAI_DEPLOYMENT", "gpt-5.4-mini")

_SYSTEM_PROMPT = """You are a bug-triage assistant. Classify the priority of the bug the user describes.

Priority rules:
  P1 – system down / crash / blocking ALL users
  P2 – major feature broken, significant user impact
  P3 – moderate issue, workaround exists
  P4 – minor / cosmetic issue

Respond ONLY with valid JSON in exactly this shape (no markdown, no explanation):
{
  "priority": <integer 1-4>,
  "reason": "<one concise sentence>"
}"""


def decide_priority(bug_text: str) -> dict:
    """
    Classify the priority of *bug_text* using the Azure OpenAI LLM.

    Returns:
        {
            "priority": int,   # 1-4
            "reason":   str
        }
    Falls back to P3 if the LLM response cannot be parsed.
    """
    try:
        response = _client.chat.completions.create(
            model=_DEPLOYMENT,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": bug_text},
            ],
            temperature=0,
            max_tokens=120,
        )

        raw = response.choices[0].message.content.strip()

        # Strip any accidental markdown fences (```json ... ```)
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()

        parsed = json.loads(raw)

        # Normalise: accept "P2" string or integer 2
        priority_raw = parsed.get("priority", 3)
        if isinstance(priority_raw, str):
            priority_raw = int(priority_raw.lstrip("Pp"))
        priority = max(1, min(4, int(priority_raw)))   # clamp to 1-4

        return {
            "priority": priority,
            "reason":   str(parsed.get("reason", "")).strip(),
        }

    except Exception as exc:
        print(f"[priority_agent] LLM call failed: {exc}")
        return {"priority": 3, "reason": "Default fallback – LLM unavailable."}