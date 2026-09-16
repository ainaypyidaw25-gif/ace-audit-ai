"""
ACE Audit AI - Executive Financial Comparison Dashboard (single-user)
=====================================================================
- Passcode gate (one CEO user)
- Gemini extracts figures from PDF / image / Excel / CSV statements
- Add / subtract / multiply / divide comparisons + red-flag alerts
- Gemini writes a CEO bullet-point summary, and answers follow-up questions
- Excel export for the board or the accountant
- Every analysis is stored in Supabase (Postgres) when configured, else SQLite

Run:     streamlit run app.py
Config:  APP_PASSCODE, GEMINI_API_KEY and optionally SUPABASE_URL / SUPABASE_KEY
         via env vars or .streamlit/secrets.toml

Module layout
    app.py      Streamlit UI only
    finance.py  calculations and alerts (pure, unit-tested)
    ai.py       Gemini extraction, summary, Q&A
    export.py   Excel workbook export
    storage.py  Supabase / SQLite persistence
"""

from __future__ import annotations

import hmac
import html
import json
import os
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

import ai
import export
import storage
from finance import (alert_counts, build_alerts, compute_metrics, display_period, distinct_labels,
                     fmt_money, fmt_pct, is_missing, pct_change, safe_div)

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


@st.cache_data(show_spinner=False)
def extract_cached(api_key: str, model: str, file_bytes: bytes, file_name: str) -> dict[str, Any]:
    """Cache per file content, so re-running an analysis does not spend quota twice."""
    return ai.extract_financials(api_key, model, file_bytes, file_name)


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
  .ace-q { font-weight: 600; margin-top: .6rem; }
  div[data-testid="stSidebar"] .stButton button { width: 100%; }
</style>
""",
    unsafe_allow_html=True,
)


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


def render_qa(rec: dict[str, Any], key_prefix: str, api_key: str, model: str, language: str) -> None:
    """Follow-up questions about one report, answered only from that report's data."""
    st.markdown("### 💬 Ask about this report")
    state_key = f"qa_{key_prefix}_{rec.get('id', 'new')}"
    history: list[dict[str, str]] = st.session_state.setdefault(state_key, [])

    for turn in history:
        if turn["role"] == "ceo":
            st.markdown(f'<div class="ace-q">🧑‍💼 {html.escape(turn["text"])}</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown(turn["text"])

    with st.form(f"form_{state_key}", clear_on_submit=True):
        question = st.text_input(
            "Question",
            placeholder="ဥပမာ - Maintenance စရိတ် ဘာကြောင့် တက်တာလဲ။ / Which cost grew the most?",
            label_visibility="collapsed",
        )
        c1, c2 = st.columns([1, 5])
        asked = c1.form_submit_button("Ask", type="primary", width="stretch")
        cleared = c2.form_submit_button("Clear conversation")

    if cleared:
        st.session_state[state_key] = []
        st.rerun()
    # Only a real submit may call Gemini. A text box can keep its value across st.rerun(),
    # so treating "non-empty" as "asked" re-sends the question on every run. Pressing Enter
    # submits through the form's first submit button, which is Ask, so `asked` covers it.
    if asked and question.strip():
        if not api_key:
            st.error("Enter your Gemini API key in the sidebar.")
            return
        with st.spinner("Thinking..."):
            try:
                answer = ai.answer_question(api_key, model, rec, question, history, language)
            except Exception as exc:  # noqa: BLE001
                st.error(ai.friendly_error(exc, model))
                return
        history.append({"role": "ceo", "text": question.strip()})
        history.append({"role": "cfo", "text": answer})
        st.rerun()


def render_report(rec: dict[str, Any], key_prefix: str, api_key: str, model: str,
                  language: str) -> None:
    """Render a full report. `key_prefix` keeps widget keys unique: Streamlit runs every
    tab in the same script pass, so the same report can be drawn twice in one run."""
    d1, d2, m, alerts = rec["data1"], rec["data2"], rec["metrics"], rec["alerts"]
    l1, l2, cur = rec["label1"], rec["label2"], rec.get("currency") or ""
    rid = rec.get("id", "new")

    st.caption(f"{l1}: {display_period(rec.get('period1'), '—')}  ·  "
               f"{l2}: {display_period(rec.get('period2'), '—')}  ·  "
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

    d_json, d_xlsx, _ = st.columns([1, 1, 2])
    try:
        d_xlsx.download_button("📗 Excel", data=export.build_excel_report(rec),
                               file_name=export.export_filename(rec),
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key=f"xlsx_{key_prefix}_{rid}", width="stretch")
    except Exception as exc:  # noqa: BLE001 - an export problem must not hide the report
        d_xlsx.warning(f"Excel export unavailable: {exc}")
    d_json.download_button("⬇️ JSON",
                           data=json.dumps(rec, indent=2, ensure_ascii=False, default=str),
                           file_name=f"ace_report_{rid}.json", mime="application/json",
                           key=f"dl_{key_prefix}_{rid}", width="stretch")

    st.markdown("### 🧭 CEO Quick Summary")
    if rec.get("summary"):
        st.markdown(f'<div class="ace-summary">\n\n{rec["summary"]}\n\n</div>', unsafe_allow_html=True)
    else:
        st.info("No AI summary stored for this report.")

    counts = alert_counts(alerts)
    st.markdown(f"### 🚨 Red Flags & Alerts  "
                f"<small>({counts['error']} critical · {counts['warning']} warnings · "
                f"{counts['info']} notes)</small>", unsafe_allow_html=True)
    if not alerts:
        st.success("No discrepancies or abnormal changes detected.")
    for a in alerts:
        getattr(st, a["severity"])(a["message"])

    render_qa(rec, key_prefix, api_key, model, language)

    st.markdown("### ➕➖ Totals & Net Variance")
    totals_df = pd.DataFrame(m["totals"])
    st.dataframe(totals_df.style.format({l1: "{:,.0f}", l2: "{:,.0f}", "Net Variance": "{:+,.0f}",
                                         "Combined": "{:,.0f}", "Change %": fmt_pct}),
                 width="stretch", hide_index=True)

    st.markdown("### ✖️➗ Growth Rates & Ratios")

    def _fr(v, unit):
        return "-" if is_missing(v) else (f"{v:.1f}%" if unit == "%" else f"{v:.2f}x")

    ratio_df = pd.DataFrame([{"Metric": r["Metric"], l1: _fr(r.get(l1), r["unit"]),
                              l2: _fr(r.get(l2), r["unit"])} for r in m["ratios"]])
    st.dataframe(ratio_df, width="stretch", hide_index=True)

    st.markdown("### 📂 Category Breakdown")
    fmt_cat = {l1: "{:,.0f}", l2: "{:,.0f}", "Difference": "{:+,.0f}", "Change %": fmt_pct}
    t1, t2 = st.tabs(["Income by category", "Expense by category"])
    for tab, rows in ((t1, m["income_by_category"]), (t2, m["expense_by_category"])):
        with tab:
            df = pd.DataFrame(rows)
            if df.empty:
                st.info("No line items were extracted.")
            else:
                st.dataframe(df.style.format(fmt_cat), width="stretch", hide_index=True)
                st.bar_chart(df.set_index("category")[[l1, l2]])

    with st.expander("🔎 Raw AI extraction (JSON)"):
        a, b = st.columns(2)
        a.json(d1)
        b.json(d2)


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
            ok = st.form_submit_button("Unlock", type="primary", width="stretch")
        if ok:
            if hmac.compare_digest(code.strip().encode(), expected.encode()):
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
    model = st.selectbox("Gemini model", MODEL_OPTIONS, index=0,
                         help="If a model's daily free quota runs out, pick another one.")
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
        label1_in = st.text_input("Previous month label", "Previous Month")
        file1 = st.file_uploader("Upload previous month statement", type=ACCEPTED_TYPES, key="f1")
    with c2:
        label2_in = st.text_input("Current month label", "Current Month")
        file2 = st.file_uploader("Upload current month statement", type=ACCEPTED_TYPES, key="f2")
    title = st.text_input("Report title", f"Comparison {datetime.now():%Y-%m-%d}")
    label1, label2 = distinct_labels(label1_in, label2_in)

    if st.button("🔍 Analyze, Summarize & Save", type="primary", disabled=not (file1 and file2)):
        if not api_key:
            st.error("Enter your Gemini API key in the sidebar.")
            st.stop()
        progress = st.progress(0, text=f"Reading {file1.name}...")
        try:
            d1 = extract_cached(api_key, model, file1.getvalue(), file1.name)
            progress.progress(35, text=f"Reading {file2.name}...")
            d2 = extract_cached(api_key, model, file2.getvalue(), file2.name)
            progress.progress(70, text="Calculating and writing the CEO summary...")
            metrics = compute_metrics(d1, d2, label1, label2)
            alerts = build_alerts(d1, d2, metrics, threshold, label1, label2)
            summary = ai.generate_ceo_summary(
                api_key, model,
                {"labels": [label1, label2], "month1": d1, "month2": d2,
                 "totals": metrics["totals"], "ratios": metrics["ratios"], "alerts": alerts},
                language,
            )
            progress.progress(100, text="Done")
        except Exception as exc:  # noqa: BLE001
            progress.empty()
            st.error(ai.friendly_error(exc, model))
            st.stop()
        progress.empty()

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
                       "It is shown below — download the Excel or JSON file to keep it.")
        st.session_state["last_report"] = rec

    if "last_report" in st.session_state:
        st.markdown("---")
        render_report(st.session_state["last_report"], "latest", api_key, model, language)

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
        options = {
            f"#{r['id']} · {str(r['created_at'])[:16].replace('T', ' ')} · {r['title']} "
            f"({display_period(r.get('period1'), '—')} → {display_period(r.get('period2'), '—')})": r["id"]
            for r in reports
        }
        choice = st.selectbox("Select a past report", list(options.keys()))
        rid = options[choice]
        rec = storage.get_report(rid)
        if rec:
            hc1, hc2 = st.columns([4, 1])
            hc1.markdown(f"#### {rec['title']}")
            confirm_key = f"confirm_del_{rid}"
            if not st.session_state.get(confirm_key):
                if hc2.button("🗑️ Delete", key=f"del_{rid}", width="stretch"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                st.warning(f"Delete report #{rid} “{rec['title']}” permanently? This cannot be undone.")
                y, n, _ = st.columns([1, 1, 4])
                if y.button("Yes, delete", type="primary", key=f"yes_{rid}", width="stretch"):
                    storage.delete_report(rid)
                    st.session_state.pop(confirm_key, None)
                    last = st.session_state.get("last_report") or {}
                    if last.get("id") == rid:
                        st.session_state.pop("last_report", None)
                    st.rerun()
                if n.button("Cancel", key=f"no_{rid}", width="stretch"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            render_report(rec, "history", api_key, model, language)

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
        # Report number keeps points distinct when two reports share a period name.
        trend["Point"] = trend.apply(lambda r: f"#{r['Report #']} {r['Period']}", axis=1)
        st.markdown("#### Income · Expense · Net Profit across saved reports (current-month figures)")
        st.line_chart(trend.set_index("Point")[["Income", "Expense", "Net Profit"]])
        trend["Profit Margin %"] = trend.apply(
            lambda r: (r["Net Profit"] / r["Income"] * 100) if r["Income"] else None, axis=1)
        st.dataframe(trend.drop(columns=["Point"]).style.format(
                         {"Income": "{:,.0f}", "Expense": "{:,.0f}", "Net Profit": "{:,.0f}",
                          "Profit Margin %": lambda v: "-" if is_missing(v) else f"{v:.1f}%"}),
                     width="stretch", hide_index=True)

# Sidebar counter is filled last so a report saved during this run is included.
try:
    report_count_slot.markdown(f"**📚 Stored reports:** {len(storage.list_reports())}")
except Exception as exc:  # noqa: BLE001
    report_count_slot.error(f"Storage unreachable: {str(exc)[:120]}")
