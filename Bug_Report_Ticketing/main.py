import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import warnings
import urllib3
warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import os
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["SSL_CERT_FILE"] = ""

import json
from agents.workflow import bug_triage_workflow
from agents.state import BugTriageState
from dotenv import load_dotenv

load_dotenv()


def triage_bug(message: str, reporter: str = "user") -> dict:
    """
    Process a bug report through the multi-agent system.

    Args:
        message: The bug description from the user
        reporter: Identifier for the person reporting

    Returns:
        A dict with structured response for the UI
    """
    initial_state: BugTriageState = {
        "user_message": message,
        "reporter_id": reporter,
        "github_matches": [],
        "github_search_count": 0,
        "needs_user_clarification": False,
        "selected_issue": None,
        "priority": 3,
        "priority_reasoning": "",
        "pattern_detected": False,
        "past_incidents": [],
        "refined_search_needed": False,
        "refined_search_query": None,
        "action_taken": "none",
        "incident_number": None,
        "incident_url": None,
        "current_step": "start",
        "final_response": "",
        "error": None
    }

    try:
        final_state = bug_triage_workflow.invoke(initial_state)
        raw = final_state.get("final_response", "{}")

        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"type": "logged", "message": raw or "Report processed."}

        # Attach ServiceNow details if available
        parsed["incident_number"] = final_state.get("incident_number")
        parsed["incident_url"] = final_state.get("incident_url")

        return parsed

    except Exception as e:
        print(f"[ERROR] Workflow failed: {e}")
        return {
            "type": "error",
            "message": "An unexpected error occurred while processing your report.",
            "detail": str(e)
        }


if __name__ == "__main__":
    print("\n🚀 Bug Triage System (Type 'exit' to quit)\n")

    while True:
        user_input = input("👤 Enter your bug: ").strip()

        if user_input.lower() == "exit":
            print("👋 Exiting...")
            break

        if not user_input:
            continue

        response = triage_bug(user_input, "user@company.com")

        print("\n🤖 Agent Response:")
        print(json.dumps(response, indent=2))

        if response.get("incident_url"):
            print(f"\n🔗 ServiceNow Incident: {response['incident_url']}")
        elif response.get("incident_number"):
            print(f"\n📌 Incident Created: {response['incident_number']}")