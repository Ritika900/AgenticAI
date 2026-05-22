"""
excel_logger.py
---------------
Appends a resolved incident row to the local Excel incident log.
"""

import os
import pandas as pd

FILE_PATH = os.getenv("INCIDENT_LOG_PATH", "Past Incidents Log.xlsx")

COLUMNS = [
    "Incident Number",
    "User Message",
    "Priority",
    "Incident URL",
]


def log_to_excel(data: dict) -> None:
    """
    Append one incident row to the Excel log.

    Args:
        data: dict with keys:
              incident_number, user_message, priority, incident_url
    """
    new_row = {
        "Incident Number": data.get("incident_number"),
        "User Message":    data.get("user_message"),
        "Priority":        data.get("priority"),
        "Incident URL":    data.get("incident_url"),
    }

    try:
        if os.path.exists(FILE_PATH):
            df = pd.read_excel(FILE_PATH, engine="openpyxl")
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        else:
            df = pd.DataFrame([new_row], columns=COLUMNS)

        df.to_excel(FILE_PATH, index=False, engine="openpyxl")

    except Exception as exc:
        print(f"[excel_logger] Failed to write incident log: {exc}")