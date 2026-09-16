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
