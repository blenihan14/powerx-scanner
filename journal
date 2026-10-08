"""Google Sheets journal adapter. Configure credentials in Streamlit secrets."""
from __future__ import annotations

import logging
from typing import Any
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _client():
    if "gcp_service_account" not in st.secrets:
        raise RuntimeError("Missing [gcp_service_account] in Streamlit secrets.")
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    return gspread.authorize(creds)


def get_records(sheet_title: str) -> list[dict[str, Any]]:
    worksheet = _client().open(sheet_title).get_worksheet(0)
    return worksheet.get_all_records()


def append_trade(sheet_title: str, trade: dict[str, Any]) -> tuple[bool, str]:
    """Append by explicit schema; first row should contain matching headers."""
    headers = [
        "Trade ID", "Opened Date", "Ticker", "Strategy", "Option Type", "Side",
        "Strike", "Expiration", "Contracts", "Premium Per Share", "Total Premium",
        "Underlying At Entry", "IV", "Status", "Notes"
    ]
    try:
        worksheet = _client().open(sheet_title).get_worksheet(0)
        existing = worksheet.row_values(1)
        if not existing:
            worksheet.append_row(headers, value_input_option="USER_ENTERED")
            existing = headers
        missing = [h for h in headers if h not in existing]
        if missing:
            return False, (
                "Sheet headers do not match the expected schema. Missing: "
                + ", ".join(missing)
            )
        values = [trade.get(h, "") for h in existing]
        worksheet.append_row(values, value_input_option="USER_ENTERED")
        return True, "Trade logged successfully."
    except Exception as exc:
        logger.exception("Failed to append trade")
        return False, f"Could not log trade: {exc}"
