"""
Headless tests of the Streamlit UI with streamlit.testing (no browser, no network).

These guard the UI bugs that unit tests of the modules cannot see: the passcode gate,
duplicate widget keys when one report renders in two tabs, the delete confirmation,
the Q&A form calling Gemini exactly once per question, and the Myanmar/English switch.
Widgets are found by key, so the tests do not depend on the display language.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import ai
from i18n import EN, MY, t

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


def _unlock(at: AppTest, code: str = "test-pass", lang: str | None = None) -> AppTest:
    _run(at)
    if lang:
        at.radio(key="lang").set_value(lang)
        _run(at)
    at.text_input(key="passcode").input(code)
    at.button(key="btn_unlock").click()
    return _run(at)


def test_default_language_is_myanmar(app_env):
    at = _run(AppTest.from_file(APP))
    assert at.radio(key="lang").value == MY
    assert at.button(key="btn_unlock").label == t("unlock", MY)


def test_passcode_gate_blocks_wrong_code(app_env):
    at = _unlock(AppTest.from_file(APP), code="wrong")
    assert any(t("wrong_passcode", MY) in e.value for e in at.error)
    assert not at.tabs


@pytest.mark.parametrize("lang", [MY, EN])
def test_passcode_gate_unlocks_in_each_language(app_env, lang):
    at = _unlock(AppTest.from_file(APP), lang=lang)
    assert [x.label for x in at.tabs][:3] == [t("tab_new", lang), t("tab_history", lang),
                                              t("tab_trend", lang)]


def test_missing_passcode_config_is_explained(monkeypatch, sqlite_storage):
    monkeypatch.delenv("APP_PASSCODE", raising=False)
    at = AppTest.from_file(APP)
    at.secrets["APP_PASSCODE"] = ""
    _run(at)
    assert any("APP_PASSCODE" in e.value for e in at.error)
    assert not at.text_input  # no login box when nothing can be checked


@pytest.mark.parametrize("lang", [MY, EN])
def test_history_report_and_alerts_render_in_language(app_env, report, lang):
    rid = app_env.save_report(report)
    at = _unlock(AppTest.from_file(APP), lang=lang)
    assert at.button(key=f"del_{rid}").label == t("delete", lang)
    assert any(t("qa_h", lang) in m.value for m in at.markdown)
    shown = [w.value for w in at.warning] + [i.value for i in at.info]
    maintenance = next(s for s in shown if "Maintenance" in s)
    if lang == MY:
        assert "ပြောင်းလဲခဲ့သည်" in maintenance
    else:
        assert "Expense 'Maintenance' changed +209.1%." == maintenance


def test_old_reports_without_alert_codes_still_render(app_env, report):
    """Reports saved before alerts carried codes only have an English message."""
    report["alerts"] = [{"severity": "warning", "message": "Legacy alert text"}]
    app_env.save_report(report)
    at = _unlock(AppTest.from_file(APP))
    assert any("Legacy alert text" in w.value for w in at.warning)


def test_same_report_in_two_tabs_has_unique_widget_keys(app_env, report):
    """Latest analysis and the same report under Previous Reports must not clash."""
    rid = app_env.save_report(report)
    at = _unlock(AppTest.from_file(APP))
    at.session_state["last_report"] = {**report, "id": rid}
    _run(at)  # would raise StreamlitDuplicateElementKey before the fix


def test_delete_requires_confirmation(app_env, report):
    rid = app_env.save_report(report)
    at = _unlock(AppTest.from_file(APP))
    at.button(key=f"del_{rid}").click()
    _run(at)
    assert any(f"#{rid}" in w.value for w in at.warning)
    assert len(app_env.list_reports()) == 1            # nothing deleted yet
    at.button(key=f"no_{rid}").click()
    _run(at)
    assert len(app_env.list_reports()) == 1
    at.button(key=f"del_{rid}").click()
    _run(at)
    at.button(key=f"yes_{rid}").click()
    _run(at)
    assert app_env.list_reports() == []


def test_question_is_sent_to_gemini_exactly_once(app_env, report, monkeypatch):
    """Regression: a non-empty text box was treated as a new question on every rerun,
    so one question looped against the Gemini API until quota ran out."""
    rid = app_env.save_report(report)
    calls = []

    def fake_answer(api_key, model, rec, question, history, language, client=None):
        calls.append((question, language))
        return f"Answer to: {question}"

    monkeypatch.setattr(ai, "answer_question", fake_answer)
    at = _unlock(AppTest.from_file(APP))

    state_key = f"qa_history_{rid}"
    at.text_input(key=f"q_{state_key}").input("Which cost grew the most?")
    at.button(key=f"ask_{state_key}").click()
    _run(at)
    for _ in range(3):  # further reruns must not re-send
        _run(at)

    assert calls == [("Which cost grew the most?", "Myanmar")]
    assert any("Answer to: Which cost grew the most?" in m.value for m in at.markdown)
