"""
Report storage for ACE Audit AI.

Two interchangeable backends behind one API:

  * **Supabase (Postgres)** - used when SUPABASE_URL and SUPABASE_KEY are configured.
    History survives redeploys, so this is the right choice on Streamlit Community Cloud
    (whose local filesystem is wiped on every reboot).
  * **SQLite** - the fallback. Zero configuration, file at ACE_DB_PATH (default
    data/ace_audit.db). Fine for local use or a VPS with a persistent disk.

Both backends store and return the same record shape, so app.py does not care which is live.

Record shape
------------
    id, created_at (ISO string), title, label1, label2, period1, period2, currency,
    file1_name, file2_name, model, data1, data2, metrics, alerts, summary

Supabase table (run once in the SQL editor) - see README.md.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from finance import display_period

DB_PATH = Path(os.environ.get("ACE_DB_PATH", "data/ace_audit.db"))
TABLE = "reports"

# JSON-valued columns; stored as TEXT in SQLite and jsonb in Postgres.
_JSON_FIELDS = ("data1", "data2", "metrics", "alerts")
_PLAIN_FIELDS = ("created_at", "title", "label1", "label2", "period1", "period2",
                 "currency", "file1_name", "file2_name", "model", "summary")


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def _secret(name: str, default: str = "") -> str:
    """Environment variable first, then st.secrets (absent locally without secrets.toml)."""
    val = os.environ.get(name, "")
    if val:
        return val
    try:
        return str(st.secrets.get(name, default))
    except Exception:  # noqa: BLE001
        return default


def _supabase_config() -> tuple[str, str]:
    return _secret("SUPABASE_URL").rstrip("/"), _secret("SUPABASE_KEY")


def using_supabase() -> bool:
    url, key = _supabase_config()
    return bool(url and key)


@st.cache_resource(show_spinner=False)
def _client(url: str, key: str):
    from supabase import create_client  # imported lazily so SQLite users need no dependency
    return create_client(url, key)


def _sb():
    url, key = _supabase_config()
    return _client(url, key)


def backend_label(lang: str = "en") -> str:
    """Short description for the sidebar."""
    from i18n import t

    if using_supabase():
        url, _ = _supabase_config()
        host = url.replace("https://", "").replace("http://", "").split(".")[0]
        return t("storage_supabase", lang, host=host)
    return t("storage_sqlite", lang, path=DB_PATH)


class StorageError(RuntimeError):
    """Raised when the configured backend cannot be reached."""


# --------------------------------------------------------------------------- #
# SQLite backend
# --------------------------------------------------------------------------- #
def _sqlite_connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at   TEXT NOT NULL,
            title        TEXT NOT NULL,
            label1       TEXT, label2 TEXT,
            period1      TEXT, period2 TEXT,
            currency     TEXT,
            file1_name   TEXT, file2_name TEXT,
            model        TEXT,
            data1_json   TEXT NOT NULL,
            data2_json   TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            alerts_json  TEXT NOT NULL,
            summary      TEXT
        )
        """
    )
    return conn


def _sqlite_row_to_rec(row: sqlite3.Row) -> dict[str, Any]:
    rec = dict(row)
    for f in _JSON_FIELDS:
        raw = rec.pop(f"{f}_json", None)
        if raw is not None:
            rec[f] = json.loads(raw)
    return rec


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def save_report(rec: dict[str, Any]) -> int:
    """Insert one report; returns its new id."""
    if using_supabase():
        payload = {f: rec.get(f) for f in _PLAIN_FIELDS}
        payload.update({f: rec.get(f) for f in _JSON_FIELDS})
        try:
            res = _sb().table(TABLE).insert(payload).execute()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Could not write to Supabase: {exc}") from exc
        if not res.data:
            raise StorageError("Supabase accepted the insert but returned no row.")
        return int(res.data[0]["id"])

    with _sqlite_connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO reports (created_at, title, label1, label2, period1, period2, currency,
                                 file1_name, file2_name, model, data1_json, data2_json,
                                 metrics_json, alerts_json, summary)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rec["created_at"], rec["title"], rec["label1"], rec["label2"],
                rec["period1"], rec["period2"], rec["currency"],
                rec["file1_name"], rec["file2_name"], rec["model"],
                json.dumps(rec["data1"], ensure_ascii=False),
                json.dumps(rec["data2"], ensure_ascii=False),
                json.dumps(rec["metrics"], ensure_ascii=False, default=str),
                json.dumps(rec["alerts"], ensure_ascii=False),
                rec["summary"],
            ),
        )
        return int(cur.lastrowid)


def list_reports() -> list[dict[str, Any]]:
    """Newest first; only the columns the history picker needs."""
    cols = "id, created_at, title, period1, period2, currency"
    if using_supabase():
        try:
            res = _sb().table(TABLE).select(cols).order("id", desc=True).execute()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Could not read from Supabase: {exc}") from exc
        return [dict(r) for r in (res.data or [])]

    with _sqlite_connect() as conn:
        rows = conn.execute(f"SELECT {cols} FROM reports ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_report(report_id: int) -> dict[str, Any] | None:
    if using_supabase():
        try:
            res = _sb().table(TABLE).select("*").eq("id", report_id).limit(1).execute()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Could not read from Supabase: {exc}") from exc
        rows = res.data or []
        return dict(rows[0]) if rows else None

    with _sqlite_connect() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    return _sqlite_row_to_rec(row) if row else None


def delete_report(report_id: int) -> None:
    if using_supabase():
        try:
            _sb().table(TABLE).delete().eq("id", report_id).execute()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Could not delete from Supabase: {exc}") from exc
        return

    with _sqlite_connect() as conn:
        conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))


def trend_frame() -> pd.DataFrame:
    """One row per stored report, using each report's current-month figures."""
    if using_supabase():
        try:
            res = _sb().table(TABLE).select("id, created_at, title, period2, data2") \
                       .order("id", desc=False).execute()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Could not read from Supabase: {exc}") from exc
        rows = [dict(r) for r in (res.data or [])]
    else:
        with _sqlite_connect() as conn:
            raw = conn.execute(
                "SELECT id, created_at, title, period2, data2_json FROM reports ORDER BY id ASC"
            ).fetchall()
        rows = [{"id": r["id"], "created_at": r["created_at"], "title": r["title"],
                 "period2": r["period2"], "data2": json.loads(r["data2_json"])} for r in raw]

    out = []
    for r in rows:
        d = r.get("data2") or {}
        if isinstance(d, str):          # jsonb sometimes arrives as text
            d = json.loads(d)
        out.append({
            "Report #": r["id"],
            "Saved": str(r.get("created_at") or "")[:16],
            "Period": display_period(r.get("period2"), r.get("title") or f"Report {r['id']}"),
            "Income": float(d.get("total_income") or 0),
            "Expense": float(d.get("total_expense") or 0),
            "Net Profit": float(d.get("net_profit") or 0),
        })
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- #
# Backup / restore
# --------------------------------------------------------------------------- #
BACKUP_APP = "ace-audit-ai"
BACKUP_VERSION = 1
REQUIRED_FIELDS = ("title", "data1", "data2", "metrics", "alerts")


class BackupError(ValueError):
    """The uploaded file is not a usable ACE Audit AI backup."""


def all_reports() -> list[dict[str, Any]]:
    """Every stored report in full, oldest first."""
    if using_supabase():
        try:
            res = _sb().table(TABLE).select("*").order("id", desc=False).execute()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Could not read from Supabase: {exc}") from exc
        return [dict(r) for r in (res.data or [])]
    with _sqlite_connect() as conn:
        rows = conn.execute("SELECT * FROM reports ORDER BY id ASC").fetchall()
    return [_sqlite_row_to_rec(r) for r in rows]


def make_backup(exported_at: str) -> bytes:
    payload = {"app": BACKUP_APP, "version": BACKUP_VERSION, "exported_at": exported_at,
               "reports": all_reports()}
    return json.dumps(payload, ensure_ascii=False, indent=1, default=str).encode("utf-8")


def parse_backup(raw: bytes) -> list[dict[str, Any]]:
    """Validate a backup file and return its reports. Raises BackupError with a reason."""
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError("not_json") from exc
    if not isinstance(payload, dict) or payload.get("app") != BACKUP_APP:
        raise BackupError("wrong_app")
    if int(payload.get("version") or 0) > BACKUP_VERSION:
        raise BackupError("newer_version")
    reports = payload.get("reports")
    if not isinstance(reports, list):
        raise BackupError("no_reports")
    for r in reports:
        if not isinstance(r, dict) or any(f not in r for f in REQUIRED_FIELDS):
            raise BackupError("bad_report")
    return reports


def _fingerprint(rec: dict[str, Any]) -> tuple:
    return (str(rec.get("created_at") or "")[:19], rec.get("title"),
            rec.get("file1_name"), rec.get("file2_name"))


def restore_reports(reports: list[dict[str, Any]]) -> tuple[int, int]:
    """Insert reports that are not already stored. Returns (added, skipped).

    Reports get new ids; a report counts as already stored when its creation time, title
    and both file names match, so restoring the same backup twice adds nothing."""
    existing = {_fingerprint(r) for r in all_reports()}
    added = skipped = 0
    for rec in reports:
        fp = _fingerprint(rec)
        if fp in existing:
            skipped += 1
            continue
        clean = {f: rec.get(f) for f in _PLAIN_FIELDS + _JSON_FIELDS}
        clean["created_at"] = str(clean.get("created_at") or "")[:19] or "1970-01-01T00:00:00"
        save_report(clean)
        existing.add(fp)
        added += 1
    return added, skipped


def health_check() -> tuple[bool, str]:
    """Verify the active backend is reachable. Returns (ok, message)."""
    try:
        n = len(list_reports())
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    return True, f"{n} report(s) stored"
