"""Gemini helpers, exercised with a fake client — no network, no API key, no quota."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import ai


class FakeModels:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[dict] = []

    def generate_content(self, model=None, contents=None, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return SimpleNamespace(text=self.text)


class FakeClient:
    def __init__(self, text: str):
        self.models = FakeModels(text)


def test_file_to_part_csv_is_text_with_exact_numbers():
    part = ai.file_to_part("s.csv", b"Category,Amount\nRent,1500000\n")
    assert isinstance(part, str) and "Rent,1500000" in part


def test_file_to_part_excel_includes_every_sheet(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "Income"
    wb.active.append(["Sales", 100])
    wb.create_sheet("Costs").append(["Rent", 40])
    path = tmp_path / "s.xlsx"
    wb.save(path)
    part = ai.file_to_part("S.XLSX", path.read_bytes())
    assert "### Sheet: Income" in part and "### Sheet: Costs" in part


@pytest.mark.parametrize("name, mime", [("a.pdf", "application/pdf"), ("b.PNG", "image/png"),
                                        ("c.jpeg", "image/jpeg"), ("d.webp", "image/webp")])
def test_file_to_part_binary_types(name, mime):
    part = ai.file_to_part(name, b"\x00\x01")
    assert part.inline_data.mime_type == mime


def test_file_to_part_rejects_unknown_type():
    with pytest.raises(ValueError):
        ai.file_to_part("notes.docx", b"")


@pytest.mark.parametrize("raw", ['{"a": 1}', '```json\n{"a": 1}\n```', '```\n{"a": 1}```'])
def test_clean_json_strips_fences(raw):
    assert json.loads(ai.clean_json(raw)) == {"a": 1}


def test_extract_financials_normalizes_output():
    payload = {"period": "Feb 2026", "currency": "MMK", "total_income": "1000",
               "total_expense": 400, "net_profit": 600, "income_items": None, "expense_items": []}
    client = FakeClient("```json\n" + json.dumps(payload) + "\n```")
    d = ai.extract_financials("k", "m", b"Category,Amount\n", "x.csv", client=client)
    assert d["total_income"] == 1000.0 and d["closing_balance"] == 0.0
    assert d["income_items"] == []
    assert client.models.calls[0]["model"] == "m"


def test_extract_financials_bad_json_gives_actionable_error():
    with pytest.raises(ValueError, match="valid JSON"):
        ai.extract_financials("k", "m", b"a,b\n", "x.csv", client=FakeClient("not json"))


def test_summary_prompt_carries_language_and_data(report):
    client = FakeClient("- ok")
    out = ai.generate_ceo_summary("k", "m", {"totals": report["metrics"]["totals"]}, "Myanmar",
                                  client=client)
    prompt = client.models.calls[0]["contents"]
    assert out == "- ok"
    assert "Burmese" in prompt and "Total Income" in prompt


def test_answer_question_is_grounded_in_the_report(report):
    client = FakeClient("Maintenance rose 209.1%.")
    history = [{"role": "ceo", "text": "Hi"}, {"role": "cfo", "text": "Hello"}]
    out = ai.answer_question("k", "m", report, "Why did costs rise?", history, "English", client=client)
    prompt = client.models.calls[0]["contents"]
    assert out == "Maintenance rose 209.1%."
    assert "Why did costs rise?" in prompt
    assert "Maintenance" in prompt           # report data is included
    assert "CEO: Hi" in prompt               # earlier turns are included
    assert "Never invent figures" in prompt


def test_answer_question_keeps_only_recent_history(report):
    client = FakeClient("ok")
    history = [{"role": "ceo", "text": f"old-{i}"} for i in range(20)]
    ai.answer_question("k", "m", report, "q", history, "English", client=client)
    prompt = client.models.calls[0]["contents"]
    assert "old-0" not in prompt and "old-19" in prompt


@pytest.mark.parametrize("message, expect", [
    ("429 RESOURCE_EXHAUSTED quota", "quota"),
    ("404 NOT_FOUND model", "not available"),
    ("403 PERMISSION_DENIED", "rejected"),
    ("DeadlineExceeded", "timed out"),
])
def test_friendly_error(message, expect):
    assert expect in ai.friendly_error(RuntimeError(message), "gemini-x")


def test_friendly_error_passes_through_value_errors():
    assert ai.friendly_error(ValueError("Gemini did not return valid JSON"), "m") == \
        "Gemini did not return valid JSON"


# --------------------------------------------------------------------------- regression
class ClosingClient:
    """Mimics genai.Client: its HTTP session closes when the client object is garbage-collected."""

    def __init__(self, api_key=None):
        self.models = _ClosingModels()

    def __del__(self):
        self.models.closed = True


class _ClosingModels:
    closed = False

    def generate_content(self, model=None, contents=None, config=None):
        if self.closed:
            raise RuntimeError("Cannot send a request, as the client has been closed.")
        payload = {"period": "P", "currency": "MMK", "total_income": 1, "total_expense": 1,
                   "net_profit": 0, "income_items": [], "expense_items": []}
        return SimpleNamespace(text=json.dumps(payload))


def test_real_client_path_keeps_client_alive(monkeypatch, report):
    """A chained `genai.Client(...).models.generate_content(...)` let the client be collected
    mid-call, so every live Gemini request failed. Exercise the no-`client` code path."""
    monkeypatch.setattr(ai.genai, "Client", ClosingClient)
    assert ai.extract_financials("k", "m", b"a,b\n", "x.csv")["currency"] == "MMK"
    assert ai.generate_ceo_summary("k", "m", {}, "English")
    assert ai.answer_question("k", "m", report, "q", [], "English")
