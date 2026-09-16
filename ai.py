"""
Google Gemini calls for ACE Audit AI: statement extraction, CEO summary, and report Q&A.

Every public function accepts an optional `client` so tests can pass a fake one
instead of making network calls (see tests/test_ai.py).
"""

from __future__ import annotations

import io
import json
import re
from typing import Any

import pandas as pd
from google import genai
from google.genai import types

from finance import normalize_statement
from i18n import EN, t

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
- If the period is not stated anywhere, use "Unspecified".
- If a value is genuinely absent use 0 and say so in `notes`.
- Respond ONLY with JSON matching the schema.
"""

class ExtractionError(ValueError):
    """Gemini answered, but not with usable JSON for this file."""

    def __init__(self, file_name: str):
        super().__init__(f"Gemini did not return valid JSON for {file_name}. Try another model.")
        self.file_name = file_name


IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _client(api_key: str, client=None):
    """Return a Gemini client.

    Callers MUST keep the result in a local variable for the duration of the request.
    genai.Client closes its HTTP connection when garbage-collected, so a chained
    `_client(...).models.generate_content(...)` fails with "client has been closed".
    """
    return client if client is not None else genai.Client(api_key=api_key)


def file_to_part(name: str, data: bytes):
    """PDFs and images go to Gemini as bytes; spreadsheets as CSV text so numbers are exact."""
    n = name.lower()
    if n.endswith(".pdf"):
        return types.Part.from_bytes(data=data, mime_type="application/pdf")
    for ext, mime in IMAGE_MIME.items():
        if n.endswith(ext):
            return types.Part.from_bytes(data=data, mime_type=mime)
    if n.endswith(".csv"):
        return "CSV data:\n\n" + pd.read_csv(io.BytesIO(data)).to_csv(index=False)
    if n.endswith((".xlsx", ".xls")):
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
        return "Excel workbook:\n\n" + "\n\n".join(
            f"### Sheet: {sn}\n{df.to_csv(index=False)}" for sn, df in sheets.items())
    raise ValueError(f"Unsupported file type: {name}")


def clean_json(text: str) -> str:
    """Strip Markdown code fences a model sometimes wraps around JSON."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    return re.sub(r"\s*```$", "", text)


def extract_financials(api_key: str, model: str, file_bytes: bytes, file_name: str,
                       client=None) -> dict[str, Any]:
    gemini = _client(api_key, client)  # keep alive until the call returns
    resp = gemini.models.generate_content(
        model=model,
        contents=[EXTRACTION_PROMPT, file_to_part(file_name, file_bytes)],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EXTRACTION_SCHEMA,
            temperature=0.0,
        ),
    )
    try:
        data = json.loads(clean_json(resp.text))
    except json.JSONDecodeError as exc:
        raise ExtractionError(file_name) from exc
    return normalize_statement(data)


def _language_line(language: str) -> str:
    return ("Write in Burmese (Myanmar language), keeping financial terms in English in brackets."
            if language == "Myanmar" else "Write in clear business English.")


def generate_ceo_summary(api_key: str, model: str, payload: dict[str, Any], language: str,
                         client=None) -> str:
    """Turn computed metrics and alerts into a CEO briefing."""
    prompt = f"""You are the CFO briefing the CEO. Using ONLY the data below, write a concise executive
summary as Markdown bullet points (5-8 bullets). Cover: overall performance, biggest drivers of
change, cost concerns, and clear RED FLAGS (mark with 🔴). End with one line of recommended action.
Do not invent numbers. {_language_line(language)}

DATA:
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
"""
    gemini = _client(api_key, client)  # keep alive until the call returns
    resp = gemini.models.generate_content(
        model=model, contents=prompt, config=types.GenerateContentConfig(temperature=0.3))
    return (resp.text or "").strip()


def report_context(rec: dict[str, Any]) -> dict[str, Any]:
    """The subset of a stored report that is useful to answer questions about it."""
    return {
        "title": rec.get("title"),
        "labels": [rec.get("label1"), rec.get("label2")],
        "periods": [rec.get("period1"), rec.get("period2")],
        "currency": rec.get("currency"),
        "previous_month": rec.get("data1"),
        "current_month": rec.get("data2"),
        "totals": (rec.get("metrics") or {}).get("totals"),
        "ratios": (rec.get("metrics") or {}).get("ratios"),
        "income_by_category": (rec.get("metrics") or {}).get("income_by_category"),
        "expense_by_category": (rec.get("metrics") or {}).get("expense_by_category"),
        "alerts": rec.get("alerts"),
        "summary": rec.get("summary"),
    }


def answer_question(api_key: str, model: str, rec: dict[str, Any], question: str,
                    history: list[dict[str, str]] | None, language: str, client=None) -> str:
    """Answer a CEO's follow-up question, grounded only in one stored report."""
    turns = "\n".join(f"{t['role'].upper()}: {t['text']}" for t in (history or [])[-6:])
    prompt = f"""You are the CFO answering the CEO's question about ONE financial comparison report.
Rules:
- Use ONLY the report data below. If the answer is not in the data, say so plainly and say
  what document would be needed. Never invent figures.
- Quote exact numbers with the currency. Show the arithmetic when you calculate something.
- Be brief: at most 6 sentences or bullets.
- {_language_line(language)}

REPORT DATA:
{json.dumps(report_context(rec), ensure_ascii=False, indent=2, default=str)}

EARLIER CONVERSATION:
{turns or "(none)"}

CEO QUESTION: {question.strip()}
"""
    gemini = _client(api_key, client)  # keep alive until the call returns
    resp = gemini.models.generate_content(
        model=model, contents=prompt, config=types.GenerateContentConfig(temperature=0.2))
    return (resp.text or "").strip()


def friendly_error(exc: Exception, model: str, lang: str = EN) -> str:
    """Turn a raw Gemini API error into one line a non-engineer can act on, in `lang`."""
    msg = str(exc)
    if isinstance(exc, ExtractionError):
        return t("err_bad_json", lang, file=exc.file_name)
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return t("err_quota", lang, model=model)
    if "404" in msg or "NOT_FOUND" in msg:
        return t("err_model", lang, model=model)
    if "401" in msg or "403" in msg or "API_KEY" in msg.upper() or "PERMISSION" in msg.upper():
        return t("err_key", lang)
    if "DeadlineExceeded" in msg or "timeout" in msg.lower():
        return t("err_timeout", lang)
    if isinstance(exc, ValueError):
        return msg
    return t("err_other", lang, error=msg[:300])
