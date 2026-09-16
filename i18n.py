"""
User-interface text in Myanmar and English.

    t("analyze", lang)                 -> button label
    t("saved", lang, id=3)             -> formatted message
    alert_text(alert, lang)            -> an alert from finance.build_alerts, in `lang`
    item_name / ratio_name / column    -> translate stored metric labels at display time

Stored reports keep English labels and alert codes, so switching language re-renders old
reports too. tests/test_i18n.py checks that every key exists in both languages and that
every template formats with the parameters finance.py supplies.
"""

from __future__ import annotations

from typing import Any

MY, EN = "my", "en"
LANGUAGES = {MY: "မြန်မာ", EN: "English"}
AI_LANGUAGE = {MY: "Myanmar", EN: "English"}   # what ai.py expects

STRINGS: dict[str, dict[str, str]] = {
    # ---- chrome -------------------------------------------------------------
    "language": {MY: "ဘာသာစကား / Language", EN: "ဘာသာစကား / Language"},
    "subtitle": {MY: "အမှုဆောင်အရာရှိချုပ်အတွက် ငွေစာရင်း နှိုင်းယှဉ်စစ်ဆေးရေး Dashboard",
                 EN: "Executive Financial Comparison Dashboard"},
    "restricted": {MY: "ခွင့်ပြုထားသူသာ ဝင်ရောက်နိုင်သည်", EN: "Restricted access"},
    "powered": {MY: "Google Gemini ဖြင့် လုပ်ဆောင်သည်", EN: "Powered by Google Gemini"},

    # ---- passcode -----------------------------------------------------------
    "passcode_missing": {
        MY: "APP_PASSCODE မသတ်မှတ်ရသေးပါ။ Environment variable သို့မဟုတ် "
            ".streamlit/secrets.toml တွင် ထည့်ပြီး app ကို ပြန်စတင်ပါ။",
        EN: "APP_PASSCODE is not configured. Set it as an environment variable or in "
            ".streamlit/secrets.toml, then restart the app."},
    "enter_passcode": {MY: "လျှို့ဝှက်နံပါတ် ထည့်ပါ", EN: "Enter passcode"},
    "unlock": {MY: "ဝင်မည်", EN: "Unlock"},
    "wrong_passcode": {MY: "လျှို့ဝှက်နံပါတ် မှားနေပါသည်။", EN: "Incorrect passcode."},

    # ---- sidebar ------------------------------------------------------------
    "settings": {MY: "⚙️ ဆက်တင်များ", EN: "⚙️ Settings"},
    "api_key": {MY: "Google Gemini API Key", EN: "Google Gemini API Key"},
    "model": {MY: "Gemini model", EN: "Gemini model"},
    "model_help": {MY: "Model တစ်ခု၏ နေ့စဉ် အခမဲ့ quota ကုန်သွားပါက အခြား model ကို ရွေးပါ။",
                   EN: "If a model's daily free quota runs out, pick another one."},
    "threshold": {MY: "သတိပေးရန် ပြောင်းလဲမှု အတိုင်းအတာ (%)", EN: "Red-flag threshold (% change)"},
    "stored_reports": {MY: "📚 သိမ်းထားသော report များ: {n}", EN: "📚 Stored reports: {n}"},
    "storage": {MY: "သိမ်းဆည်းရာ: {label}", EN: "Storage: {label}"},
    "storage_unreachable": {MY: "သိမ်းဆည်းရာသို့ မချိတ်ဆက်နိုင်ပါ: {error}",
                            EN: "Storage unreachable: {error}"},
    "storage_sqlite": {MY: "SQLite · {path} (Cloud တွင် redeploy လုပ်တိုင်း ပျက်ပါမည်)",
                       EN: "SQLite · {path} (wiped on redeploy in the cloud)"},
    "storage_supabase": {MY: "Supabase · {host} (အမြဲ သိမ်းဆည်းထားသည်)",
                         EN: "Supabase · {host} (persistent)"},
    "lock": {MY: "🔒 Dashboard ပိတ်မည်", EN: "🔒 Lock dashboard"},

    # ---- tabs ---------------------------------------------------------------
    "tab_new": {MY: "🆕 စစ်ဆေးမှု အသစ်", EN: "🆕 New Analysis"},
    "tab_history": {MY: "📚 ယခင် Report များ", EN: "📚 Previous Reports"},
    "tab_trend": {MY: "📈 လမ်းကြောင်း ပြောင်းလဲမှု", EN: "📈 Trend Viewer"},

    # ---- new analysis -------------------------------------------------------
    "prev_label": {MY: "ယခင်လ အမည်", EN: "Previous month label"},
    "curr_label": {MY: "လက်ရှိလ အမည်", EN: "Current month label"},
    "prev_default": {MY: "ယခင်လ", EN: "Previous Month"},
    "curr_default": {MY: "လက်ရှိလ", EN: "Current Month"},
    "upload_prev": {MY: "ယခင်လ ငွေစာရင်းဖိုင် တင်ပါ", EN: "Upload previous month statement"},
    "upload_curr": {MY: "လက်ရှိလ ငွေစာရင်းဖိုင် တင်ပါ", EN: "Upload current month statement"},
    "report_title": {MY: "Report ခေါင်းစဉ်", EN: "Report title"},
    "title_default": {MY: "နှိုင်းယှဉ်စစ်ဆေးချက် {date}", EN: "Comparison {date}"},
    "analyze": {MY: "🔍 စစ်ဆေး၊ အနှစ်ချုပ်ပြီး သိမ်းမည်", EN: "🔍 Analyze, Summarize & Save"},
    "need_key": {MY: "Sidebar တွင် Gemini API key ထည့်ပါ။", EN: "Enter your Gemini API key in the sidebar."},
    "reading": {MY: "{name} ကို ဖတ်နေသည်...", EN: "Reading {name}..."},
    "calculating": {MY: "တွက်ချက်ပြီး CEO အနှစ်ချုပ် ရေးနေသည်...",
                    EN: "Calculating and writing the CEO summary..."},
    "done": {MY: "ပြီးပါပြီ", EN: "Done"},
    "saved": {MY: "Report #{id} အဖြစ် သိမ်းပြီးပါပြီ။ ယခင် Report များ tab တွင် ပြန်ကြည့်နိုင်ပါသည်။",
              EN: "Saved as report #{id} — available under Previous Reports."},
    "save_failed": {
        MY: "စစ်ဆေးမှု အောင်မြင်သော်လည်း သိမ်း၍ မရပါ: {error}\n\n"
            "အောက်တွင် ပြထားပါသည်။ မပျောက်စေရန် Excel သို့မဟုတ် JSON ဖိုင်ကို download လုပ်ထားပါ။",
        EN: "The analysis succeeded but could not be saved: {error}\n\n"
            "It is shown below — download the Excel or JSON file to keep it."},

    # ---- history ------------------------------------------------------------
    "storage_error": {MY: "Report သိမ်းဆည်းရာသို့ မချိတ်ဆက်နိုင်ပါ: {error}",
                      EN: "Cannot reach report storage: {error}"},
    "no_reports": {MY: "သိမ်းထားသော report မရှိသေးပါ။ စစ်ဆေးမှု အသစ် tab တွင် စတင်ပါ။",
                   EN: "No reports saved yet. Run an analysis in the New Analysis tab."},
    "select_report": {MY: "ယခင် report ရွေးပါ", EN: "Select a past report"},
    "delete": {MY: "🗑️ ဖျက်", EN: "🗑️ Delete"},
    "confirm_delete": {MY: "Report #{id} “{title}” ကို အပြီးဖျက်မလား။ ပြန်ယူ၍ မရပါ။",
                       EN: "Delete report #{id} “{title}” permanently? This cannot be undone."},
    "yes_delete": {MY: "ဟုတ်ကဲ့၊ ဖျက်မည်", EN: "Yes, delete"},
    "cancel": {MY: "မဖျက်တော့ပါ", EN: "Cancel"},

    # ---- trend --------------------------------------------------------------
    "trend_need_two": {MY: "Report နှစ်ခု သိမ်းပြီးမှ လမ်းကြောင်း ပြောင်းလဲမှု chart ပေါ်ပါမည်။",
                       EN: "Trend lines appear once at least two reports are saved."},
    "trend_title": {MY: "သိမ်းထားသော report များ၏ ဝင်ငွေ · ထွက်ငွေ · အသားတင်အမြတ် (လက်ရှိလ ကိန်းဂဏန်းများ)",
                    EN: "Income · Expense · Net Profit across saved reports (current-month figures)"},

    # ---- report -------------------------------------------------------------
    "caption": {MY: "{l1}: {p1}  ·  {l2}: {p2}  ·  ငွေကြေး: {cur}  ·  ဖိုင်များ: {f1}, {f2}",
                EN: "{l1}: {p1}  ·  {l2}: {p2}  ·  Currency: {cur}  ·  Files: {f1}, {f2}"},
    "card_income": {MY: "စုစုပေါင်း ဝင်ငွေ", EN: "Total Income"},
    "card_expense": {MY: "စုစုပေါင်း ထွက်ငွေ", EN: "Total Expense"},
    "card_net": {MY: "အသားတင်အမြတ်", EN: "Net Profit"},
    "card_margin": {MY: "အမြတ်ရာခိုင်နှုန်း", EN: "Profit Margin"},
    "pts": {MY: "%pt", EN: "pts"},
    "dl_json": {MY: "⬇️ JSON", EN: "⬇️ JSON"},
    "dl_excel": {MY: "📗 Excel", EN: "📗 Excel"},
    "excel_unavailable": {MY: "Excel ထုတ်၍ မရပါ: {error}", EN: "Excel export unavailable: {error}"},
    "summary_h": {MY: "🧭 CEO အနှစ်ချုပ်", EN: "🧭 CEO Quick Summary"},
    "no_summary": {MY: "ဤ report အတွက် AI အနှစ်ချုပ် မရှိပါ။", EN: "No AI summary stored for this report."},
    "alerts_h": {MY: "🚨 သတိပေးချက်များ", EN: "🚨 Red Flags & Alerts"},
    "alert_counts": {MY: "(အရေးကြီး {e} · သတိပေး {w} · မှတ်ချက် {i})",
                     EN: "({e} critical · {w} warnings · {i} notes)"},
    "no_alerts": {MY: "ကိန်းဂဏန်း မကိုက်ညီမှု သို့မဟုတ် ပုံမှန်မဟုတ်သော ပြောင်းလဲမှု မတွေ့ပါ။",
                  EN: "No discrepancies or abnormal changes detected."},
    "qa_h": {MY: "💬 ဤ report အကြောင်း မေးမြန်းရန်", EN: "💬 Ask about this report"},
    "qa_label": {MY: "မေးခွန်း", EN: "Question"},
    "qa_placeholder": {MY: "ဥပမာ - Maintenance စရိတ် ဘာကြောင့် တက်တာလဲ။",
                       EN: "e.g. Which cost grew the most?"},
    "ask": {MY: "မေးမည်", EN: "Ask"},
    "clear_chat": {MY: "မေးမြန်းမှု ရှင်းမည်", EN: "Clear conversation"},
    "thinking": {MY: "စဉ်းစားနေသည်...", EN: "Thinking..."},
    "totals_h": {MY: "➕➖ စုစုပေါင်းနှင့် ကွာခြားချက်", EN: "➕➖ Totals & Net Variance"},
    "ratios_h": {MY: "✖️➗ တိုးတက်နှုန်းနှင့် အချိုးများ", EN: "✖️➗ Growth Rates & Ratios"},
    "categories_h": {MY: "📂 အမျိုးအစားအလိုက် ခွဲခြမ်းစိတ်ဖြာချက်", EN: "📂 Category Breakdown"},
    "income_tab": {MY: "ဝင်ငွေ အမျိုးအစားအလိုက်", EN: "Income by category"},
    "expense_tab": {MY: "ထွက်ငွေ အမျိုးအစားအလိုက်", EN: "Expense by category"},
    "no_items": {MY: "အသေးစိတ် စာရင်း မတွေ့ပါ။", EN: "No line items were extracted."},
    "raw_h": {MY: "🔎 AI ဖတ်ယူထားသော မူရင်းဒေတာ (JSON)", EN: "🔎 Raw AI extraction (JSON)"},

    # ---- column headers -----------------------------------------------------
    "col_item": {MY: "အကြောင်းအရာ", EN: "Item"},
    "col_variance": {MY: "ကွာခြားချက်", EN: "Net Variance"},
    "col_combined": {MY: "ပေါင်းလဒ်", EN: "Combined"},
    "col_change_pct": {MY: "ပြောင်းလဲမှု %", EN: "Change %"},
    "col_metric": {MY: "တိုင်းတာချက်", EN: "Metric"},
    "col_category": {MY: "အမျိုးအစား", EN: "Category"},
    "col_difference": {MY: "ကွာခြားချက်", EN: "Difference"},
    "col_change": {MY: "ပြောင်းလဲမှု", EN: "Change"},
    "col_report": {MY: "Report #", EN: "Report #"},
    "col_saved": {MY: "သိမ်းသည့်အချိန်", EN: "Saved"},
    "col_period": {MY: "ကာလ", EN: "Period"},
    "col_income": {MY: "ဝင်ငွေ", EN: "Income"},
    "col_expense": {MY: "ထွက်ငွေ", EN: "Expense"},
    "col_net": {MY: "အသားတင်အမြတ်", EN: "Net Profit"},
    "col_margin_pct": {MY: "အမြတ်ရာခိုင်နှုန်း %", EN: "Profit Margin %"},

    # ---- Excel export -------------------------------------------------------
    "xl_generated": {MY: "ACE Audit AI မှ ထုတ်ပေးသည်", EN: "Generated by ACE Audit AI"},
    "xl_currency": {MY: "ငွေကြေး", EN: "Currency"},
    "xl_key_figure": {MY: "အဓိက ကိန်းဂဏန်း", EN: "Key figure"},
    "xl_total_income": {MY: "စုစုပေါင်း ဝင်ငွေ", EN: "Total income"},
    "xl_total_expense": {MY: "စုစုပေါင်း ထွက်ငွေ", EN: "Total expense"},
    "xl_net_profit": {MY: "အသားတင်အမြတ်", EN: "Net profit"},
    "xl_profit_margin": {MY: "အမြတ်ရာခိုင်နှုန်း", EN: "Profit margin"},
    "xl_alerts": {MY: "သတိပေးချက်များ", EN: "Alerts"},
    "xl_alert_counts": {MY: "အရေးကြီး {e} · သတိပေး {w} · မှတ်ချက် {i}",
                        EN: "{e} critical · {w} warnings · {i} notes"},
    "xl_summary": {MY: "CEO အနှစ်ချုပ်", EN: "CEO summary"},
    "xl_no_summary": {MY: "(အနှစ်ချုပ် မရှိပါ)", EN: "(no summary)"},
    "xl_total": {MY: "စုစုပေါင်း", EN: "Total"},
    "xl_severity": {MY: "အဆင့်", EN: "Severity"},
    "xl_message": {MY: "အကြောင်းအရာ", EN: "Message"},
    "sev_error": {MY: "အရေးကြီး", EN: "Critical"},
    "sev_warning": {MY: "သတိပေး", EN: "Warning"},
    "sev_info": {MY: "မှတ်ချက်", EN: "Note"},

    # ---- errors from ai.friendly_error --------------------------------------
    "err_quota": {
        MY: "**{model}** ၏ ယနေ့ အခမဲ့ quota ကုန်သွားပါပြီ။ Sidebar တွင် အခြား model ကို ရွေးပြီး "
            "ထပ်စမ်းပါ၊ သို့မဟုတ် Google AI Studio တွင် billing ထည့်ပါ။",
        EN: "Daily free-tier quota for **{model}** is used up. Pick a different model in the "
            "sidebar and try again, or add billing to your Google AI Studio project."},
    "err_model": {MY: "**{model}** model ကို ဤ API key ဖြင့် အသုံးပြု၍ မရပါ။ Sidebar တွင် အခြား model ကို ရွေးပါ။",
                  EN: "The model **{model}** is not available to this API key. Choose another model "
                      "in the sidebar."},
    "err_key": {MY: "Gemini API key ကို လက်မခံပါ။ Sidebar သို့မဟုတ် Secrets ထဲရှိ key ကို စစ်ဆေးပါ။",
                EN: "The Gemini API key was rejected. Check the key in the sidebar or in Secrets."},
    "err_timeout": {MY: "Gemini က အချိန်အကြာကြီး တုံ့ပြန်ခြင်း မရှိပါ။ ထပ်စမ်းပါ၊ သို့မဟုတ် ဖိုင်အသေးကို သုံးပါ။",
                    EN: "Gemini timed out. Try again, or use a smaller file."},
    "err_bad_json": {MY: "{file} အတွက် Gemini က မှန်ကန်သော JSON မပြန်ပေးပါ။ အခြား model ကို စမ်းပါ။",
                     EN: "Gemini did not return valid JSON for {file}. Try another model."},
    "err_other": {MY: "စစ်ဆေးမှု မအောင်မြင်ပါ: {error}", EN: "Analysis failed: {error}"},
}

# Stored metric labels (always English in the database) -> display text.
ITEM_NAMES = {
    "Opening Balance": {MY: "လက်ကျန်ငွေ (အစ)", EN: "Opening Balance"},
    "Total Income": {MY: "စုစုပေါင်း ဝင်ငွေ", EN: "Total Income"},
    "Total Expense": {MY: "စုစုပေါင်း ထွက်ငွေ", EN: "Total Expense"},
    "Net Profit": {MY: "အသားတင်အမြတ်", EN: "Net Profit"},
    "Closing Balance": {MY: "လက်ကျန်ငွေ (အဆုံး)", EN: "Closing Balance"},
}
RATIO_NAMES = {
    "Income growth rate": {MY: "ဝင်ငွေ တိုးတက်နှုန်း", EN: "Income growth rate"},
    "Expense growth rate": {MY: "ထွက်ငွေ တိုးတက်နှုန်း", EN: "Expense growth rate"},
    "Net profit growth rate": {MY: "အသားတင်အမြတ် တိုးတက်နှုန်း", EN: "Net profit growth rate"},
    "Profit margin (net / income)": {MY: "အမြတ်ရာခိုင်နှုန်း (အမြတ် ÷ ဝင်ငွေ)",
                                     EN: "Profit margin (net / income)"},
    "Expense ratio (expense / income)": {MY: "အသုံးစရိတ် အချိုး (ထွက်ငွေ ÷ ဝင်ငွေ)",
                                         EN: "Expense ratio (expense / income)"},
    "Income / Expense multiple": {MY: "ဝင်ငွေ ÷ ထွက်ငွေ အဆ", EN: "Income / Expense multiple"},
    "Income multiplier (current / previous)": {MY: "ဝင်ငွေ အဆ (လက်ရှိ ÷ ယခင်)",
                                               EN: "Income multiplier (current / previous)"},
    # name used by reports saved before 2026-09-16
    "Income multiplier (M2 / M1)": {MY: "ဝင်ငွေ အဆ (လက်ရှိ ÷ ယခင်)",
                                    EN: "Income multiplier (current / previous)"},
}

# Alert templates. English must stay identical to what finance.build_alerts has always
# produced, so stored reports and existing tests keep matching.
METRIC_NAMES = {
    "total_income": {MY: "စုစုပေါင်း ဝင်ငွေ", EN: "Total income"},
    "total_expense": {MY: "စုစုပေါင်း ထွက်ငွေ", EN: "Total expense"},
    "net_profit": {MY: "အသားတင်အမြတ်", EN: "Net profit"},
}
KIND_NAMES = {"income": {MY: "ဝင်ငွေ", EN: "Income"}, "expense": {MY: "ထွက်ငွေ", EN: "Expense"}}

ALERTS: dict[str, dict[str, str]] = {
    "net_mismatch": {
        MY: "{label}: ဖော်ပြထားသော အသားတင်အမြတ် {stated} သည် ဝင်ငွေ − ထွက်ငွေ {computed} နှင့် "
            "မကိုက်ညီပါ (ကွာခြားချက် {gap})။",
        EN: "{label}: stated net profit {stated} ≠ income − expense {computed} (gap {gap})."},
    "income_items_mismatch": {
        MY: "{label}: ဝင်ငွေ အသေးစိတ်များ ပေါင်းလဒ် {items} ဖြစ်သော်လည်း စုစုပေါင်း ဝင်ငွေမှာ {total} ဖြစ်နေပါသည်။",
        EN: "{label}: income line items sum to {items} but total income is {total}."},
    "expense_items_mismatch": {
        MY: "{label}: ထွက်ငွေ အသေးစိတ်များ ပေါင်းလဒ် {items} ဖြစ်သော်လည်း စုစုပေါင်း ထွက်ငွေမှာ {total} ဖြစ်နေပါသည်။",
        EN: "{label}: expense line items sum to {items} but total expense is {total}."},
    "balance_rollforward": {
        MY: "{label}: အစလက်ကျန် + အသားတင်အမြတ် = {expected} ဖြစ်သော်လည်း အဆုံးလက်ကျန်မှာ {closing} ဖြစ်နေပါသည်။",
        EN: "{label}: opening + net profit = {expected} but closing balance is {closing}."},
    "balance_break": {
        MY: "{label1} ၏ အဆုံးလက်ကျန် {closing} သည် {label2} ၏ အစလက်ကျန် {opening} နှင့် မကိုက်ညီပါ။",
        EN: "{label1} closing balance {closing} ≠ {label2} opening balance {opening}."},
    "currency_mismatch": {
        MY: "ငွေကြေး မတူပါ: {c1} နှင့် {c2}။ ငွေကြေး တူညီမှသာ နှိုင်းယှဉ်ချက်များ အဓိပ္ပာယ်ရှိပါမည်။",
        EN: "Currency differs: {c1} vs {c2}. Comparisons are not meaningful until both use the same currency."},
    "total_swing": {
        MY: "{metric} သည် {change} ပြောင်းလဲခဲ့သည် (သတ်မှတ်ချက် {threshold}%)။",
        EN: "{metric} changed {change} (threshold {threshold}%)."},
    "net_loss": {
        MY: "{label} တွင် အသားတင် အရှုံး {amount} ရှိနေပါသည်။",
        EN: "{label} shows a NET LOSS of {amount}."},
    "expense_outpaces_income": {
        MY: "ထွက်ငွေသည် ဝင်ငွေထက် ပိုမြန်စွာ တိုးလာနေသည် (ထွက်ငွေ {exp}၊ ဝင်ငွေ {inc})။",
        EN: "Expenses grew faster than income ({exp} vs {inc})."},
    "category_swing": {
        MY: "{kind} '{category}' သည် {change} ပြောင်းလဲခဲ့သည်။",
        EN: "{kind} '{category}' changed {change}."},
    "category_gone": {
        MY: "{kind} '{category}' သည် {label} တွင် မရှိတော့ပါ (ယခင် {was})။",
        EN: "{kind} '{category}' disappeared in {label} (was {was})."},
    "category_new": {
        MY: "{kind} '{category}' သည် {label} တွင် အသစ် ပေါ်လာသည် ({amount})။",
        EN: "{kind} '{category}' is new in {label} ({amount})."},
    "ai_note": {
        MY: "{label} AI မှတ်ချက်: {note}",
        EN: "{label} AI notes: {note}"},
}


def normalize_lang(lang: str | None) -> str:
    return lang if lang in LANGUAGES else MY


def t(key: str, lang: str | None = MY, **params: Any) -> str:
    entry = STRINGS[key]
    text = entry.get(normalize_lang(lang)) or entry[EN]
    return text.format(**params) if params else text


def _pick(table: dict[str, dict[str, str]], name: str, lang: str | None) -> str:
    entry = table.get(name)
    return (entry.get(normalize_lang(lang)) or name) if entry else name


def item_name(name: str, lang: str | None) -> str:
    return _pick(ITEM_NAMES, name, lang)


def ratio_name(name: str, lang: str | None) -> str:
    return _pick(RATIO_NAMES, name, lang)


def render_alert(code: str, params: dict[str, Any], lang: str | None) -> str:
    lang = normalize_lang(lang)
    p = dict(params)
    if "metric" in p:
        p["metric"] = _pick(METRIC_NAMES, p["metric"], lang)
    if "kind" in p:
        p["kind"] = _pick(KIND_NAMES, p["kind"], lang)
    return ALERTS[code][lang].format(**p)


def alert_text(alert: dict[str, Any], lang: str | None) -> str:
    """Translated text for a stored alert; older reports without a code keep their message."""
    code = alert.get("code")
    if code in ALERTS:
        try:
            return render_alert(code, alert.get("params") or {}, lang)
        except (KeyError, IndexError, ValueError):
            pass
    return alert.get("message", "")
