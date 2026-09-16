from __future__ import annotations

from types import SimpleNamespace


def test_sqlite_round_trip(sqlite_storage, report):
    s = sqlite_storage
    assert not s.using_supabase()
    rid = s.save_report(report)
    got = s.get_report(rid)
    assert got["title"] == report["title"]
    assert got["data2"]["total_income"] == report["data2"]["total_income"]
    assert got["summary"] == report["summary"]            # Myanmar text survives
    assert got["alerts"] == report["alerts"]
    assert got["metrics"]["totals"][1]["Item"] == "Total Income"


def test_sqlite_list_newest_first_and_delete(sqlite_storage, report):
    s = sqlite_storage
    a = s.save_report({**report, "title": "first"})
    b = s.save_report({**report, "title": "second"})
    assert [r["id"] for r in s.list_reports()] == [b, a]
    s.delete_report(a)
    assert [r["id"] for r in s.list_reports()] == [b]
    assert s.get_report(a) is None


def test_trend_frame_uses_label_when_period_unknown(sqlite_storage, report):
    s = sqlite_storage
    s.save_report(report)
    s.save_report({**report, "title": "No period", "period2": "Unspecified"})
    df = s.trend_frame()
    assert list(df["Period"]) == ["February 2026", "No period"]
    assert list(df["Net Profit"]) == [10_900_000.0, 10_900_000.0]


def test_health_check(sqlite_storage, report):
    s = sqlite_storage
    s.save_report(report)
    assert s.health_check() == (True, "1 report(s) stored")


def test_supabase_path_issues_expected_queries(monkeypatch, report):
    import storage

    calls = []

    class Query:
        def __init__(self): self.ops = []
        def __getattr__(self, name):
            def op(*args, **kwargs):
                self.ops.append((name, args, kwargs))
                return self
            return op
        def execute(self):
            calls.append(self.ops)
            if self.ops[0][0] == "insert":
                return SimpleNamespace(data=[{"id": 42}])
            return SimpleNamespace(data=[{**report, "id": 42}])

    monkeypatch.setattr(storage, "_secret",
                        lambda name, default="": {"SUPABASE_URL": "https://demo.supabase.co",
                                                  "SUPABASE_KEY": "k"}.get(name, default))
    monkeypatch.setattr(storage, "_sb", lambda: SimpleNamespace(table=lambda name: Query()))

    assert storage.using_supabase()
    assert storage.backend_label().startswith("Supabase · demo")
    assert storage.save_report(report) == 42
    assert storage.get_report(42)["title"] == report["title"]
    storage.delete_report(42)
    assert [op[0] for op in calls[0]] == ["insert"]
    assert [op[0] for op in calls[1]] == ["select", "eq", "limit"]
    assert [op[0] for op in calls[2]] == ["delete", "eq"]


# --------------------------------------------------------------------------- backup / restore
import json

import pytest


def test_backup_round_trip_into_empty_storage(sqlite_storage, report, tmp_path, monkeypatch):
    s = sqlite_storage
    s.save_report(report)
    s.save_report({**report, "title": "second", "created_at": "2026-09-17T09:00:00"})
    raw = s.make_backup("2026-09-17T10:00:00")

    payload = json.loads(raw)
    assert payload["app"] == "ace-audit-ai" and len(payload["reports"]) == 2

    monkeypatch.setattr(s, "DB_PATH", tmp_path / "fresh.db")      # simulate a wiped cloud disk
    assert s.list_reports() == []
    assert s.restore_reports(s.parse_backup(raw)) == (2, 0)
    restored = {r["title"]: r for r in s.all_reports()}
    assert set(restored) == {report["title"], "second"}
    assert restored[report["title"]]["summary"] == report["summary"]      # Myanmar text intact
    assert restored[report["title"]]["alerts"] == report["alerts"]


def test_restoring_the_same_backup_twice_adds_nothing(sqlite_storage, report):
    s = sqlite_storage
    s.save_report(report)
    raw = s.make_backup("now")
    assert s.restore_reports(s.parse_backup(raw)) == (0, 1)
    assert len(s.list_reports()) == 1


@pytest.mark.parametrize("raw, reason", [
    (b"\x89PNG not json", "not_json"),
    (json.dumps({"hello": 1}).encode(), "wrong_app"),
    (json.dumps({"app": "ace-audit-ai", "version": 99, "reports": []}).encode(), "newer_version"),
    (json.dumps({"app": "ace-audit-ai", "version": 1}).encode(), "no_reports"),
    (json.dumps({"app": "ace-audit-ai", "version": 1, "reports": [{"title": "x"}]}).encode(), "bad_report"),
])
def test_parse_backup_rejects_bad_files_with_a_reason(sqlite_storage, raw, reason):
    with pytest.raises(sqlite_storage.BackupError) as err:
        sqlite_storage.parse_backup(raw)
    assert str(err.value) == reason


def test_parse_backup_accepts_utf8_bom(sqlite_storage, report):
    sqlite_storage.save_report(report)
    raw = b"\xef\xbb\xbf" + sqlite_storage.make_backup("now")
    assert len(sqlite_storage.parse_backup(raw)) == 1
