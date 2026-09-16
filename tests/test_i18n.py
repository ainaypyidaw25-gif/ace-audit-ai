"""Every piece of interface text must exist in both languages and format cleanly."""

from __future__ import annotations

import io
import re
import string

import openpyxl
import pytest

import ai
import i18n
from export import build_excel_report
from finance import build_alerts, compute_metrics
from i18n import EN, MY, t

MYANMAR_CHARS = re.compile(r"[က-႟]")


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.mark.parametrize("table_name", ["STRINGS", "ALERTS", "ITEM_NAMES", "RATIO_NAMES",
                                        "METRIC_NAMES", "KIND_NAMES"])
def test_every_entry_has_both_languages_with_same_placeholders(table_name):
    table = getattr(i18n, table_name)
    for key, entry in table.items():
        assert set(entry) == {MY, EN}, f"{table_name}[{key}] missing a language"
        assert entry[MY].strip() and entry[EN].strip(), f"{table_name}[{key}] is empty"
        assert _placeholders(entry[MY]) == _placeholders(entry[EN]), \
            f"{table_name}[{key}] placeholders differ between languages"


def test_myanmar_text_is_actually_myanmar():
    exempt = {"language", "api_key", "model", "dl_json", "dl_excel", "col_report", "pts"}
    for key, entry in i18n.STRINGS.items():
        if key not in exempt:
            assert MYANMAR_CHARS.search(entry[MY]), f"STRINGS[{key}] has no Myanmar text"


def test_unknown_language_falls_back_to_myanmar():
    assert t("unlock", "fr") == t("unlock", MY)


def _all_alert_codes(jan, feb):
    """Build statements that trigger every alert code at least once."""
    jan.update(opening_balance=100.0, closing_balance=999.0, notes="Scanned copy was blurry")
    feb.update(opening_balance=500.0, net_profit=-1.0, currency="USD",
               total_expense=feb["total_expense"] * 2)
    feb["income_items"] = [i for i in feb["income_items"] if i["category"] != "Event Hall"]
    metrics = compute_metrics(jan, feb, "Jan", "Feb")
    return build_alerts(jan, feb, metrics, 5.0, "Jan", "Feb")


def test_alert_codes_all_have_templates_and_render(jan, feb):
    alerts = _all_alert_codes(jan, feb)
    codes = {a["code"] for a in alerts}
    assert codes <= set(i18n.ALERTS)
    for a in alerts:
        my = i18n.alert_text(a, MY)
        en = i18n.alert_text(a, EN)
        assert en == a["message"]
        assert MYANMAR_CHARS.search(my) and my != en


def test_alert_fixture_covers_most_codes(jan, feb):
    codes = {a["code"] for a in _all_alert_codes(jan, feb)}
    missing = set(i18n.ALERTS) - codes - {"net_mismatch", "income_items_mismatch", "category_new",
                                          "category_swing"}
    assert not missing, f"fixture does not exercise: {missing}"


def test_braces_in_user_text_do_not_break_formatting():
    alert = {"code": "ai_note", "params": {"label": "Jan {x}", "note": "total {0} ok"}}
    assert i18n.alert_text(alert, MY) == "Jan {x} AI မှတ်ချက်: total {0} ok"


def test_broken_stored_params_fall_back_to_message():
    alert = {"code": "net_loss", "params": {}, "message": "fallback"}
    assert i18n.alert_text(alert, MY) == "fallback"


def test_friendly_errors_translate():
    msg = ai.friendly_error(RuntimeError("429 RESOURCE_EXHAUSTED"), "gemini-x", MY)
    assert "gemini-x" in msg and MYANMAR_CHARS.search(msg)
    err = ai.ExtractionError("feb.pdf")
    assert "feb.pdf" in ai.friendly_error(err, "m", MY)
    assert ai.friendly_error(err, "m", EN) == str(err)


def test_excel_export_in_myanmar(report):
    wb = openpyxl.load_workbook(io.BytesIO(build_excel_report(report, MY)))
    summary = wb["Summary"]
    assert summary["A4"].value == t("xl_key_figure", MY)
    assert summary["A5"].value == t("xl_total_income", MY)
    assert summary["B5"].value == 63_000_000               # numbers unchanged
    assert wb["Totals"]["A3"].value == "စုစုပေါင်း ဝင်ငွေ"
    alert_cells = [wb["Alerts"].cell(r, 2).value for r in range(2, wb["Alerts"].max_row + 1)]
    assert all(MYANMAR_CHARS.search(c) for c in alert_cells)
