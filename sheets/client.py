"""Google Sheets client — connects via service account and polls for pending rows."""

import os
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

# Column names that must exist in the sheet (order doesn't matter)
REQUIRED_COLUMNS = [
    "application_url",
    "company",
    "role",
    "location",
    "employment_type",
    "jd_summary",
    "fit_score",
    "fit_reasoning",
    "portal_type",
    "status",
    "date_applied",
    "notes",
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_credentials(credentials_path: str) -> Credentials:
    return Credentials.from_service_account_file(credentials_path, scopes=SCOPES)


class SheetsClient:
    def __init__(self, credentials_path: str, spreadsheet_name: str):
        """
        Args:
            credentials_path: Path to the service account JSON key file.
            spreadsheet_name: Exact name of the Google Sheet.
        """
        creds = _get_credentials(credentials_path)
        self._gc = gspread.authorize(creds)
        self._sheet = self._gc.open(spreadsheet_name).sheet1
        self._headers: list[str] = self._sheet.row_values(1)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _col(self, name: str) -> int:
        """Return 1-based column index for a header name."""
        return self._headers.index(name) + 1

    def _row_to_dict(self, row_values: list[str], row_number: int) -> dict:
        d = {h: (row_values[i] if i < len(row_values) else "") for i, h in enumerate(self._headers)}
        d["_row"] = row_number
        return d

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_pending_rows(self) -> list[dict]:
        """Return all rows where status == 'Pending'."""
        all_rows = self._sheet.get_all_values()
        headers = all_rows[0]
        status_col = headers.index("status")
        pending = []
        for i, row in enumerate(all_rows[1:], start=2):  # row 1 is header
            status = row[status_col] if status_col < len(row) else ""
            if status.strip() == "Pending":
                pending.append(self._row_to_dict(row, i))
        return pending

    def update_cell(self, row: int, column_name: str, value: str) -> None:
        """Update a single cell by row number and column name."""
        col = self._col(column_name)
        self._sheet.update_cell(row, col, value)

    def update_row(self, row: int, data: dict) -> None:
        """Update multiple columns in a row at once."""
        for column_name, value in data.items():
            if column_name.startswith("_"):
                continue
            if column_name in self._headers:
                self.update_cell(row, column_name, str(value) if value is not None else "")

    def set_status(self, row: int, status: str) -> None:
        self.update_cell(row, "status", status)
