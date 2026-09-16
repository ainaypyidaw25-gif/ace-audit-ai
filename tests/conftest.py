"""Shared fixtures. Tests never touch the network or the real .streamlit/secrets.toml."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JAN = {
    "period": "January 2026", "currency": "MMK",
    "total_income": 63_000_000.0, "total_expense": 31_200_000.0, "net_profit": 31_800_000.0,
    "opening_balance": 0.0, "closing_balance": 0.0,
    "income_items": [{"category": "Room Sales", "amount": 45_000_000},
                     {"category": "Restaurant", "amount": 12_000_000},
                     {"category": "Event Hall", "amount": 6_000_000}],
    "expense_items": [{"category": "Salaries", "amount": 18_000_000},
                      {"category": "Utilities", "amount": 4_500_000},
                      {"category": "Food & Beverage Cost", "amount": 5_000_000},
                      {"category": "Maintenance", "amount": 2_200_000},
                      {"category": "Marketing", "amount": 1_500_000}],
    "notes": "",
}
FEB = {
    "period": "February 2026", "currency": "MMK",
    "total_income": 54_500_000.0, "total_expense": 43_600_000.0, "net_profit": 10_900_000.0,
    "opening_balance": 0.0, "closing_balance": 0.0,
    "income_items": [{"category": "Room Sales", "amount": 39_000_000},
                     {"category": "Restaurant", "amount": 13_500_000},
                     {"category": "Event Hall", "amount": 2_000_000}],
    "expense_items": [{"category": "Salaries", "amount": 18_500_000},
                      {"category": "Utilities", "amount": 7_200_000},
                      {"category": "Food & Beverage Cost", "amount": 5_600_000},
                      {"category": "Maintenance", "amount": 6_800_000},
                      {"category": "Marketing", "amount": 1_500_000},
                      {"category": "Renovation", "amount": 4_000_000}],
    "notes": "",
}


@pytest.fixture
def jan() -> dict:
    return copy.deepcopy(JAN)


@pytest.fixture
def feb() -> dict:
    return copy.deepcopy(FEB)


@pytest.fixture
def report(jan, feb) -> dict:
    """A complete stored-report record built from the sample hotel statements."""
    from finance import build_alerts, compute_metrics

    metrics = compute_metrics(jan, feb, "January", "February")
    return {
        "id": 1, "created_at": "2026-09-16T09:00:00", "title": "Hotel Jan vs Feb 2026",
        "label1": "January", "label2": "February",
        "period1": jan["period"], "period2": feb["period"], "currency": "MMK",
        "file1_name": "jan.pdf", "file2_name": "feb.pdf", "model": "test-model",
        "data1": jan, "data2": feb, "metrics": metrics,
        "alerts": build_alerts(jan, feb, metrics, 30.0, "January", "February"),
        "summary": "- ဝင်ငွေ **13.5%** ကျဆင်းသည်\n- 🔴 Maintenance +209%",
    }


@pytest.fixture
def sqlite_storage(tmp_path, monkeypatch):
    """storage module pointed at a throwaway SQLite file with Supabase switched off."""
    import storage

    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(storage, "_secret", lambda name, default="": "")
    return storage
