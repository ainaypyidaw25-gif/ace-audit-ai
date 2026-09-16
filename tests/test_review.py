"""Human review of AI-extracted figures: live checks and the audit trail."""

from __future__ import annotations

import pandas as pd

from finance import (REVIEW_KEY, apply_review, check_statement, clean_items, public_statement,
                     review_changes)


def test_clean_items_accepts_editor_dataframe_and_drops_blank_rows():
    df = pd.DataFrame([{"category": "Rent", "amount": "1500"},
                       {"category": "", "amount": 99},
                       {"category": None, "amount": 5},
                       {"category": "Salaries", "amount": None}])
    assert clean_items(df) == [{"category": "Rent", "amount": 1500.0},
                               {"category": "Salaries", "amount": 0.0}]


def test_check_statement_consistent_sample_has_no_problems(feb):
    assert check_statement(feb, "Feb") == []


def test_check_statement_flags_each_kind_of_slip(feb):
    feb["net_profit"] = 1.0
    feb["total_income"] = 1.0
    feb.update(opening_balance=100.0, closing_balance=50.0)
    codes = {a["code"] for a in check_statement(feb, "Feb")}
    assert codes == {"net_mismatch", "income_items_mismatch", "balance_rollforward"}


def test_review_changes_reports_scalars_and_item_lists(feb):
    edited = {**feb, "total_expense": 44_000_000.0, "period": "Feb 2026",
              "expense_items": feb["expense_items"] + [{"category": "Tax", "amount": 400_000}]}
    changes = {c["field"]: c for c in review_changes(feb, edited)}
    assert set(changes) == {"total_expense", "period", "expense_items"}
    assert changes["total_expense"] == {"field": "total_expense", "from": 43_600_000.0, "to": 44_000_000.0}
    assert changes["expense_items"]["from"] == {"rows": 6, "total": 43_600_000.0}
    assert changes["expense_items"]["to"] == {"rows": 7, "total": 44_000_000.0}


def test_review_changes_ignores_row_order_and_number_types(feb):
    edited = {**feb, "income_items": list(reversed(feb["income_items"])),
              "total_income": int(feb["total_income"])}
    assert review_changes(feb, edited) == []


def test_apply_review_records_audit_and_normalizes(feb):
    edited = {**feb, "total_expense": "44000000",
              "income_items": pd.DataFrame(feb["income_items"] + [{"category": "", "amount": 1}])}
    out = apply_review(feb, edited, "2026-09-16T10:00:00")
    assert out["total_expense"] == 44_000_000.0
    assert len(out["income_items"]) == 3                      # blank editor row dropped
    audit = out[REVIEW_KEY]
    assert audit["edited"] is True and audit["reviewed_at"] == "2026-09-16T10:00:00"
    assert [c["field"] for c in audit["changes"]] == ["total_expense"]


def test_apply_review_unchanged_statement_is_marked_not_edited(feb):
    out = apply_review(feb, dict(feb), "t")
    assert out[REVIEW_KEY] == {"reviewed_at": "t", "edited": False, "changes": []}


def test_reviewing_twice_does_not_nest_audit_records(feb):
    once = apply_review(feb, dict(feb), "t1")
    twice = apply_review(once, {**once, "net_profit": 1.0}, "t2")
    assert REVIEW_KEY not in twice[REVIEW_KEY]
    assert [c["field"] for c in twice[REVIEW_KEY]["changes"]] == ["net_profit"]


def test_public_statement_hides_bookkeeping(feb):
    out = apply_review(feb, dict(feb), "t")
    assert REVIEW_KEY in out and REVIEW_KEY not in public_statement(out)
