"""
ACE Audit AI - Financial Statement Comparison with Google Gemini
=================================================================
Streamlit web app that:
  1. Accepts two monthly financial statement files (PDF / image / Excel / CSV)
  2. Uses Google Gemini to extract structured financial figures
  3. Compares the two months (totals, net difference, growth %, ratios)
  4. Flags discrepancies and abnormal changes

Run locally:   streamlit run app.py
Deploy:        Streamlit Cloud (main file = app.py) or any server with Python 3.9+
"""

from __future__ import annotations

import io
import json
import os
import re
from typing import Any

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# --------------------------------------------------------------------------- #
# Page config
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="ACE Audit AI - ငွေစာရင်း နှိုင်းယှဉ်စစ်ဆေးရေး",
    page_icon="📊",
    layout="wide",
)

DEFAULT_MODEL = "gemini-2.5-flash"
MODEL_OPTIONS = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]

# Threshold (in %) above which a change is flagged as abnormal
DEFAULT_ALERT_THRESHOLD = 30.0

# --------------------------------------------------------------------------- #
# Gemini extraction schema & prompt
# --------------------------------------------------------------------------- #
EXTRACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "period": {"type": "STRING", "description": "Statement period, e.g. 'January 2026'"},
        "currency": {"type": "STRING", "description": "Currency code or symbol, e.g. MMK, USD"},
        "total_income": {"type": "NUMBER", "description": "Total income / revenue for the period"},
        "total_expense": {"type": "NUMBER", "description": "Total expenses for the period"},
        "net_profit": {"type": "NUMBER", "description": "Net profit or loss (income - expense)"},
        "opening_balance": {"type": "NUMBER", "description": "Opening / beginning balance, 0 if not present"},
        "closing_balance": {"type": "NUMBER", "description": "Closing / ending balance, 0 if not present"},
        "income_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "category": {"type": "STRING"},
                    "amount": {"type": "NUMBER"},
                },
                "required": ["category", "amount"],
            },
        },
        "expense_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "category": {"type": "STRING"},
                    "amount": {"type": "NUMBER"},
                },
                "required": ["category", "amount"],
            },
        },
        "notes": {"type": "STRING", "description": "Any anomalies, unclear figures or assumptions made"},
    },
    "required": [
        "period",
        "currency",
        "total_income",
        "total_expense",
        "net_profit",
        "income_items",
        "expense_items",
    ],
}

EXTRACTION_PROMPT = """You are a meticulous accountant. Read the attached financial statement
(it may be a PDF, a scanned image, or tabular data) and extract the figures.

Rules:
- All amounts must be plain numbers (no thousands separators, no currency symbols).
- Expenses are positive numbers.
- net_profit = total_income - total_expense. If the document states a different net figure,
  still report the document's stated value and mention the mismatch in `notes`.
- Group line items into sensible categories (e.g. Sales, Service Income, Rent, Salaries, Utilities).
- If a value is genuinely absent, use 0 and explain in `notes`.
- Respond ONLY with JSON matching the given schema.
"""

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def get_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def file_to_part(uploaded) -> tuple[types.Part | str, str]:
    """
    Convert an uploaded file into a Gemini content part.
    Returns (part, description). Excel/CSV are converted to CSV text so Gemini
    reads exact numbers instead of guessing from a rendered image.
    """
    name = uploaded.name.lower()
    data = uploaded.getvalue()

    if name.endswith(".pdf"):
        return types.Part.from_bytes(data=data, mime_type="application/pdf"), "PDF"

    if name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        mime = "image/png" if name.endswith(".png") else "image/webp" if name.endswith(".webp") else "image/jpeg"
        return types.Part.from_bytes(data=data, mime_type=mime), "Image"

    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(data))
        return f"CSV data:\n\n{df.to_csv(index=False)}", "CSV"

    if name.endswith((".xlsx", ".xls")):
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
        chunks = [f"### Sheet: {sn}\n{df.to_csv(index=False)}" for sn, df in sheets.items()]
        return "Excel workbook data:\n\n" + "\n\n".join(chunks), "Excel"

    raise ValueError(f"Unsupported file type: {uploaded.name}")


def _clean_json(text: str) -> str:
    """Strip markdown fences if the model wraps JSON in ```json ... ```."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text


@st.cache_data(show_spinner=False)
def extract_financials(api_key: str, model: str, file_bytes: bytes, file_name: str) -> dict[str, Any]:
    """Send one file to Gemini and return the structured extraction. Cached per file content."""
    client = get_client(api_key)

    class _Wrapper:  # minimal shim so file_to_part can reuse UploadedFile API
        name = file_name

        @staticmethod
        def getvalue() -> bytes:
            return file_bytes

    part, _ = file_to_part(_Wrapper())

    response = client.models.generate_content(
        model=model,
        contents=[EXTRACTION_PROMPT, part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EXTRACTION_SCHEMA,
            temperature=0.0,
        ),
    )
    return json.loads(_clean_json(response.text))


def pct_change(old: float, new: float) -> float | None:
    if old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def safe_ratio(num: float, den: float) -> float | None:
    return None if den == 0 else num / den


def fmt_money(v: float | None, cur: str = "") -> str:
    if v is None:
        return "-"
    return f"{v:,.0f} {cur}".strip()


def fmt_pct(v: float | None) -> str:
    return "-" if v is None or pd.isna(v) else f"{v:+.1f}%"


def items_to_df(items: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(items or [], columns=["category", "amount"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df.groupby("category", as_index=False)["amount"].sum()


def compare_items(items1: list[dict], items2: list[dict], label1: str, label2: str) -> pd.DataFrame:
    df1 = items_to_df(items1).rename(columns={"amount": label1})
    df2 = items_to_df(items2).rename(columns={"amount": label2})
    merged = df1.merge(df2, on="category", how="outer").fillna(0.0)
    merged["Difference"] = merged[label2] - merged[label1]
    merged["Change %"] = merged.apply(lambda r: pct_change(r[label1], r[label2]), axis=1)
    return merged.sort_values(label2, ascending=False).reset_index(drop=True)


def build_alerts(d1: dict, d2: dict, item_cmp_income: pd.DataFrame, item_cmp_expense: pd.DataFrame,
                 threshold: float) -> list[tuple[str, str]]:
    """Return list of (severity, message). severity in {'error','warning','info'}."""
    alerts: list[tuple[str, str]] = []

    # 1. Internal consistency: income - expense should equal net_profit
    for label, d in (("Month 1", d1), ("Month 2", d2)):
        computed = d["total_income"] - d["total_expense"]
        stated = d["net_profit"]
        if abs(computed - stated) > max(1.0, abs(stated) * 0.005):
            alerts.append((
                "error",
                f"{label}: Net profit stated ({stated:,.0f}) does not equal income - expense "
                f"({computed:,.0f}). Difference = {stated - computed:,.0f}.",
            ))

        # 2. Line items should sum to the totals
        inc_sum = items_to_df(d.get("income_items", []))["amount"].sum()
        exp_sum = items_to_df(d.get("expense_items", []))["amount"].sum()
        if inc_sum and abs(inc_sum - d["total_income"]) > max(1.0, abs(d["total_income"]) * 0.01):
            alerts.append((
                "warning",
                f"{label}: Income line items sum to {inc_sum:,.0f} but total income is "
                f"{d['total_income']:,.0f}.",
            ))
        if exp_sum and abs(exp_sum - d["total_expense"]) > max(1.0, abs(d["total_expense"]) * 0.01):
            alerts.append((
                "warning",
                f"{label}: Expense line items sum to {exp_sum:,.0f} but total expense is "
                f"{d['total_expense']:,.0f}.",
            ))

        # 3. Balance roll-forward check (only if balances present)
        ob, cb = d.get("opening_balance", 0) or 0, d.get("closing_balance", 0) or 0
        if ob or cb:
            expected_cb = ob + stated
            if abs(expected_cb - cb) > max(1.0, abs(cb) * 0.005):
                alerts.append((
                    "warning",
                    f"{label}: Opening balance + net profit = {expected_cb:,.0f} but closing balance "
                    f"is {cb:,.0f}.",
                ))

    # 4. Month 1 closing should equal Month 2 opening
    cb1 = d1.get("closing_balance", 0) or 0
    ob2 = d2.get("opening_balance", 0) or 0
    if cb1 and ob2 and abs(cb1 - ob2) > max(1.0, abs(cb1) * 0.005):
        alerts.append((
            "error",
            f"Month 1 closing balance ({cb1:,.0f}) does not match Month 2 opening balance ({ob2:,.0f}).",
        ))

    # 5. Currency mismatch
    if (d1.get("currency") or "").strip().upper() != (d2.get("currency") or "").strip().upper():
        alerts.append(("warning", f"Currency differs: Month 1 = {d1.get('currency')}, Month 2 = {d2.get('currency')}."))

    # 6. Abnormal swings on totals
    for key, name in (("total_income", "Total income"), ("total_expense", "Total expense"), ("net_profit", "Net profit")):
        ch = pct_change(d1[key], d2[key])
        if ch is not None and abs(ch) >= threshold:
            alerts.append(("warning", f"{name} changed by {ch:+.1f}% (threshold {threshold:.0f}%)."))

    # 7. Loss
    if d2["net_profit"] < 0:
        alerts.append(("error", f"Month 2 shows a net LOSS of {d2['net_profit']:,.0f}."))

    # 8. Abnormal swings on individual categories
    for df, kind in ((item_cmp_income, "Income"), (item_cmp_expense, "Expense")):
        for _, r in df.iterrows():
            ch = r["Change %"]
            missing = ch is None or pd.isna(ch)
            if not missing and abs(ch) >= threshold:
                alerts.append(("info", f"{kind} category '{r['category']}' changed by {ch:+.1f}%."))
            elif missing and r["Difference"] != 0:
                alerts.append(("info", f"{kind} category '{r['category']}' is new or disappeared (diff {r['Difference']:,.0f})."))

    # 9. Model-reported notes
    for label, d in (("Month 1", d1), ("Month 2", d2)):
        note = (d.get("notes") or "").strip()
        if note and note.lower() not in {"none", "n/a", "no anomalies"}:
            alerts.append(("info", f"{label} AI notes: {note}"))

    return alerts


# --------------------------------------------------------------------------- #
# Sidebar - settings
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("⚙️ Settings")
    api_key = st.text_input(
        "Google Gemini API Key",
        type="password",
        value=os.environ.get("GEMINI_API_KEY", ""),
        help="Get a key at https://aistudio.google.com/app/apikey. "
             "On Streamlit Cloud you can also set GEMINI_API_KEY in Secrets.",
    )
    if not api_key:
        try:  # st.secrets raises if no secrets.toml exists locally
            api_key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:  # noqa: BLE001
            api_key = ""

    model = st.selectbox("Gemini model", MODEL_OPTIONS, index=0)
    threshold = st.slider("Alert threshold (% change)", 5.0, 100.0, DEFAULT_ALERT_THRESHOLD, 5.0)

    st.markdown("---")
    st.caption(
        "Supported files: PDF, PNG/JPG/WEBP, XLSX/XLS, CSV.\n\n"
        "Files are sent to Google Gemini for extraction. Do not upload data you are not "
        "allowed to share with a third-party service."
    )

# --------------------------------------------------------------------------- #
# Main UI
# --------------------------------------------------------------------------- #
st.title("📊 ACE Audit AI")
st.subheader("လစဉ် ငွေစာရင်း နှိုင်းယှဉ်စစ်ဆေးရေး (Gemini AI)")
st.write(
    "လနှစ်လ၏ ငွေစာရင်းဖိုင်များကို တင်ပါ။ AI က ဝင်ငွေ၊ ထွက်ငွေ၊ အမြတ် စသည်တို့ကို ဖတ်ယူပြီး "
    "ကွာခြားချက်၊ တိုးတက်နှုန်း၊ အချိုးများနှင့် သတိပေးချက်များကို တွက်ချက်ဖော်ပြပေးပါမည်။"
)

ACCEPTED = ["pdf", "png", "jpg", "jpeg", "webp", "xlsx", "xls", "csv"]
col1, col2 = st.columns(2)
with col1:
    label1 = st.text_input("Month 1 label", "Month 1")
    file1 = st.file_uploader("Upload Month 1 statement", type=ACCEPTED, key="f1")
with col2:
    label2 = st.text_input("Month 2 label", "Month 2")
    file2 = st.file_uploader("Upload Month 2 statement", type=ACCEPTED, key="f2")

run = st.button("🔍 Analyze & Compare", type="primary", disabled=not (file1 and file2))

if run:
    if not api_key:
        st.error("Please enter your Gemini API key in the sidebar.")
        st.stop()

    try:
        with st.spinner(f"Extracting {label1} with Gemini..."):
            d1 = extract_financials(api_key, model, file1.getvalue(), file1.name)
        with st.spinner(f"Extracting {label2} with Gemini..."):
            d2 = extract_financials(api_key, model, file2.getvalue(), file2.name)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Extraction failed: {exc}")
        st.stop()

    for d in (d1, d2):
        for k in ("total_income", "total_expense", "net_profit", "opening_balance", "closing_balance"):
            d[k] = float(d.get(k) or 0)

    cur = d2.get("currency") or d1.get("currency") or ""

    # ------------------------------------------------------------------ #
    # Summary metrics
    # ------------------------------------------------------------------ #
    st.markdown("## 📌 Summary")
    st.caption(f"{label1}: {d1.get('period', '?')}  |  {label2}: {d2.get('period', '?')}  |  Currency: {cur}")

    m1, m2, m3 = st.columns(3)
    for col, key, name in ((m1, "total_income", "Total Income"), (m2, "total_expense", "Total Expense"), (m3, "net_profit", "Net Profit")):
        ch = pct_change(d1[key], d2[key])
        col.metric(
            name,
            fmt_money(d2[key], cur),
            delta=f"{d2[key] - d1[key]:+,.0f} ({fmt_pct(ch)})",
            delta_color="inverse" if key == "total_expense" else "normal",
        )

    # ------------------------------------------------------------------ #
    # Comparison table (add / subtract)
    # ------------------------------------------------------------------ #
    st.markdown("## ➕➖ Totals & Net Difference")
    rows = []
    for key, name in (
        ("opening_balance", "Opening Balance"),
        ("total_income", "Total Income"),
        ("total_expense", "Total Expense"),
        ("net_profit", "Net Profit"),
        ("closing_balance", "Closing Balance"),
    ):
        rows.append({
            "Item": name,
            label1: d1[key],
            label2: d2[key],
            "Difference (M2 - M1)": d2[key] - d1[key],
            "Combined (M1 + M2)": d1[key] + d2[key],
            "Change %": pct_change(d1[key], d2[key]),
        })
    totals_df = pd.DataFrame(rows)
    st.dataframe(
        totals_df.style.format({label1: "{:,.0f}", label2: "{:,.0f}", "Difference (M2 - M1)": "{:+,.0f}",
                                "Combined (M1 + M2)": "{:,.0f}", "Change %": lambda v: fmt_pct(v)}),
        use_container_width=True, hide_index=True,
    )

    # ------------------------------------------------------------------ #
    # Ratios (multiply / divide)
    # ------------------------------------------------------------------ #
    st.markdown("## ✖️➗ Growth Rates & Ratios")
    ratio_rows = [
        {"Metric": "Income growth rate", label1: None, label2: pct_change(d1["total_income"], d2["total_income"]), "unit": "%"},
        {"Metric": "Expense growth rate", label1: None, label2: pct_change(d1["total_expense"], d2["total_expense"]), "unit": "%"},
        {"Metric": "Net profit growth rate", label1: None, label2: pct_change(d1["net_profit"], d2["net_profit"]), "unit": "%"},
        {"Metric": "Profit margin (net / income)",
         label1: (safe_ratio(d1["net_profit"], d1["total_income"]) or 0) * 100,
         label2: (safe_ratio(d2["net_profit"], d2["total_income"]) or 0) * 100, "unit": "%"},
        {"Metric": "Expense ratio (expense / income)",
         label1: (safe_ratio(d1["total_expense"], d1["total_income"]) or 0) * 100,
         label2: (safe_ratio(d2["total_expense"], d2["total_income"]) or 0) * 100, "unit": "%"},
        {"Metric": "Income / Expense multiple (x)",
         label1: safe_ratio(d1["total_income"], d1["total_expense"]),
         label2: safe_ratio(d2["total_income"], d2["total_expense"]), "unit": "x"},
        {"Metric": "Income multiplier M2 / M1 (x)", label1: None,
         label2: safe_ratio(d2["total_income"], d1["total_income"]), "unit": "x"},
    ]

    def _fmt_ratio(v, unit):
        if v is None:
            return "-"
        return f"{v:.1f}%" if unit == "%" else f"{v:.2f}x"

    ratio_df = pd.DataFrame([
        {"Metric": r["Metric"], label1: _fmt_ratio(r[label1], r["unit"]), label2: _fmt_ratio(r[label2], r["unit"])}
        for r in ratio_rows
    ])
    st.dataframe(ratio_df, use_container_width=True, hide_index=True)

    # ------------------------------------------------------------------ #
    # Category-level breakdown
    # ------------------------------------------------------------------ #
    st.markdown("## 📂 Category Breakdown")
    inc_cmp = compare_items(d1.get("income_items", []), d2.get("income_items", []), label1, label2)
    exp_cmp = compare_items(d1.get("expense_items", []), d2.get("expense_items", []), label1, label2)

    fmt_cat = {label1: "{:,.0f}", label2: "{:,.0f}", "Difference": "{:+,.0f}", "Change %": lambda v: fmt_pct(v)}
    t1, t2 = st.tabs(["Income by category", "Expense by category"])
    with t1:
        if inc_cmp.empty:
            st.info("No income line items were extracted.")
        else:
            st.dataframe(inc_cmp.style.format(fmt_cat), use_container_width=True, hide_index=True)
            st.bar_chart(inc_cmp.set_index("category")[[label1, label2]])
    with t2:
        if exp_cmp.empty:
            st.info("No expense line items were extracted.")
        else:
            st.dataframe(exp_cmp.style.format(fmt_cat), use_container_width=True, hide_index=True)
            st.bar_chart(exp_cmp.set_index("category")[[label1, label2]])

    # ------------------------------------------------------------------ #
    # Alerts
    # ------------------------------------------------------------------ #
    st.markdown("## 🚨 Discrepancy Alerts")
    alerts = build_alerts(d1, d2, inc_cmp, exp_cmp, threshold)
    if not alerts:
        st.success("No discrepancies or abnormal changes detected.")
    else:
        for sev, msg in alerts:
            getattr(st, sev)(msg)

    # ------------------------------------------------------------------ #
    # Raw extraction & downloads
    # ------------------------------------------------------------------ #
    with st.expander("🔎 Raw AI extraction (JSON)"):
        c1, c2 = st.columns(2)
        c1.json(d1)
        c2.json(d2)

    report = {
        "labels": {"month1": label1, "month2": label2},
        "month1": d1,
        "month2": d2,
        "totals": totals_df.to_dict(orient="records"),
        "ratios": ratio_rows,
        "income_by_category": inc_cmp.to_dict(orient="records"),
        "expense_by_category": exp_cmp.to_dict(orient="records"),
        "alerts": [{"severity": s, "message": m} for s, m in alerts],
    }
    dl1, dl2 = st.columns(2)
    dl1.download_button(
        "⬇️ Download report (JSON)",
        data=json.dumps(report, indent=2, ensure_ascii=False, default=str),
        file_name="comparison_report.json",
        mime="application/json",
    )
    dl2.download_button(
        "⬇️ Download totals (CSV)",
        data=totals_df.to_csv(index=False),
        file_name="comparison_totals.csv",
        mime="text/csv",
    )
