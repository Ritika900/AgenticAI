# 🤖 Multi-Agent Bug Triage System

An AI-powered pipeline that converts a plain-English bug description into a ServiceNow ticket automatically — no manual triage needed.

## How It Works
A user types a bug in the chat UI. Four agents handle the rest:
1. **Detective** — searches for matching known issues
2. **Brain** — classifies priority P1–P4 using ollama llm; auto-escalates to P1 on recurring patterns
3. **RAG Check** — detects semantic duplicates via ChromaDB so the same bug never creates two tickets
4. **Fixer** — creates or updates a ServiceNow ticket, then logs to Excel + ChromaDB

## Tech Stack
LangGraph · LLM · ChromaDB · Flask · ServiceNow 

## Setup
```bash
pip install langgraph langchain-openai openai chromadb flask pandas openpyxl requests python-dotenv google-auth google-api-python-client
cp .env.example .env   # fill in API keys
python app.py          # visit http://localhost:5000
```
