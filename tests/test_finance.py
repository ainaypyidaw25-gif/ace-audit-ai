from __future__ import annotations

import math

import pytest

from finance import (alert_counts, build_alerts, compare_items, compute_metrics, display_period,
                     distinct_labels, fmt_money, fmt_pct, normalize_statement, pct_change, safe_div)


# --------------------------------------------------------------------------- helpers
def test_pct_change_basic_and_zero_base():
    assert pct_change(100, 150) == pytest.approx(50.0)
    assert pct_change(100, 50) == pytest.approx(-50.0)
    assert pct_change(0, 50) is None


def test_pct_change_from_a_loss_uses_absolute_base():
    # Loss of 100 improving to a loss of 50 is a +50% improvement, not -50%.
    assert pct_change(-100, -50) == pytest.approx(50.0)


def test_safe_div():
    assert safe_div(10, 4) == 2.5
    assert safe_div(10, 0) is None


def test_formatters_handle_missing_values():
    assert fmt_money(1234567, "MMK") == "1,234,567 MMK"
    assert fmt_money(None) == "-"
    assert fmt_pct(12.345) == "+12.3%"
    assert fmt_pct(float("nan")) == "-"


def test_normalize_statement_coerces_bad_input():
    d = normalize_statement({"total_income": "1000", "total_expense": None, "net_profit": "oops",
                             "income_items": None})
    assert d["total_income"] == 1000.0
    assert d["total_expense"] == 0.0
    assert d["net_profit"] == 0.0
    assert d["income_items"] == [] and d["expense_items"] == []


@pytest.mark.parametrize("period, expected", [
    ("February 2026", "February 2026"),
    ("Unspecified", "Label"), ("unknown", "Label"), ("", "Label"), (None, "Label"),
    ("Not specified", "Label"),
])
def test_display_period_falls_back_to_label(period, expected):
    assert display_period(period, "Label") == expected


def test_distinct_labels_prevents_column_collision():
    assert distinct_labels("Jan", "Feb") == ("Jan", "Feb")
    a, b = distinct_labels("Month", "Month")
    assert a != b
    assert distinct_labels("", "  ") == ("Previous", "Current")


# --------------------------------------------------------------------------- comparisons
def test_compare_items_merges_new_and_removed_categories():
    df = compare_items([{"category": "Rent", "amount": 100}, {"category": "Old", "amount": 50}],
                       [{"category": "Rent", "amount": 150}, {"category": "New", "amount": 30}],
                       "A", "B")
    rows = {r["category"]: r for r in df.to_dict(orient="records")}
    assert rows["Rent"]["Difference"] == 50 and rows["Rent"]["Change %"] == pytest.approx(50)
    assert rows["Old"]["B"] == 0 and rows["Old"]["Change %"] == pytest.approx(-100)
    assert rows["New"]["A"] == 0 and (rows["New"]["Change %"] is None
                                      or math.isnan(rows["New"]["Change %"]))


def test_compare_items_sums_duplicate_categories():
    df = compare_items([{"category": "Rent", "amount": 100}, {"category": " Rent ", "amount": 20}],
                       [], "A", "B")
    assert df.loc[df.category == "Rent", "A"].item() == 120


def test_compute_metrics_on_hotel_sample(jan, feb):
    m = compute_metrics(jan, feb, "Jan", "Feb")
    totals = {t["Item"]: t for t in m["totals"]}
    assert totals["Total Income"]["Net Variance"] == -8_500_000
    assert totals["Total Income"]["Combined"] == 117_500_000
    assert totals["Net Profit"]["Change %"] == pytest.approx(-65.72, abs=0.01)

    ratios = {r["Metric"]: r for r in m["ratios"]}
    assert ratios["Profit margin (net / income)"]["Jan"] == pytest.approx(50.48, abs=0.01)
    assert ratios["Profit margin (net / income)"]["Feb"] == pytest.approx(20.0, abs=0.01)
    assert ratios["Expense ratio (expense / income)"]["Feb"] == pytest.approx(80.0, abs=0.01)
    assert ratios["Income / Expense multiple"]["Jan"] == pytest.approx(2.019, abs=0.001)

    assert len(m["income_by_category"]) == 3
    assert len(m["expense_by_category"]) == 6


def test_compute_metrics_zero_income_does_not_crash(jan, feb):
    feb["total_income"] = 0.0
    m = compute_metrics(jan, feb, "Jan", "Feb")
    ratios = {r["Metric"]: r for r in m["ratios"]}
    assert ratios["Profit margin (net / income)"]["Feb"] is None


# --------------------------------------------------------------------------- alerts
def _messages(alerts):
    return [a["message"] for a in alerts]


def test_hotel_sample_alerts(jan, feb):
    m = compute_metrics(jan, feb, "January", "February")
    alerts = build_alerts(jan, feb, m, 30.0, "January", "February")
    msgs = " | ".join(_messages(alerts))
    assert "Total expense changed +39.7%" in msgs
    assert "Net profit changed -65.7%" in msgs
    assert "Expenses grew faster than income" in msgs
    assert "Maintenance' changed +209.1%" in msgs
    assert "'Renovation' is new in February" in msgs
    # user labels are used, not hard-coded Month 1/2
    assert "Month 1" not in msgs and "Month 2" not in msgs
    assert alert_counts(alerts)["error"] == 0


def test_alert_when_net_profit_does_not_add_up(jan, feb):
    feb["net_profit"] = 12_000_000.0  # income − expense is 10.9M
    m = compute_metrics(jan, feb, "A", "B")
    alerts = build_alerts(jan, feb, m, 30.0, "A", "B")
    errors = [a for a in alerts if a["severity"] == "error"]
    assert any("B: stated net profit 12,000,000" in a["message"] for a in errors)


def test_alert_when_line_items_do_not_sum_to_total(jan, feb):
    feb["total_expense"] = 50_000_000.0
    feb["net_profit"] = feb["total_income"] - feb["total_expense"]
    m = compute_metrics(jan, feb, "A", "B")
    msgs = " | ".join(_messages(build_alerts(jan, feb, m, 30.0, "A", "B")))
    assert "expense line items sum to 43,600,000 but total expense is 50,000,000" in msgs


def test_alert_on_balance_breaks(jan, feb):
    jan.update(opening_balance=100_000_000.0, closing_balance=131_800_000.0)
    feb.update(opening_balance=120_000_000.0, closing_balance=130_900_000.0)
    m = compute_metrics(jan, feb, "A", "B")
    msgs = " | ".join(_messages(build_alerts(jan, feb, m, 30.0, "A", "B")))
    assert "A closing balance 131,800,000 ≠ B opening balance 120,000,000" in msgs


def test_alert_on_loss_and_currency_mismatch(jan, feb):
    feb.update(total_expense=60_000_000.0, net_profit=-5_500_000.0, currency="USD",
               expense_items=[{"category": "All", "amount": 60_000_000}])
    m = compute_metrics(jan, feb, "A", "B")
    alerts = build_alerts(jan, feb, m, 30.0, "A", "B")
    msgs = " | ".join(_messages(alerts))
    assert "B shows a NET LOSS of -5,500,000" in msgs
    assert "Currency differs: MMK vs USD" in msgs


def test_disappeared_category_is_reported_as_disappeared(jan, feb):
    feb["income_items"] = [i for i in feb["income_items"] if i["category"] != "Event Hall"]
    feb["total_income"] = 52_500_000.0
    feb["net_profit"] = feb["total_income"] - feb["total_expense"]
    m = compute_metrics(jan, feb, "A", "B")
    msgs = " | ".join(_messages(build_alerts(jan, feb, m, 30.0, "A", "B")))
    assert "Income 'Event Hall' disappeared in B (was 6,000,000)" in msgs


def test_threshold_controls_swing_alerts(jan, feb):
    m = compute_metrics(jan, feb, "A", "B")
    loose = build_alerts(jan, feb, m, 100.0, "A", "B")
    strict = build_alerts(jan, feb, m, 5.0, "A", "B")
    assert len(strict) > len(loose)
