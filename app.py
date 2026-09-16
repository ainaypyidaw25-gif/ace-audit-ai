"""
ACE Audit AI - Executive Financial Comparison Dashboard (single-user)
=====================================================================
- Passcode gate (one CEO user)
- Myanmar and English interface (Myanmar by default)
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
    i18n.py     Myanmar / English text
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
import uuid
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

import ai
import export
import storage
from finance import (REVIEW_KEY, alert_counts, apply_review, build_alerts, check_statement,
                     clean_items, compute_metrics, display_period, distinct_labels, fmt_money,
                     fmt_pct, is_missing, items_to_df, pct_change, public_statement, review_changes,
                     safe_div)
from i18n import AI_LANGUAGE, LANGUAGES, MY, alert_text, item_name, ratio_name, t

# =========================================================================== #
# Configuration
# =========================================================================== #
st.set_page_config(
    page_title="ACE Audit AI",
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
  .ace-card .label { font-size: .8rem; letter-spacing: .03em; opacity: .7; }
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


def uploader_text_css(lang: str) -> None:
    """Streamlit's file uploader has fixed English text and no option to change it, so hide
    those spans and draw translated text with CSS pseudo-elements instead."""
    def css_str(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    st.markdown(f"""
<style>
  [data-testid="stFileUploaderDropzoneInstructions"] > div > span {{ display: none; }}
  [data-testid="stFileUploaderDropzoneInstructions"] > div::before {{
    content: {css_str(t("upload_drop", lang))}; display: block; margin-bottom: .25rem; }}
  [data-testid="stFileUploaderDropzoneInstructions"] > div::after {{
    content: {css_str(t("upload_limit", lang))}; display: block; font-size: .8rem; opacity: .65; }}
  [data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-secondary"] {{ font-size: 0; }}
  [data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-secondary"]::after {{
    content: {css_str(t("upload_browse", lang))}; font-size: 1rem; }}
</style>
""", unsafe_allow_html=True)


def hero(lang: str, tagline_key: str) -> None:
    st.markdown(f'<div class="ace-hero"><h1>📊 ACE Audit AI</h1>'
                f'<p>{t("subtitle", lang)} · {t(tagline_key, lang)}</p></div>',
                unsafe_allow_html=True)


# =========================================================================== #
# UI helpers
# =========================================================================== #
def metric_card(col, label: str, value: str, delta: float | None, pct: float | None,
                invert: bool = False, pts_label: str | None = None) -> None:
    if is_missing(delta) or delta == 0:
        cls, arrow = "flat", "•"
    else:
        # Arrow shows the direction of the change; colour shows whether it is good news.
        arrow = "▲" if delta > 0 else "▼"
        cls = "up" if ((delta > 0) != invert) else "down"
    if is_missing(delta):
        delta_txt = ""
    elif pts_label:
        delta_txt = f"{arrow} {delta:+.1f} {pts_label}"
    else:
        delta_txt = f"{arrow} {delta:+,.0f} ({fmt_pct(pct)})"
    col.markdown(
        f'<div class="ace-card"><div class="label">{label}</div>'
        f'<div class="value">{value}</div><div class="delta {cls}">{delta_txt}</div></div>',
        unsafe_allow_html=True,
    )


def render_qa(rec: dict[str, Any], key_prefix: str, api_key: str, model: str, lang: str) -> None:
    """Follow-up questions about one report, answered only from that report's data."""
    st.markdown(f"### {t('qa_h', lang)}")
    state_key = f"qa_{key_prefix}_{rec.get('id', 'new')}"
    history: list[dict[str, str]] = st.session_state.setdefault(state_key, [])

    for turn in history:
        if turn["role"] == "ceo":
            st.markdown(f'<div class="ace-q">🧑‍💼 {html.escape(turn["text"])}</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown(turn["text"])

    with st.form(f"form_{state_key}", clear_on_submit=True):
        question = st.text_input(t("qa_label", lang), placeholder=t("qa_placeholder", lang),
                                 label_visibility="collapsed", key=f"q_{state_key}")
        c1, c2 = st.columns([1, 4])
        asked = c1.form_submit_button(t("ask", lang), type="primary", width="stretch",
                                      key=f"ask_{state_key}")
        cleared = c2.form_submit_button(t("clear_chat", lang), key=f"clear_{state_key}")

    if cleared:
        st.session_state[state_key] = []
        st.rerun()
    # Only a real submit may call Gemini. A text box can keep its value across st.rerun(),
    # so treating "non-empty" as "asked" re-sends the question on every run. Pressing Enter
    # submits through the form's first submit button, which is Ask, so `asked` covers it.
    if asked and question.strip():
        if not api_key:
            st.error(t("need_key", lang))
            return
        with st.spinner(t("thinking", lang)):
            try:
                answer = ai.answer_question(api_key, model, rec, question, history, AI_LANGUAGE[lang])
            except Exception as exc:  # noqa: BLE001
                st.error(ai.friendly_error(exc, model, lang))
                return
        history.append({"role": "ceo", "text": question.strip()})
        history.append({"role": "cfo", "text": answer})
        st.rerun()


FIELD_KEYS = {"period": "f_period", "currency": "f_currency", "total_income": "f_total_income",
              "total_expense": "f_total_expense", "net_profit": "f_net_profit",
              "opening_balance": "f_opening_balance", "closing_balance": "f_closing_balance",
              "income_items": "f_income_items", "expense_items": "f_expense_items"}


def _fmt_change_value(v: Any, lang: str) -> str:
    if isinstance(v, dict):
        return t("rows_total", lang, rows=v.get("rows", 0), total=fmt_money(v.get("total")))
    if isinstance(v, (int, float)):
        return fmt_money(v)
    return str(v if v not in (None, "") else "—")


def render_review_note(rec: dict[str, Any], lang: str) -> None:
    """Audit trail: show which figures a person corrected before the report was saved."""
    lines = []
    for label, d in ((rec["label1"], rec["data1"]), (rec["label2"], rec["data2"])):
        for c in ((d or {}).get(REVIEW_KEY) or {}).get("changes") or []:
            lines.append(t("change_line", lang, label=label, field=t(FIELD_KEYS.get(c["field"], "f_period"), lang)
                           if c["field"] in FIELD_KEYS else c["field"],
                           old=_fmt_change_value(c.get("from"), lang),
                           new=_fmt_change_value(c.get("to"), lang)))
    if lines:
        with st.expander(t("review_saved_note", lang, n=len(lines))):
            for line in lines:
                st.markdown(f"- {html.escape(line)}")


def _set_state(key: str, value: Any) -> None:
    st.session_state[key] = value


def _statement_editor(d: dict[str, Any], idx: int, draft_id: str, label: str, lang: str) -> dict[str, Any]:
    """Editable copy of one extracted statement, with live consistency checks."""
    k = f"rv_{draft_id}_{idx}_"
    with st.container(border=True):
        st.markdown(f"#### {idx + 1}. {html.escape(label)}")
        # Seed widget state once and never pass `value=` as well: the fix buttons write to these
        # keys, and Streamlit warns on screen when a widget has both a default and a state value.
        seeds = {"period": d.get("period") or "", "currency": d.get("currency") or ""}
        seeds.update({f: float(d.get(f) or 0.0) for f in ("total_income", "total_expense", "net_profit",
                                                          "opening_balance", "closing_balance")})
        for f, v in seeds.items():
            st.session_state.setdefault(k + f, v)

        c1, c2 = st.columns(2)
        period = c1.text_input(t("f_period", lang), key=k + "period")
        currency = c2.text_input(t("f_currency", lang), key=k + "currency")

        # Two per row keeps nine-digit kyat amounts readable; number inputs cannot show commas,
        # so each one gets a formatted caption underneath.
        nums: dict[str, float] = {}
        for row in (("total_income", "total_expense"), ("net_profit", None),
                    ("opening_balance", "closing_balance")):
            for col, f in zip(st.columns(2), row):
                if f is None:
                    continue
                nums[f] = col.number_input(t(FIELD_KEYS[f], lang), step=1000.0, format="%.0f", key=k + f)
                col.caption(fmt_money(nums[f], currency))

        column_config = {
            "category": st.column_config.TextColumn(t("col_category", lang), required=True),
            "amount": st.column_config.NumberColumn(t("col_amount", lang), format="localized",
                                                    required=True),
        }
        items: dict[str, list[dict[str, Any]]] = {}
        for f in ("income_items", "expense_items"):
            st.markdown(f"**{t(FIELD_KEYS[f], lang)}**")
            start = pd.DataFrame(clean_items(d.get(f)), columns=["category", "amount"])
            edited = st.data_editor(start, key=k + f, num_rows="dynamic", hide_index=True,
                                    width="stretch", column_config=column_config)
            items[f] = clean_items(edited)

        edited_stmt = {**d, "period": period, "currency": currency, **nums, **items}

        # Live checks and one-click fixes for the two most common extraction slips.
        problems = check_statement(edited_stmt, label)
        if not problems:
            st.success(t("checks_ok", lang))
        for a in problems:
            getattr(st, a["severity"])(alert_text(a, lang))
        codes = {a["code"] for a in problems}
        b1, b2 = st.columns(2)
        if "net_mismatch" in codes:
            computed = nums["total_income"] - nums["total_expense"]
            b1.button(t("use_computed_net", lang, value=fmt_money(computed)), key=k + "fix_net",
                      on_click=_set_state, args=(k + "net_profit", computed))
        if codes & {"income_items_mismatch", "expense_items_mismatch"}:
            def _use_item_totals(inc=float(items_to_df(items["income_items"]).amount.sum()),
                                 exp=float(items_to_df(items["expense_items"]).amount.sum())):
                if inc:
                    st.session_state[k + "total_income"] = inc
                if exp:
                    st.session_state[k + "total_expense"] = exp
                st.session_state[k + "net_profit"] = (inc or nums["total_income"]) - (exp or nums["total_expense"])
            b2.button(t("use_item_totals", lang), key=k + "fix_items", on_click=_use_item_totals)

        n_changes = len(review_changes({k2: v for k2, v in d.items() if k2 != REVIEW_KEY}, edited_stmt))
        if n_changes:
            st.caption(t("edited_count", lang, n=n_changes))
    return edited_stmt


def render_review(draft: dict[str, Any], lang: str, api_key: str, model: str, threshold: float) -> None:
    """Step 2 of an analysis: a person checks the AI-extracted figures before anything is saved."""
    st.markdown(f"### {t('review_h', lang)}")
    st.info(t("review_intro", lang))
    e1 = _statement_editor(draft["d1"], 0, draft["id"], draft["label1"], lang)
    e2 = _statement_editor(draft["d2"], 1, draft["id"], draft["label2"], lang)

    c1, c2, _ = st.columns([2, 2, 1])
    confirm = c1.button(t("confirm", lang), type="primary", key="btn_confirm", width="stretch")
    if c2.button(t("discard", lang), key="btn_discard", width="stretch"):
        st.session_state.pop("draft", None)
        st.rerun()
    if not confirm:
        return

    now = datetime.now().isoformat(timespec="seconds")
    d1 = apply_review(draft["d1"], e1, now)
    d2 = apply_review(draft["d2"], e2, now)
    label1, label2 = draft["label1"], draft["label2"]
    try:
        with st.spinner(t("calculating", lang)):
            metrics = compute_metrics(d1, d2, label1, label2)
            alerts = build_alerts(d1, d2, metrics, threshold, label1, label2)
            summary = ai.generate_ceo_summary(
                api_key, model,
                {"labels": [label1, label2], "month1": public_statement(d1), "month2": public_statement(d2),
                 "totals": metrics["totals"], "ratios": metrics["ratios"],
                 "alerts": [a["message"] for a in alerts]},
                AI_LANGUAGE[lang],
            )
    except Exception as exc:  # noqa: BLE001
        st.error(ai.friendly_error(exc, model, lang))
        return

    rec = {
        "created_at": now, "title": draft["title"], "label1": label1, "label2": label2,
        "period1": d1.get("period"), "period2": d2.get("period"),
        "currency": d2.get("currency") or d1.get("currency") or "",
        "file1_name": draft["file1_name"], "file2_name": draft["file2_name"], "model": model,
        "data1": d1, "data2": d2, "metrics": metrics, "alerts": alerts, "summary": summary,
    }
    try:
        rec["id"] = storage.save_report(rec)
        flash("new", "success", t("saved", lang, id=rec["id"]))
    except Exception as exc:  # noqa: BLE001 - never lose an analysis that already cost API calls
        rec["id"] = "unsaved"
        flash("new", "warning", t("save_failed", lang, error=exc))
    st.session_state["last_report"] = rec
    st.session_state.pop("draft", None)
    st.rerun()


BACKUP_ERRORS = {"not_json": "backup_not_json", "wrong_app": "backup_wrong_app",
                 "newer_version": "backup_newer_version", "no_reports": "backup_no_reports",
                 "bad_report": "backup_bad_report"}


def render_backup(lang: str) -> None:
    with st.expander(t("backup_h", lang)):
        st.caption(t("backup_intro", lang))
        now = datetime.now()
        try:
            st.download_button(t("backup_download", lang), data=storage.make_backup(now.isoformat(timespec="seconds")),
                               file_name=f"ace_audit_backup_{now:%Y%m%d_%H%M}.json", mime="application/json",
                               key="btn_backup")
        except Exception as exc:  # noqa: BLE001
            st.error(t("storage_error", lang, error=exc))
        upload = st.file_uploader(t("restore_upload", lang), type=["json"], key="restore_file")
        if st.button(t("restore_button", lang), key="btn_restore", disabled=upload is None):
            try:
                added, skipped = storage.restore_reports(storage.parse_backup(upload.getvalue()))
            except storage.BackupError as exc:
                st.error(t(BACKUP_ERRORS.get(str(exc), "backup_bad_report"), lang))
            except Exception as exc:  # noqa: BLE001
                st.error(t("storage_error", lang, error=exc))
            else:
                flash("history", "success", t("restore_done", lang, added=added, skipped=skipped))
                st.rerun()


def flash(where: str, severity: str, message: str) -> None:
    """Queue a one-off message to show after st.rerun(). `where` names the tab that shows it:
    every tab runs on every rerun, so a shared message would be consumed by whichever tab
    happened to render first, usually one the user is not looking at."""
    st.session_state[f"flash_{where}"] = (severity, message)


def show_flash(where: str) -> None:
    item = st.session_state.pop(f"flash_{where}", None)
    if item:
        getattr(st, item[0])(item[1])


def render_report(rec: dict[str, Any], key_prefix: str, api_key: str, model: str, lang: str) -> None:
    """Render a full report. `key_prefix` keeps widget keys unique: Streamlit runs every
    tab in the same script pass, so the same report can be drawn twice in one run."""
    d1, d2, m, alerts = rec["data1"], rec["data2"], rec["metrics"], rec["alerts"]
    l1, l2, cur = rec["label1"], rec["label2"], rec.get("currency") or ""
    rid = rec.get("id", "new")

    st.caption(t("caption", lang, l1=l1, p1=display_period(rec.get("period1"), "—"),
                 l2=l2, p2=display_period(rec.get("period2"), "—"), cur=cur or "?",
                 f1=rec.get("file1_name"), f2=rec.get("file2_name")))
    render_review_note(rec, lang)

    c1, c2, c3, c4 = st.columns(4)
    metric_card(c1, t("card_income", lang), fmt_money(d2["total_income"], cur),
                d2["total_income"] - d1["total_income"], pct_change(d1["total_income"], d2["total_income"]))
    metric_card(c2, t("card_expense", lang), fmt_money(d2["total_expense"], cur),
                d2["total_expense"] - d1["total_expense"], pct_change(d1["total_expense"], d2["total_expense"]),
                invert=True)
    metric_card(c3, t("card_net", lang), fmt_money(d2["net_profit"], cur),
                d2["net_profit"] - d1["net_profit"], pct_change(d1["net_profit"], d2["net_profit"]))
    pm1, pm2 = safe_div(d1["net_profit"], d1["total_income"]), safe_div(d2["net_profit"], d2["total_income"])
    metric_card(c4, t("card_margin", lang), "-" if is_missing(pm2) else f"{pm2 * 100:.1f}%",
                None if is_missing(pm1) or is_missing(pm2) else (pm2 - pm1) * 100, None,
                pts_label=t("pts", lang))

    d_json, d_xlsx, _ = st.columns([1, 1, 2])
    try:
        d_xlsx.download_button(t("dl_excel", lang), data=export.build_excel_report(rec, lang),
                               file_name=export.export_filename(rec),
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key=f"xlsx_{key_prefix}_{rid}", width="stretch")
    except Exception as exc:  # noqa: BLE001 - an export problem must not hide the report
        d_xlsx.warning(t("excel_unavailable", lang, error=exc))
    d_json.download_button(t("dl_json", lang),
                           data=json.dumps(rec, indent=2, ensure_ascii=False, default=str),
                           file_name=f"ace_report_{rid}.json", mime="application/json",
                           key=f"dl_{key_prefix}_{rid}", width="stretch")

    st.markdown(f"### {t('summary_h', lang)}")
    if rec.get("summary"):
        st.markdown(f'<div class="ace-summary">\n\n{rec["summary"]}\n\n</div>', unsafe_allow_html=True)
    else:
        st.info(t("no_summary", lang))

    counts = alert_counts(alerts)
    st.markdown(f"### {t('alerts_h', lang)}  <small>"
                f"{t('alert_counts', lang, e=counts['error'], w=counts['warning'], i=counts['info'])}"
                f"</small>", unsafe_allow_html=True)
    if not alerts:
        st.success(t("no_alerts", lang))
    for a in alerts:
        getattr(st, a["severity"])(alert_text(a, lang))

    render_qa(rec, key_prefix, api_key, model, lang)

    col_var, col_comb, col_pct = t("col_variance", lang), t("col_combined", lang), t("col_change_pct", lang)
    st.markdown(f"### {t('totals_h', lang)}")
    totals_df = pd.DataFrame(m["totals"])
    totals_df["Item"] = totals_df["Item"].map(lambda x: item_name(x, lang))
    totals_df = totals_df.rename(columns={"Item": t("col_item", lang), "Net Variance": col_var,
                                          "Combined": col_comb, "Change %": col_pct})
    st.dataframe(totals_df.style.format({l1: "{:,.0f}", l2: "{:,.0f}", col_var: "{:+,.0f}",
                                         col_comb: "{:,.0f}", col_pct: fmt_pct}),
                 width="stretch", hide_index=True)

    st.markdown(f"### {t('ratios_h', lang)}")

    def _fr(v, unit):
        return "-" if is_missing(v) else (f"{v:.1f}%" if unit == "%" else f"{v:.2f}x")

    ratio_df = pd.DataFrame([{t("col_metric", lang): ratio_name(r["Metric"], lang),
                              l1: _fr(r.get(l1), r["unit"]), l2: _fr(r.get(l2), r["unit"])}
                             for r in m["ratios"]])
    st.dataframe(ratio_df, width="stretch", hide_index=True)

    st.markdown(f"### {t('categories_h', lang)}")
    col_cat, col_diff = t("col_category", lang), t("col_difference", lang)
    fmt_cat = {l1: "{:,.0f}", l2: "{:,.0f}", col_diff: "{:+,.0f}", col_pct: fmt_pct}
    tab_i, tab_e = st.tabs([t("income_tab", lang), t("expense_tab", lang)])
    for tab, rows in ((tab_i, m["income_by_category"]), (tab_e, m["expense_by_category"])):
        with tab:
            df = pd.DataFrame(rows)
            if df.empty:
                st.info(t("no_items", lang))
            else:
                df = df.rename(columns={"category": col_cat, "Difference": col_diff, "Change %": col_pct})
                st.dataframe(df.style.format(fmt_cat), width="stretch", hide_index=True)
                st.bar_chart(df.set_index(col_cat)[[l1, l2]])

    with st.expander(t("raw_h", lang)):
        a, b = st.columns(2)
        a.json(d1)
        b.json(d2)


# =========================================================================== #
# Language (chosen before the passcode gate so the login page is translated too)
# =========================================================================== #
with st.sidebar:
    lang = st.radio(t("language"), list(LANGUAGES), format_func=LANGUAGES.get,
                    horizontal=True, key="lang")


# =========================================================================== #
# Passcode gate
# =========================================================================== #
def require_passcode(lang: str) -> None:
    expected = secret("APP_PASSCODE")
    if not expected:
        st.error(t("passcode_missing", lang))
        st.stop()
    if st.session_state.get("authenticated"):
        return

    hero(lang, "restricted")
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        with st.form("login"):
            code = st.text_input(t("enter_passcode", lang), type="password", key="passcode")
            ok = st.form_submit_button(t("unlock", lang), type="primary", width="stretch",
                                       key="btn_unlock")
        if ok:
            if hmac.compare_digest(code.strip().encode(), expected.encode()):
                st.session_state["authenticated"] = True
                st.rerun()
            st.error(t("wrong_passcode", lang))
    st.stop()


require_passcode(lang)

# =========================================================================== #
# Sidebar
# =========================================================================== #
with st.sidebar:
    st.markdown(f"## {t('settings', lang)}")
    api_key = st.text_input(t("api_key", lang), type="password", value=secret("GEMINI_API_KEY"),
                            help="https://aistudio.google.com/app/apikey")
    model = st.selectbox(t("model", lang), MODEL_OPTIONS, index=0, help=t("model_help", lang))
    threshold = st.slider(t("threshold", lang), 5.0, 100.0, DEFAULT_ALERT_THRESHOLD, 5.0)
    st.markdown("---")
    report_count_slot = st.empty()  # filled at the end so a fresh save is reflected immediately
    st.caption(t("storage", lang, label=storage.backend_label(lang)))
    st.markdown("---")
    if st.button(t("lock", lang), key="btn_lock"):
        chosen = st.session_state.get("lang", MY)
        st.session_state.clear()
        st.session_state["lang"] = chosen
        st.rerun()

# =========================================================================== #
# Main
# =========================================================================== #
hero(lang, "powered")
uploader_text_css(lang)

tab_new, tab_history, tab_trend = st.tabs([t("tab_new", lang), t("tab_history", lang),
                                           t("tab_trend", lang)])

# --------------------------------------------------------------------------- #
with tab_new:
    show_flash("new")
    draft = st.session_state.get("draft")
    if draft:
        render_review(draft, lang, api_key, model, threshold)
    else:
        c1, c2 = st.columns(2)
        with c1:
            label1_in = st.text_input(t("prev_label", lang), t("prev_default", lang), key=f"label1_{lang}")
            file1 = st.file_uploader(t("upload_prev", lang), type=ACCEPTED_TYPES, key="f1")
        with c2:
            label2_in = st.text_input(t("curr_label", lang), t("curr_default", lang), key=f"label2_{lang}")
            file2 = st.file_uploader(t("upload_curr", lang), type=ACCEPTED_TYPES, key="f2")
        title = st.text_input(t("report_title", lang),
                              t("title_default", lang, date=f"{datetime.now():%Y-%m-%d}"), key=f"title_{lang}")
        label1, label2 = distinct_labels(label1_in, label2_in)
        st.caption(t("extract_hint", lang))

        if st.button(t("extract", lang), type="primary", disabled=not (file1 and file2), key="btn_extract"):
            if not api_key:
                st.error(t("need_key", lang))
                st.stop()
            progress = st.progress(0, text=t("reading", lang, name=file1.name))
            try:
                d1 = extract_cached(api_key, model, file1.getvalue(), file1.name)
                progress.progress(50, text=t("reading", lang, name=file2.name))
                d2 = extract_cached(api_key, model, file2.getvalue(), file2.name)
            except Exception as exc:  # noqa: BLE001
                progress.empty()
                st.error(ai.friendly_error(exc, model, lang))
                st.stop()
            progress.empty()
            st.session_state["draft"] = {
                "id": uuid.uuid4().hex[:8], "d1": d1, "d2": d2, "label1": label1, "label2": label2,
                "title": title.strip() or t("title_default", lang, date=f"{datetime.now():%Y-%m-%d}"),
                "file1_name": file1.name, "file2_name": file2.name,
            }
            st.rerun()

    if "last_report" in st.session_state and not draft:
        st.markdown("---")
        render_report(st.session_state["last_report"], "latest", api_key, model, lang)

# --------------------------------------------------------------------------- #
with tab_history:
    show_flash("history")
    render_backup(lang)
    try:
        reports = storage.list_reports()
    except Exception as exc:  # noqa: BLE001
        st.error(t("storage_error", lang, error=exc))
        reports = []
    if not reports:
        st.info(t("no_reports", lang))
    else:
        options = {
            f"#{r['id']} · {str(r['created_at'])[:16].replace('T', ' ')} · {r['title']} "
            f"({display_period(r.get('period1'), '—')} → {display_period(r.get('period2'), '—')})": r["id"]
            for r in reports
        }
        choice = st.selectbox(t("select_report", lang), list(options.keys()), key="history_pick")
        rid = options[choice]
        rec = storage.get_report(rid)
        if rec:
            hc1, hc2 = st.columns([4, 1])
            hc1.markdown(f"#### {rec['title']}")
            confirm_key = f"confirm_del_{rid}"
            if not st.session_state.get(confirm_key):
                if hc2.button(t("delete", lang), key=f"del_{rid}", width="stretch"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                st.warning(t("confirm_delete", lang, id=rid, title=rec["title"]))
                y, n, _ = st.columns([1, 1, 3])
                if y.button(t("yes_delete", lang), type="primary", key=f"yes_{rid}", width="stretch"):
                    storage.delete_report(rid)
                    st.session_state.pop(confirm_key, None)
                    last = st.session_state.get("last_report") or {}
                    if last.get("id") == rid:
                        st.session_state.pop("last_report", None)
                    st.rerun()
                if n.button(t("cancel", lang), key=f"no_{rid}", width="stretch"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            render_report(rec, "history", api_key, model, lang)

# --------------------------------------------------------------------------- #
with tab_trend:
    try:
        trend = storage.trend_frame()
    except Exception as exc:  # noqa: BLE001
        st.error(t("storage_error", lang, error=exc))
        trend = pd.DataFrame()
    if len(trend) < 2:
        st.info(t("trend_need_two", lang))
    else:
        cols = {"Report #": t("col_report", lang), "Saved": t("col_saved", lang),
                "Period": t("col_period", lang), "Income": t("col_income", lang),
                "Expense": t("col_expense", lang), "Net Profit": t("col_net", lang)}
        margin = t("col_margin_pct", lang)
        trend[margin] = trend.apply(
            lambda r: (r["Net Profit"] / r["Income"] * 100) if r["Income"] else None, axis=1)
        # Report number keeps points distinct when two reports share a period name.
        trend["Point"] = trend.apply(lambda r: f"#{r['Report #']} {r['Period']}", axis=1)
        trend = trend.rename(columns=cols)
        series = [cols["Income"], cols["Expense"], cols["Net Profit"]]
        st.markdown(f"#### {t('trend_title', lang)}")
        st.line_chart(trend.set_index("Point")[series])
        st.dataframe(trend.drop(columns=["Point"]).style.format(
                         {**{c: "{:,.0f}" for c in series},
                          margin: lambda v: "-" if is_missing(v) else f"{v:.1f}%"}),
                     width="stretch", hide_index=True)

# Sidebar counter is filled last so a report saved during this run is included.
try:
    report_count_slot.markdown(f"**{t('stored_reports', lang, n=len(storage.list_reports()))}**")
except Exception as exc:  # noqa: BLE001
    report_count_slot.error(t("storage_unreachable", lang, error=str(exc)[:120]))
