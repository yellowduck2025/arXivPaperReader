"""Incremental CSV writer with resume support."""

import csv
import os
from pathlib import Path

from .models import CSV_COLUMNS, FILL_NONE


def init_csv(path: Path) -> None:
    """Create CSV with header if it doesn't already exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
            writer.writeheader()


def append_row(path: Path, row: dict[str, str]) -> None:
    """Append a single row to CSV, filling missing fields with 'none'."""
    sanitised = {}
    for col in CSV_COLUMNS:
        val = row.get(col, FILL_NONE)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            val = FILL_NONE
        # Join lists into semicolon-separated strings
        if isinstance(val, list):
            val = "; ".join(str(v) for v in val)
        sanitised[col] = str(val)

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writerow(sanitised)
        f.flush()
        os.fsync(f.fileno())


def read_existing_ids(path: Path) -> set[str]:
    """Return set of arxiv_ids already present in the CSV (for resume)."""
    if not path.exists():
        return set()
    ids: set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            aid = row.get("arxiv_id", "").strip()
            if aid and aid != FILL_NONE:
                ids.add(aid)
    return ids


def read_all_rows(path: Path) -> list[dict]:
    """Read all rows from the CSV into a list of dicts."""
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))
