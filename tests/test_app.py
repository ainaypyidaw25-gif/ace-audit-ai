"""
Headless tests of the Streamlit UI with streamlit.testing (no browser, no network).

These guard the UI bugs that unit tests of the modules cannot see: the passcode gate,
duplicate widget keys when one report renders in two tabs, the delete confirmation,
and the Q&A form calling Gemini exactly once per question.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import ai

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def app_env(monkeypatch, sqlite_storage):
    monkeypatch.setenv("APP_PASSCODE", "test-pass")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    return sqlite_storage


def _run(at: AppTest) -> AppTest:
    at.run(timeout=30)
    assert not at.exception, [e.value for e in at.exception]
    return at


def _unlock(at: AppTest, code: str = "test-pass") -> AppTest:
    _run(at)
    at.text_input[0].input(code)
    next(b for b in at.button if b.label == "Unlock").click()
    return _run(at)


def test_passcode_gate_blocks_wrong_code(app_env):
    at = _unlock(AppTest.from_file(APP), code="wrong")
    assert any("Incorrect passcode" in e.value for e in at.error)
    assert not at.tabs


def test_passcode_gate_unlocks(app_env):
    at = _unlock(AppTest.from_file(APP))
    assert [t.label for t in at.tabs][:3] == ["🆕 New Analysis", "📚 Previous Reports", "📈 Trend Viewer"]


def test_missing_passcode_config_is_explained(monkeypatch, sqlite_storage):
    monkeypatch.delenv("APP_PASSCODE", raising=False)
    at = AppTest.from_file(APP)
    at.secrets["APP_PASSCODE"] = ""
    _run(at)
    assert any("APP_PASSCODE is not configured" in e.value for e in at.error)
    assert not at.text_input  # no login box when nothing can be checked


def test_history_renders_stored_report_without_errors(app_env, report):
    app_env.save_report(report)
    at = _unlock(AppTest.from_file(APP))
    labels = [b.label for b in at.button]
    assert "🗑️ Delete" in labels
    assert any("Ask about this report" in m.value for m in at.markdown)


def test_same_report_in_two_tabs_has_unique_widget_keys(app_env, report):
    """Latest analysis and the same report under Previous Reports must not clash."""
    rid = app_env.save_report(report)
    at = _unlock(AppTest.from_file(APP))
    at.session_state["last_report"] = {**report, "id": rid}
    _run(at)  # would raise StreamlitDuplicateElementKey before the fix


def test_delete_requires_confirmation(app_env, report):
    app_env.save_report(report)
    at = _unlock(AppTest.from_file(APP))
    next(b for b in at.button if b.label == "🗑️ Delete").click()
    _run(at)
    assert any("permanently" in w.value for w in at.warning)
    assert len(app_env.list_reports()) == 1            # nothing deleted yet
    next(b for b in at.button if b.label == "Cancel").click()
    _run(at)
    assert len(app_env.list_reports()) == 1
    next(b for b in at.button if b.label == "🗑️ Delete").click()
    _run(at)
    next(b for b in at.button if b.label == "Yes, delete").click()
    _run(at)
    assert app_env.list_reports() == []


def test_question_is_sent_to_gemini_exactly_once(app_env, report, monkeypatch):
    """Regression: a non-empty text box was treated as a new question on every rerun,
    so one question looped against the Gemini API until quota ran out."""
    app_env.save_report(report)
    calls = []

    def fake_answer(api_key, model, rec, question, history, language, client=None):
        calls.append(question)
        return f"Answer to: {question}"

    monkeypatch.setattr(ai, "answer_question", fake_answer)
    at = _unlock(AppTest.from_file(APP))

    box = next(t for t in at.text_input if "Maintenance" in (t.placeholder or ""))
    box.input("Which cost grew the most?")
    next(b for b in at.button if b.label == "Ask").click()
    _run(at)
    for _ in range(3):  # further reruns must not re-send
        _run(at)

    assert calls == ["Which cost grew the most?"]
    assert any("Answer to: Which cost grew the most?" in m.value for m in at.markdown)
