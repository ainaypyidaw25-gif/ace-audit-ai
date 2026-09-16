"""
Pure financial calculations for ACE Audit AI.

No Streamlit and no network calls here, so everything in this module is unit-tested
directly (see tests/test_finance.py).

A statement dict ("d") is what Gemini extraction returns:
    period, currency, total_income, total_expense, net_profit,
    opening_balance, closing_balance, income_items, expense_items, notes
where *_items are lists of {"category": str, "amount": number}.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

NUMERIC_FIELDS = ("total_income", "total_expense", "net_profit", "opening_balance", "closing_balance")
UNKNOWN_PERIODS = {"", "unknown", "unspecified", "not specified", "n/a", "none", "null"}


# --------------------------------------------------------------------------- #
# Small numeric helpers
# --------------------------------------------------------------------------- #
def pct_change(old: float, new: float) -> float | None:
    """Percent change from old to new; None when old is zero (undefined)."""
    return None if old == 0 else (new - old) / abs(old) * 100.0


def safe_div(a: float, b: float) -> float | None:
    return None if b == 0 else a / b


def is_missing(v: Any) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v))


def fmt_money(v: float | None, cur: str = "") -> str:
    return "-" if is_missing(v) else f"{v:,.0f} {cur}".strip()


def fmt_pct(v: float | None) -> str:
    return "-" if is_missing(v) else f"{v:+.1f}%"


def normalize_statement(d: dict[str, Any]) -> dict[str, Any]:
    """Coerce numeric fields to float and item lists to lists, tolerating None/strings."""
    out = dict(d or {})
    for k in NUMERIC_FIELDS:
        try:
            out[k] = float(out.get(k) or 0)
        except (TypeError, ValueError):
            out[k] = 0.0
    for k in ("income_items", "expense_items"):
        out[k] = list(out.get(k) or [])
    return out


def display_period(period: str | None, fallback: str) -> str:
    """Use the extracted period when it is real, otherwise the user's label."""
    p = (period or "").strip()
    return fallback if p.lower() in UNKNOWN_PERIODS else p


def distinct_labels(label1: str, label2: str) -> tuple[str, str]:
    """Column names must differ, or the comparison tables silently merge into one column."""
    l1 = (label1 or "").strip() or "Previous"
    l2 = (label2 or "").strip() or "Current"
    if l1 == l2:
        l1, l2 = f"{l1} (1)", f"{l2} (2)"
    return l1, l2


# --------------------------------------------------------------------------- #
# Comparisons
# --------------------------------------------------------------------------- #
def items_to_df(items: list[dict] | None) -> pd.DataFrame:
    df = pd.DataFrame(items or [], columns=["category", "amount"])
    df["category"] = df["category"].astype(str).str.strip()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df.groupby("category", as_index=False)["amount"].sum()


def compare_items(items1, items2, label1: str, label2: str) -> pd.DataFrame:
    df1 = items_to_df(items1).rename(columns={"amount": label1})
    df2 = items_to_df(items2).rename(columns={"amount": label2})
    m = df1.merge(df2, on="category", how="outer").fillna(0.0)
    m["Difference"] = m[label2] - m[label1]
    m["Change %"] = m.apply(lambda r: pct_change(r[label1], r[label2]), axis=1)
    return m.sort_values(label2, ascending=False).reset_index(drop=True)


def compute_metrics(d1: dict, d2: dict, label1: str, label2: str) -> dict[str, Any]:
    """Totals (add/subtract), ratios (multiply/divide) and per-category comparisons."""
    totals = []
    for key, name in (("opening_balance", "Opening Balance"), ("total_income", "Total Income"),
                      ("total_expense", "Total Expense"), ("net_profit", "Net Profit"),
                      ("closing_balance", "Closing Balance")):
        totals.append({"Item": name, label1: d1[key], label2: d2[key],
                       "Net Variance": d2[key] - d1[key], "Combined": d1[key] + d2[key],
                       "Change %": pct_change(d1[key], d2[key])})

    def as_pct(v):
        return None if is_missing(v) else v * 100

    ratios = [
        {"Metric": "Income growth rate", "unit": "%", label1: None,
         label2: pct_change(d1["total_income"], d2["total_income"])},
        {"Metric": "Expense growth rate", "unit": "%", label1: None,
         label2: pct_change(d1["total_expense"], d2["total_expense"])},
        {"Metric": "Net profit growth rate", "unit": "%", label1: None,
         label2: pct_change(d1["net_profit"], d2["net_profit"])},
        {"Metric": "Profit margin (net / income)", "unit": "%",
         label1: as_pct(safe_div(d1["net_profit"], d1["total_income"])),
         label2: as_pct(safe_div(d2["net_profit"], d2["total_income"]))},
        {"Metric": "Expense ratio (expense / income)", "unit": "%",
         label1: as_pct(safe_div(d1["total_expense"], d1["total_income"])),
         label2: as_pct(safe_div(d2["total_expense"], d2["total_income"]))},
        {"Metric": "Income / Expense multiple", "unit": "x",
         label1: safe_div(d1["total_income"], d1["total_expense"]),
         label2: safe_div(d2["total_income"], d2["total_expense"])},
        {"Metric": "Income multiplier (current / previous)", "unit": "x", label1: None,
         label2: safe_div(d2["total_income"], d1["total_income"])},
    ]
    inc = compare_items(d1.get("income_items", []), d2.get("income_items", []), label1, label2)
    exp = compare_items(d1.get("expense_items", []), d2.get("expense_items", []), label1, label2)
    return {"totals": totals, "ratios": ratios,
            "income_by_category": inc.to_dict(orient="records"),
            "expense_by_category": exp.to_dict(orient="records")}


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
def _tol(reference: float, rel: float) -> float:
    """Tolerance for 'these should match': at least 1 unit, or rel of the reference."""
    return max(1.0, abs(reference) * rel)


def _make_alert(sev: str, code: str, **params: Any) -> dict[str, Any]:
    from i18n import EN, render_alert  # local import: i18n has no dependencies, avoids cycles

    params = {k: str(v) for k, v in params.items()}
    return {"severity": sev, "code": code, "params": params, "message": render_alert(code, params, EN)}


def _money(v: float) -> str:
    return f"{v:,.0f}"


def check_statement(d: dict, label: str) -> list[dict[str, Any]]:
    """Checks that need only one statement: net = income − expense, line items add up to
    the totals, and opening balance + net profit = closing balance."""
    out: list[dict[str, Any]] = []
    computed = d["total_income"] - d["total_expense"]
    if abs(computed - d["net_profit"]) > _tol(d["net_profit"], 0.005):
        out.append(_make_alert("error", "net_mismatch", label=label, stated=_money(d["net_profit"]),
                               computed=_money(computed), gap=_money(d["net_profit"] - computed)))
    inc_sum = items_to_df(d.get("income_items")).amount.sum()
    exp_sum = items_to_df(d.get("expense_items")).amount.sum()
    if inc_sum and abs(inc_sum - d["total_income"]) > _tol(d["total_income"], 0.01):
        out.append(_make_alert("warning", "income_items_mismatch", label=label, items=_money(inc_sum),
                               total=_money(d["total_income"])))
    if exp_sum and abs(exp_sum - d["total_expense"]) > _tol(d["total_expense"], 0.01):
        out.append(_make_alert("warning", "expense_items_mismatch", label=label, items=_money(exp_sum),
                               total=_money(d["total_expense"])))
    ob, cb = d.get("opening_balance") or 0, d.get("closing_balance") or 0
    if (ob or cb) and abs(ob + d["net_profit"] - cb) > _tol(cb, 0.005):
        out.append(_make_alert("warning", "balance_rollforward", label=label,
                               expected=_money(ob + d["net_profit"]), closing=_money(cb)))
    return out


def build_alerts(d1: dict, d2: dict, metrics: dict, threshold: float,
                 label1: str = "Month 1", label2: str = "Month 2") -> list[dict[str, Any]]:
    """Return alerts as {"severity", "code", "params", "message"}.

    `code` and `params` let the UI re-render an alert in any language (see i18n.py);
    `message` is the English text, kept for Excel export fallbacks and older reports.
    Numbers in `params` are pre-formatted strings so every language shows the same figures.
    """
    alerts: list[dict[str, Any]] = []

    def add(sev: str, code: str, **params: Any) -> None:
        alerts.append(_make_alert(sev, code, **params))

    money = _money

    # Internal consistency of each statement
    alerts.extend(check_statement(d1, label1))
    alerts.extend(check_statement(d2, label2))

    # Continuity between the two statements
    cb1, ob2 = d1.get("closing_balance") or 0, d2.get("opening_balance") or 0
    if cb1 and ob2 and abs(cb1 - ob2) > _tol(cb1, 0.005):
        add("error", "balance_break", label1=label1, label2=label2, closing=money(cb1), opening=money(ob2))

    c1 = (d1.get("currency") or "").strip().upper()
    c2 = (d2.get("currency") or "").strip().upper()
    if c1 and c2 and c1 != c2:
        add("warning", "currency_mismatch", c1=d1.get("currency"), c2=d2.get("currency"))

    # Abnormal swings
    for key in ("total_income", "total_expense", "net_profit"):
        ch = pct_change(d1[key], d2[key])
        if ch is not None and abs(ch) >= threshold:
            add("warning", "total_swing", metric=key, change=f"{ch:+.1f}%", threshold=f"{threshold:.0f}")

    if d2["net_profit"] < 0:
        add("error", "net_loss", label=label2, amount=money(d2["net_profit"]))
    exp_growth = pct_change(d1["total_expense"], d2["total_expense"])
    inc_growth = pct_change(d1["total_income"], d2["total_income"])
    if exp_growth is not None and inc_growth is not None and exp_growth > inc_growth + 10:
        add("warning", "expense_outpaces_income", exp=f"{exp_growth:+.1f}%", inc=f"{inc_growth:+.1f}%")

    for rows, kind in ((metrics["income_by_category"], "income"),
                       (metrics["expense_by_category"], "expense")):
        for r in rows:
            ch = r["Change %"]
            if not is_missing(ch) and abs(ch) >= threshold:
                if r[label2] == 0:
                    add("info", "category_gone", kind=kind, category=r["category"], label=label2,
                        was=money(r[label1]))
                else:
                    add("info", "category_swing", kind=kind, category=r["category"], change=f"{ch:+.1f}%")
            elif is_missing(ch) and r["Difference"] != 0:
                add("info", "category_new", kind=kind, category=r["category"], label=label2,
                    amount=money(r[label2]))

    for label, d in ((label1, d1), (label2, d2)):
        note = (d.get("notes") or "").strip()
        if note and note.lower() not in {"none", "n/a", "no anomalies"}:
            add("info", "ai_note", label=label, note=note)
    return alerts


def alert_counts(alerts: list[dict[str, str]]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for a in alerts:
        counts[a.get("severity", "info")] = counts.get(a.get("severity", "info"), 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# Human review of AI-extracted figures
# --------------------------------------------------------------------------- #
REVIEW_KEY = "_review"
SCALAR_FIELDS = ("period", "currency") + NUMERIC_FIELDS


def clean_items(items: Any) -> list[dict[str, Any]]:
    """Rows from an editable table -> [{"category", "amount"}], dropping blank rows."""
    if isinstance(items, pd.DataFrame):
        items = items.to_dict(orient="records")
    out = []
    for row in items or []:
        cat = str(row.get("category") or "").strip()
        try:
            amount = float(row.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if cat and cat.lower() != "nan":
            out.append({"category": cat, "amount": amount})
    return out


def _items_signature(items: list[dict] | None) -> list[tuple[str, float]]:
    return sorted((str(i.get("category", "")).strip(), round(float(i.get("amount") or 0), 2))
                  for i in clean_items(items))


def review_changes(original: dict, edited: dict) -> list[dict[str, Any]]:
    """What a reviewer changed, field by field. Item lists are compared as a whole and
    reported as count and total, which is what an auditor needs to see."""
    changes: list[dict[str, Any]] = []
    for f in SCALAR_FIELDS:
        a, b = original.get(f), edited.get(f)
        if f in NUMERIC_FIELDS:
            a, b = float(a or 0), float(b or 0)
            if abs(a - b) > 0.005:
                changes.append({"field": f, "from": a, "to": b})
        elif (a or "") != (b or ""):
            changes.append({"field": f, "from": a, "to": b})
    for f in ("income_items", "expense_items"):
        a, b = _items_signature(original.get(f)), _items_signature(edited.get(f))
        if a != b:
            changes.append({"field": f,
                            "from": {"rows": len(a), "total": sum(x[1] for x in a)},
                            "to": {"rows": len(b), "total": sum(x[1] for x in b)}})
    return changes


def apply_review(original: dict, edited: dict, reviewed_at: str) -> dict[str, Any]:
    """The statement to save: edited figures plus an audit record of what changed."""
    body = {k: v for k, v in edited.items() if k != REVIEW_KEY}
    # Clean item tables first: an editor DataFrame has no truth value, so normalize_statement's
    # `items or []` would raise on it.
    for f in ("income_items", "expense_items"):
        body[f] = clean_items(body.get(f))
    out = normalize_statement(body)
    base = {k: v for k, v in original.items() if k != REVIEW_KEY}
    changes = review_changes(base, out)
    out[REVIEW_KEY] = {"reviewed_at": reviewed_at, "edited": bool(changes), "changes": changes}
    return out


def public_statement(d: dict) -> dict:
    """Statement without internal bookkeeping keys, for prompts and summaries."""
    return {k: v for k, v in (d or {}).items() if not str(k).startswith("_")}
