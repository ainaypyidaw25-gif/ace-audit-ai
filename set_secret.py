#!/usr/bin/env python3
"""
Write one secret into .streamlit/secrets.toml from the macOS clipboard.

No typing, no text editor, nothing echoed to the screen:

    1. Copy the value (Cmd+C) from Google AI Studio or the Supabase dashboard
    2. Run:  python3 set_secret.py GEMINI_API_KEY

Valid names: APP_PASSCODE, GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY

The file is rewritten as valid TOML with correct quoting, and the script prints
only the length of what it stored, never the value itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SECRETS = Path(os.environ.get("ACE_SECRETS_PATH",
                              Path(__file__).parent / ".streamlit" / "secrets.toml"))
ORDER = ["APP_PASSCODE", "GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"]


def read_existing() -> dict[str, str]:
    values = {k: "" for k in ORDER}
    if SECRETS.exists():
        for line in SECRETS.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def clipboard() -> str:
    try:
        out = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Could not read the clipboard: {exc}", file=sys.stderr)
        raise SystemExit(2)
    return out.stdout.strip()


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ORDER:
        print(__doc__)
        print(f"Usage: python3 {Path(sys.argv[0]).name} <{'|'.join(ORDER)}>")
        return 1

    name = sys.argv[1]
    value = clipboard()
    if not value:
        print("The clipboard is empty. Copy the value first, then run this again.")
        return 1
    if "\n" in value:
        print("The clipboard holds more than one line. Copy just the single value.")
        return 1
    if name == "SUPABASE_URL" and not value.startswith("https://"):
        print(f"That does not look like a URL (starts with '{value[:8]}...'). "
              "Copy the Supabase Project URL.")
        return 1
    if name == "SUPABASE_KEY" and value.startswith("https://"):
        print("That is a URL, not a key. Copy the service_role key instead.")
        return 1

    values = read_existing()
    values[name] = value.replace('"', "")

    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Local dev only (gitignored). Written by set_secret.py."]
    lines += [f'{k} = "{values.get(k, "")}"' for k in ORDER]
    SECRETS.write_text("\n".join(lines) + "\n")

    print(f"Stored {name} ({len(value)} characters) in {SECRETS}\n")
    print("Current state:")
    for k in ORDER:
        v = values.get(k, "")
        shown = v if k == "SUPABASE_URL" else (f"{len(v)} characters" if v else "")
        print(f"  {k:16s} {shown or '(empty)'}")
    ready = bool(values.get("SUPABASE_URL") and values.get("SUPABASE_KEY"))
    print(f"\nStorage backend on next run: {'Supabase (persistent)' if ready else 'SQLite'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
