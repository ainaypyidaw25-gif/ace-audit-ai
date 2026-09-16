#!/usr/bin/env python3
"""
Interactive setup for .streamlit/secrets.toml.

Prompts for each setting, hides secret values while you type, and writes valid TOML
(correct quoting) so a stray quote or a missed save cannot break the app.

    python3 configure.py

Press Enter at any prompt to keep the current value. Nothing is printed back.
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

# ACE_SECRETS_PATH lets tests point this at a throwaway file instead of your real secrets.
SECRETS = Path(os.environ.get("ACE_SECRETS_PATH",
                              Path(__file__).parent / ".streamlit" / "secrets.toml"))

FIELDS = [
    ("APP_PASSCODE", "Passcode to unlock the dashboard", True),
    ("GEMINI_API_KEY", "Google Gemini API key (aistudio.google.com/app/apikey)", True),
    ("SUPABASE_URL", "Supabase Project URL, e.g. https://abcd.supabase.co (blank = use SQLite)", False),
    ("SUPABASE_KEY", "Supabase service_role key (blank = use SQLite)", True),
]


def read_existing() -> dict[str, str]:
    values: dict[str, str] = {}
    if not SECRETS.exists():
        return values
    for line in SECRETS.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def main() -> int:
    current = read_existing()
    print("ACE Audit AI — configuration")
    print(f"Writing to {SECRETS}\n")
    print("Press Enter to keep the current value.\n")

    out: dict[str, str] = {}
    for key, label, secret in FIELDS:
        have = current.get(key, "")
        status = f"currently set, {len(have)} characters" if have else "currently empty"
        prompt = f"{key}\n  {label}\n  [{status}]: "
        entered = getpass.getpass(prompt) if secret else input(prompt)
        out[key] = entered.strip() or have
        print()

    if out.get("SUPABASE_URL"):
        url = out["SUPABASE_URL"]
        if not re.match(r"^https://[a-z0-9-]+\.supabase\.(co|in)$", url):
            print(f"Warning: '{url}' does not look like a Supabase project URL.")
            print("  Expected something like https://abcdefgh.supabase.co\n")
        if not out.get("SUPABASE_KEY"):
            print("Warning: SUPABASE_URL is set but SUPABASE_KEY is empty — the app will use SQLite.\n")

    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Local dev only (gitignored). Written by configure.py — values are quoted for you."]
    for key, _, _ in FIELDS:
        value = out.get(key, "").replace('"', "")
        lines.append(f'{key} = "{value}"')
    SECRETS.write_text("\n".join(lines) + "\n")

    print("Saved.")
    for key, _, _ in FIELDS:
        v = out.get(key, "")
        shown = v if key == "SUPABASE_URL" else (f"{len(v)} characters" if v else "")
        print(f"  {key:16s} {shown or '(empty)'}")
    backend = "Supabase (persistent)" if out.get("SUPABASE_URL") and out.get("SUPABASE_KEY") else "SQLite"
    print(f"\nStorage backend on next run: {backend}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
