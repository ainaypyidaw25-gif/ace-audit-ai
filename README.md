# ACE Audit AI — Executive Dashboard

Single-user (CEO) Streamlit app that compares two monthly financial statements with Google Gemini
and keeps a persistent history of every analysis.

- **Passcode gate** — one shared passcode (`APP_PASSCODE`), no accounts
- **AI extraction** — PDF / PNG / JPG / WEBP / XLSX / XLS / CSV → income, expenses, net profit, balances, line items
- **Calculations** — totals, net variance, growth rate %, profit margin %, expense ratio, multiples
- **CEO Quick Summary** — Gemini writes bullet-point insights with 🔴 red flags (Myanmar or English)
- **Discrepancy alerts** — net ≠ income − expense, line items ≠ totals, balance roll-forward, abnormal swings
- **History & trends** — every report is stored in SQLite; browse past reports, delete, and view trend lines

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export APP_PASSCODE="your-passcode"
export GEMINI_API_KEY="your-gemini-key"   # optional, can also be typed in the sidebar
streamlit run app.py
```

Or put both values in `.streamlit/secrets.toml` (see `secrets.toml.example`).
The database is created automatically at `data/ace_audit.db` (override with `ACE_DB_PATH`).

## Deploy on Streamlit Community Cloud

1. Push to GitHub, create the app at https://share.streamlit.io (main file `app.py`, Python 3.11).
2. **App settings → Secrets**:

```toml
GEMINI_API_KEY = "your-gemini-key"
APP_PASSCODE   = "your-passcode"
```

> **Important:** Streamlit Community Cloud's filesystem is ephemeral. The SQLite history is kept
> while the app is running but is wiped on every redeploy / reboot. For durable history, run the
> app on a VPS (Docker, systemd) where `data/` is on persistent disk, or point `ACE_DB_PATH` at a
> mounted volume.

## Deploy on a VPS

```bash
pip install -r requirements.txt
APP_PASSCODE=... GEMINI_API_KEY=... streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

Put nginx/Caddy in front for HTTPS. Back up `data/ace_audit.db` regularly.
