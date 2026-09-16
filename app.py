"""
ACE Audit AI - Executive Financial Comparison Dashboard (single-user)
=====================================================================
- Passcode gate (one CEO user)
- Gemini extracts figures from PDF / image / Excel / CSV statements
- Add / subtract / multiply / divide comparisons + red-flag alerts
- Gemini writes a CEO bullet-point summary
- Every analysis is stored in Supabase (Postgres) when configured, else SQLite

Run:     streamlit run app.py
Config:  APP_PASSCODE, GEMINI_API_KEY and optionally SUPABASE_URL / SUPABASE_KEY
         via env vars or .streamlit/secrets.toml
"""

from __future__ import annotations

import hmac
import io
import json
import os
import re
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

import storage

# =========================================================================== #
# Configuration
# =========================================================================== #
st.set_page_config(
    page_title="ACE Audit AI - Executive Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

MODEL_OPTIONS = ["gemini-flash-latest", "gemini-3.8-flash", "gemini-3.6-flash",
                 "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                 "gemini-pro-latest"]
DEFAULT_ALERT_THRESHOLD = 30.0
ACCEPTED_TYPES = ["pdf", "png", "jpg", "jpeg", "webp", "xlsx", "xls", "csv"]


def secret(name: str, default: str = "") -> str:
    """Read from env first, then st.secrets (which may not exist locally)."""
    val = os.environ.get(name, "")
    if val:
        return val
    try:
        return str(st.secrets.get(name, default))
    except Exception:  # noqa: BLE001 - no secrets.toml locally
        return default


# =========================================================================== #
# Styling - clean executive look
# =========================================================================== #
st.markdown(
    """
<style>
  .block-container { padding-top: 1.5rem; max-width: 1300px; }
  h1, h2, h3 { letter-spacing: -0.01em; }
  .ace-hero {
    background: linear-gradient(135deg, #0f2a4a 0%, #1f6feb 100%);
    color: #fff; border-radius: 14px; padding: 1.4rem 1.8rem; margin-bottom: 1.2rem;
  }
  .ace-hero h1 { color: #fff; margin: 0; font-size: 1.9rem; }
  .ace-hero p  { margin: .3rem 0 0; opacity: .9; }
  .ace-card {
    background: var(--secondary-background-color); border-radius: 12px;
    padding: 1rem 1.2rem; border: 1px solid rgba(128,128,128,.15); height: 100%;
  }
  .ace-card .label { font-size: .8rem; text-transform: uppercase; letter-spacing: .06em; opacity: .7; }
  .ace-card .value { font-size: clamp(1.05rem, 1.9vw, 1.7rem); font-weight: 700;
                     margin: .15rem 0; white-space: nowrap; }
  .ace-card .delta { font-size: clamp(.75rem, 1vw, .9rem); font-weight: 600; white-space: nowrap; }
  .up   { color: #1a9c5b; }
  .down { color: #d63b3b; }
  .flat { color: #888; }
  .ace-summary { background: rgba(31,111,235,.06); border-left: 4px solid #1f6feb;
                 border-radius: 8px; padding: 1rem 1.2rem; }
  div[data-testid="stSidebar"] .stButton button { width: 100%; }
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================================== #
# Gemini - extraction
# =========================================================================== #
EXTRACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "period": {"type": "STRING", "description": "Statement period, e.g. 'January 2026'"},
        "currency": {"type": "STRING", "description": "Currency code or symbol, e.g. MMK, USD"},
        "total_income": {"type": "NUMBER"},
        "total_expense": {"type": "NUMBER"},
        "net_profit": {"type": "NUMBER", "description": "Net profit/loss as stated in the document"},
        "opening_balance": {"type": "NUMBER", "description": "0 if absent"},
        "closing_balance": {"type": "NUMBER", "description": "0 if absent"},
        "income_items": {
            "type": "ARRAY",
            "items": {"type": "OBJECT",
                      "properties": {"category": {"type": "STRING"}, "amount": {"type": "NUMBER"}},
                      "required": ["category", "amount"]},
        },
        "expense_items": {
            "type": "ARRAY",
            "items": {"type": "OBJECT",
                      "properties": {"category": {"type": "STRING"}, "amount": {"type": "NUMBER"}},
                      "required": ["category", "amount"]},
        },
        "notes": {"type": "STRING", "description": "Anomalies, unclear figures, assumptions"},
    },
    "required": ["period", "currency", "total_income", "total_expense", "net_profit",
                 "income_items", "expense_items"],
}

EXTRACTION_PROMPT = """You are a meticulous accountant. Read the attached financial statement
(PDF, scanned image, or tabular data) and extract the figures.

Rules:
- Amounts are plain numbers: no thousands separators, no currency symbols.
- Expenses are positive numbers.
- net_profit should equal total_income - total_expense. If the document states a different
  figure, report the document's figure and explain the mismatch in `notes`.
- Group line items into sensible categories (Sales, Service Income, Rent, Salaries, Utilities...).
- If a value is genuinely absent use 0 and say so in `notes`.
- Respond ONLY with JSON matching the schema.
"""


def file_to_part(name: str, data: bytes):
    n = name.lower()
    if n.endswith(".pdf"):
        return types.Part.from_bytes(data=data, mime_type="application/pdf")
    if n.endswith((".png", ".jpg", ".jpeg", ".webp")):
        mime = "image/png" if n.endswith(".png") else "image/webp" if n.endswith(".webp") else "image/jpeg"
        return types.Part.from_bytes(data=data, mime_type=mime)
    if n.endswith(".csv"):
        return "CSV data:\n\n" + pd.read_csv(io.BytesIO(data)).to_csv(index=False)
    if n.endswith((".xlsx", ".xls")):
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
        return "Excel workbook:\n\n" + "\n\n".join(
            f"### Sheet: {sn}\n{df.to_csv(index=False)}" for sn, df in sheets.items())
    raise ValueError(f"Unsupported file type: {name}")


def _clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    return re.sub(r"\s*```$", "", text)


@st.cache_data(show_spinner=False)
def extract_financials(api_key: str, model: str, file_bytes: bytes, file_name: str) -> dict[str, Any]:
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=model,
        contents=[EXTRACTION_PROMPT, file_to_part(file_name, file_bytes)],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EXTRACTION_SCHEMA,
            temperature=0.0,
        ),
    )
    d = json.loads(_clean_json(resp.text))
    for k in ("total_income", "total_expense", "net_profit", "opening_balance", "closing_balance"):
        d[k] = float(d.get(k) or 0)
    return d


def generate_ceo_summary(api_key: str, model: str, payload: dict[str, Any], language: str) -> str:
    """Second Gemini call: turn the computed metrics + alerts into a CEO briefing."""
    lang_line = ("Write in Burmese (Myanmar language), keeping financial terms in English in brackets."
                 if language == "Myanmar" else "Write in clear business English.")
    prompt = f"""You are the CFO briefing the CEO. Using ONLY the data below, write a concise executive
summary as Markdown bullet points (5-8 bullets). Cover: overall performance, biggest drivers of
change, cost concerns, and clear RED FLAGS (mark with 🔴). End with one line of recommended action.
Do not invent numbers. {lang_line}

DATA:
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
"""
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3),
    )
    return (resp.text or "").strip()


# =========================================================================== #
# Calculations
# =========================================================================== #
def friendly_error(exc: Exception, model: str) -> str:
    """Turn a raw Gemini API error into one line a non-engineer can act on."""
    msg = str(exc)
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return (f"Daily free-tier quota for **{model}** is used up. Pick a different model in the "
                "sidebar and try again, or add billing to your Google AI Studio project.")
    if "404" in msg or "NOT_FOUND" in msg:
        return (f"The model **{model}** is not available to this API key. Choose another model "
                "in the sidebar.")
    if "401" in msg or "403" in msg or "API_KEY" in msg.upper() or "PERMISSION" in msg.upper():
        return "The Gemini API key was rejected. Check the key in the sidebar or in Secrets."
    if "DeadlineExceeded" in msg or "timeout" in msg.lower():
        return "Gemini timed out. Try again, or use a smaller file."
    return f"Analysis failed: {msg[:300]}"


def pct_change(old: float, new: float) -> float | None:
    return None if old == 0 else (new - old) / abs(old) * 100.0


def safe_div(a: float, b: float) -> float | None:
    return None if b == 0 else a / b


def is_missing(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v))


def fmt_money(v: float | None, cur: str = "") -> str:
    return "-" if is_missing(v) else f"{v:,.0f} {cur}".strip()


def fmt_pct(v: float | None) -> str:
    return "-" if is_missing(v) else f"{v:+.1f}%"


def items_to_df(items: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(items or [], columns=["category", "amount"])
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
    totals = []
    for key, name in (("opening_balance", "Opening Balance"), ("total_income", "Total Income"),
                      ("total_expense", "Total Expense"), ("net_profit", "Net Profit"),
                      ("closing_balance", "Closing Balance")):
        totals.append({"Item": name, label1: d1[key], label2: d2[key],
                       "Net Variance": d2[key] - d1[key], "Combined": d1[key] + d2[key],
                       "Change %": pct_change(d1[key], d2[key])})

    def r(v, unit):
        return None if is_missing(v) else (v * 100 if unit == "%" else v)

    ratios = [
        {"Metric": "Income growth rate", "unit": "%", label1: None,
         label2: pct_change(d1["total_income"], d2["total_income"])},
        {"Metric": "Expense growth rate", "unit": "%", label1: None,
         label2: pct_change(d1["total_expense"], d2["total_expense"])},
        {"Metric": "Net profit growth rate", "unit": "%", label1: None,
         label2: pct_change(d1["net_profit"], d2["net_profit"])},
        {"Metric": "Profit margin (net / income)", "unit": "%",
         label1: r(safe_div(d1["net_profit"], d1["total_income"]), "%"),
         label2: r(safe_div(d2["net_profit"], d2["total_income"]), "%")},
        {"Metric": "Expense ratio (expense / income)", "unit": "%",
         label1: r(safe_div(d1["total_expense"], d1["total_income"]), "%"),
         label2: r(safe_div(d2["total_expense"], d2["total_income"]), "%")},
        {"Metric": "Income / Expense multiple", "unit": "x",
         label1: safe_div(d1["total_income"], d1["total_expense"]),
         label2: safe_div(d2["total_income"], d2["total_expense"])},
        {"Metric": "Income multiplier (M2 / M1)", "unit": "x", label1: None,
         label2: safe_div(d2["total_income"], d1["total_income"])},
    ]
    inc = compare_items(d1.get("income_items", []), d2.get("income_items", []), label1, label2)
    exp = compare_items(d1.get("expense_items", []), d2.get("expense_items", []), label1, label2)
    return {"totals": totals, "ratios": ratios,
            "income_by_category": inc.to_dict(orient="records"),
            "expense_by_category": exp.to_dict(orient="records")}


def build_alerts(d1: dict, d2: dict, metrics: dict, threshold: float) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    def add(sev, msg):
        alerts.append({"severity": sev, "message": msg})

    for label, d in (("Month 1", d1), ("Month 2", d2)):
        computed = d["total_income"] - d["total_expense"]
        if abs(computed - d["net_profit"]) > max(1.0, abs(d["net_profit"]) * 0.005):
            add("error", f"{label}: stated net profit {d['net_profit']:,.0f} ≠ income − expense "
                         f"{computed:,.0f} (gap {d['net_profit'] - computed:,.0f}).")
        inc_sum = items_to_df(d.get("income_items", []))["amount"].sum()
        exp_sum = items_to_df(d.get("expense_items", []))["amount"].sum()
        if inc_sum and abs(inc_sum - d["total_income"]) > max(1.0, abs(d["total_income"]) * 0.01):
            add("warning", f"{label}: income line items sum to {inc_sum:,.0f} but total income is "
                           f"{d['total_income']:,.0f}.")
        if exp_sum and abs(exp_sum - d["total_expense"]) > max(1.0, abs(d["total_expense"]) * 0.01):
            add("warning", f"{label}: expense line items sum to {exp_sum:,.0f} but total expense is "
                           f"{d['total_expense']:,.0f}.")
        ob, cb = d.get("opening_balance", 0) or 0, d.get("closing_balance", 0) or 0
        if (ob or cb) and abs(ob + d["net_profit"] - cb) > max(1.0, abs(cb) * 0.005):
            add("warning", f"{label}: opening + net profit = {ob + d['net_profit']:,.0f} but closing "
                           f"balance is {cb:,.0f}.")

    cb1, ob2 = d1.get("closing_balance", 0) or 0, d2.get("opening_balance", 0) or 0
    if cb1 and ob2 and abs(cb1 - ob2) > max(1.0, abs(cb1) * 0.005):
        add("error", f"Month 1 closing balance {cb1:,.0f} ≠ Month 2 opening balance {ob2:,.0f}.")

    if (d1.get("currency") or "").strip().upper() != (d2.get("currency") or "").strip().upper():
        add("warning", f"Currency differs: {d1.get('currency')} vs {d2.get('currency')}.")

    for key, name in (("total_income", "Total income"), ("total_expense", "Total expense"),
                      ("net_profit", "Net profit")):
        ch = pct_change(d1[key], d2[key])
        if ch is not None and abs(ch) >= threshold:
            add("warning", f"{name} changed {ch:+.1f}% (threshold {threshold:.0f}%).")

    if d2["net_profit"] < 0:
        add("error", f"Month 2 shows a NET LOSS of {d2['net_profit']:,.0f}.")
    exp_growth = pct_change(d1["total_expense"], d2["total_expense"])
    inc_growth = pct_change(d1["total_income"], d2["total_income"])
    if exp_growth is not None and inc_growth is not None and exp_growth > inc_growth + 10:
        add("warning", f"Expenses grew faster than income ({exp_growth:+.1f}% vs {inc_growth:+.1f}%).")

    for rows, kind in ((metrics["income_by_category"], "Income"), (metrics["expense_by_category"], "Expense")):
        for r in rows:
            ch = r["Change %"]
            if not is_missing(ch) and abs(ch) >= threshold:
                add("info", f"{kind} '{r['category']}' changed {ch:+.1f}%.")
            elif is_missing(ch) and r["Difference"] != 0:
                add("info", f"{kind} '{r['category']}' is new or disappeared (Δ {r['Difference']:,.0f}).")

    for label, d in (("Month 1", d1), ("Month 2", d2)):
        note = (d.get("notes") or "").strip()
        if note and note.lower() not in {"none", "n/a", "no anomalies", ""}:
            add("info", f"{label} AI notes: {note}")
    return alerts


# =========================================================================== #
# UI helpers
# =========================================================================== #
def metric_card(col, label: str, value: str, delta: float | None, pct: float | None,
                invert: bool = False, unit: str = "money") -> None:
    if is_missing(delta) or delta == 0:
        cls, arrow = "flat", "•"
    else:
        # Arrow shows the direction of the change; colour shows whether it is good news.
        arrow = "▲" if delta > 0 else "▼"
        cls = "up" if ((delta > 0) != invert) else "down"
    if is_missing(delta):
        delta_txt = ""
    elif unit == "pts":
        delta_txt = f"{arrow} {delta:+.1f} pts"
    else:
        delta_txt = f"{arrow} {delta:+,.0f} ({fmt_pct(pct)})"
    col.markdown(
        f'<div class="ace-card"><div class="label">{label}</div>'
        f'<div class="value">{value}</div><div class="delta {cls}">{delta_txt}</div></div>',
        unsafe_allow_html=True,
    )


def render_report(rec: dict[str, Any]) -> None:
    """Render a full report (used for both fresh analyses and stored history)."""
    d1, d2, m, alerts = rec["data1"], rec["data2"], rec["metrics"], rec["alerts"]
    l1, l2, cur = rec["label1"], rec["label2"], rec.get("currency") or ""

    st.caption(f"{l1}: {rec.get('period1') or '?'}  ·  {l2}: {rec.get('period2') or '?'}  ·  "
               f"Currency: {cur or '?'}  ·  Files: {rec.get('file1_name')}, {rec.get('file2_name')}")

    c1, c2, c3, c4 = st.columns(4)
    metric_card(c1, "Total Income", fmt_money(d2["total_income"], cur),
                d2["total_income"] - d1["total_income"], pct_change(d1["total_income"], d2["total_income"]))
    metric_card(c2, "Total Expense", fmt_money(d2["total_expense"], cur),
                d2["total_expense"] - d1["total_expense"], pct_change(d1["total_expense"], d2["total_expense"]),
                invert=True)
    metric_card(c3, "Net Profit", fmt_money(d2["net_profit"], cur),
                d2["net_profit"] - d1["net_profit"], pct_change(d1["net_profit"], d2["net_profit"]))
    pm1, pm2 = safe_div(d1["net_profit"], d1["total_income"]), safe_div(d2["net_profit"], d2["total_income"])
    metric_card(c4, "Profit Margin", "-" if is_missing(pm2) else f"{pm2 * 100:.1f}%",
                None if is_missing(pm1) or is_missing(pm2) else (pm2 - pm1) * 100, None, unit="pts")

    st.markdown("### 🧭 CEO Quick Summary")
    if rec.get("summary"):
        st.markdown(f'<div class="ace-summary">\n\n{rec["summary"]}\n\n</div>', unsafe_allow_html=True)
    else:
        st.info("No AI summary stored for this report.")

    st.markdown("### 🚨 Red Flags & Alerts")
    if not alerts:
        st.success("No discrepancies or abnormal changes detected.")
    for a in alerts:
        getattr(st, a["severity"])(a["message"])

    st.markdown("### ➕➖ Totals & Net Variance")
    totals_df = pd.DataFrame(m["totals"])
    st.dataframe(totals_df.style.format({l1: "{:,.0f}", l2: "{:,.0f}", "Net Variance": "{:+,.0f}",
                                         "Combined": "{:,.0f}", "Change %": fmt_pct}),
                 use_container_width=True, hide_index=True)

    st.markdown("### ✖️➗ Growth Rates & Ratios")
    def _fr(v, unit):
        return "-" if is_missing(v) else (f"{v:.1f}%" if unit == "%" else f"{v:.2f}x")
    ratio_df = pd.DataFrame([{"Metric": r["Metric"], l1: _fr(r.get(l1), r["unit"]),
                              l2: _fr(r.get(l2), r["unit"])} for r in m["ratios"]])
    st.dataframe(ratio_df, use_container_width=True, hide_index=True)

    st.markdown("### 📂 Category Breakdown")
    fmt_cat = {l1: "{:,.0f}", l2: "{:,.0f}", "Difference": "{:+,.0f}", "Change %": fmt_pct}
    t1, t2 = st.tabs(["Income by category", "Expense by category"])
    for tab, rows in ((t1, m["income_by_category"]), (t2, m["expense_by_category"])):
        with tab:
            df = pd.DataFrame(rows)
            if df.empty:
                st.info("No line items were extracted.")
            else:
                st.dataframe(df.style.format(fmt_cat), use_container_width=True, hide_index=True)
                st.bar_chart(df.set_index("category")[[l1, l2]])

    with st.expander("🔎 Raw AI extraction (JSON)"):
        a, b = st.columns(2)
        a.json(d1)
        b.json(d2)

    st.download_button("⬇️ Download report (JSON)",
                       data=json.dumps(rec, indent=2, ensure_ascii=False, default=str),
                       file_name=f"ace_report_{rec.get('id', 'new')}.json", mime="application/json",
                       key=f"dl_{rec.get('id', 'new')}")


# =========================================================================== #
# Passcode gate
# =========================================================================== #
def require_passcode() -> None:
    expected = secret("APP_PASSCODE")
    if not expected:
        st.error("APP_PASSCODE is not configured. Set it as an environment variable or in "
                 ".streamlit/secrets.toml, then restart the app.")
        st.stop()
    if st.session_state.get("authenticated"):
        return

    st.markdown('<div class="ace-hero"><h1>📊 ACE Audit AI</h1>'
                '<p>Executive Financial Comparison Dashboard · Restricted access</p></div>',
                unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        with st.form("login"):
            code = st.text_input("Enter passcode", type="password")
            ok = st.form_submit_button("Unlock", type="primary", use_container_width=True)
        if ok:
            if hmac.compare_digest(code.strip(), expected):
                st.session_state["authenticated"] = True
                st.rerun()
            st.error("Incorrect passcode.")
    st.stop()


require_passcode()

# =========================================================================== #
# Sidebar
# =========================================================================== #
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    api_key = st.text_input("Google Gemini API Key", type="password", value=secret("GEMINI_API_KEY"),
                            help="https://aistudio.google.com/app/apikey")
    model = st.selectbox("Gemini model", MODEL_OPTIONS, index=0)
    language = st.radio("Summary language", ["Myanmar", "English"], horizontal=True)
    threshold = st.slider("Red-flag threshold (% change)", 5.0, 100.0, DEFAULT_ALERT_THRESHOLD, 5.0)
    st.markdown("---")
    report_count_slot = st.empty()  # filled at the end so a fresh save is reflected immediately
    st.caption(f"Storage: {storage.backend_label()}")
    st.markdown("---")
    if st.button("🔒 Lock dashboard"):
        st.session_state.clear()
        st.rerun()

# =========================================================================== #
# Main
# =========================================================================== #
st.markdown('<div class="ace-hero"><h1>📊 ACE Audit AI</h1>'
            '<p>Executive Financial Comparison Dashboard · Powered by Google Gemini</p></div>',
            unsafe_allow_html=True)

tab_new, tab_history, tab_trend = st.tabs(["🆕 New Analysis", "📚 Previous Reports", "📈 Trend Viewer"])

# --------------------------------------------------------------------------- #
with tab_new:
    c1, c2 = st.columns(2)
    with c1:
        label1 = st.text_input("Previous month label", "Previous Month")
        file1 = st.file_uploader("Upload previous month statement", type=ACCEPTED_TYPES, key="f1")
    with c2:
        label2 = st.text_input("Current month label", "Current Month")
        file2 = st.file_uploader("Upload current month statement", type=ACCEPTED_TYPES, key="f2")
    title = st.text_input("Report title", f"Comparison {datetime.now():%Y-%m-%d}")

    if st.button("🔍 Analyze, Summarize & Save", type="primary", disabled=not (file1 and file2)):
        if not api_key:
            st.error("Enter your Gemini API key in the sidebar.")
            st.stop()
        try:
            with st.spinner(f"Extracting {label1}..."):
                d1 = extract_financials(api_key, model, file1.getvalue(), file1.name)
            with st.spinner(f"Extracting {label2}..."):
                d2 = extract_financials(api_key, model, file2.getvalue(), file2.name)
            metrics = compute_metrics(d1, d2, label1, label2)
            alerts = build_alerts(d1, d2, metrics, threshold)
            with st.spinner("Writing CEO summary..."):
                summary = generate_ceo_summary(
                    api_key, model,
                    {"labels": [label1, label2], "month1": d1, "month2": d2,
                     "totals": metrics["totals"], "ratios": metrics["ratios"], "alerts": alerts},
                    language,
                )
        except Exception as exc:  # noqa: BLE001
            st.error(friendly_error(exc, model))
            st.stop()

        rec = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "title": title.strip() or f"Comparison {datetime.now():%Y-%m-%d}",
            "label1": label1, "label2": label2,
            "period1": d1.get("period"), "period2": d2.get("period"),
            "currency": d2.get("currency") or d1.get("currency") or "",
            "file1_name": file1.name, "file2_name": file2.name, "model": model,
            "data1": d1, "data2": d2, "metrics": metrics, "alerts": alerts, "summary": summary,
        }
        try:
            rec["id"] = storage.save_report(rec)
            st.success(f"Saved as report #{rec['id']} — available under Previous Reports.")
        except Exception as exc:  # noqa: BLE001 - never lose an analysis that already cost API calls
            rec["id"] = "unsaved"
            st.warning(f"The analysis succeeded but could not be saved: {exc}\n\n"
                       "It is shown below — download the JSON to keep it.")
        st.session_state["last_report"] = rec

    if "last_report" in st.session_state:
        st.markdown("---")
        render_report(st.session_state["last_report"])

# --------------------------------------------------------------------------- #
with tab_history:
    try:
        reports = storage.list_reports()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Cannot reach report storage: {exc}")
        reports = []
    if not reports:
        st.info("No reports saved yet. Run an analysis in the New Analysis tab.")
    else:
        options = {f"#{r['id']} · {str(r['created_at'])[:16]} · {r['title']} "
                   f"({r['period1'] or '?'} → {r['period2'] or '?'})": r["id"] for r in reports}
        choice = st.selectbox("Select a past report", list(options.keys()))
        rid = options[choice]
        rec = storage.get_report(rid)
        if rec:
            hc1, hc2 = st.columns([6, 1])
            hc1.markdown(f"#### {rec['title']}")
            if hc2.button("🗑️ Delete", key=f"del_{rid}"):
                storage.delete_report(rid)
                st.session_state.pop("last_report", None)
                st.rerun()
            render_report(rec)

# --------------------------------------------------------------------------- #
with tab_trend:
    try:
        trend = storage.trend_frame()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Cannot reach report storage: {exc}")
        trend = pd.DataFrame()
    if len(trend) < 2:
        st.info("Trend lines appear once at least two reports are saved.")
    else:
        st.markdown("#### Income · Expense · Net Profit across saved reports (current-month figures)")
        st.line_chart(trend.set_index("Period")[["Income", "Expense", "Net Profit"]])
        trend["Profit Margin %"] = trend.apply(
            lambda r: (r["Net Profit"] / r["Income"] * 100) if r["Income"] else None, axis=1)
        st.dataframe(trend.style.format({"Income": "{:,.0f}", "Expense": "{:,.0f}",
                                         "Net Profit": "{:,.0f}", "Profit Margin %": "{:.1f}%"}),
                     use_container_width=True, hide_index=True)

# Sidebar counter is filled last so a report saved during this run is included.
try:
    report_count_slot.markdown(f"**📚 Stored reports:** {len(storage.list_reports())}")
except Exception as exc:  # noqa: BLE001
    report_count_slot.error(f"Storage unreachable: {str(exc)[:120]}")
