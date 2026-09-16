# ACE Audit AI — Executive Dashboard

Single-user (CEO) Streamlit app that compares two monthly financial statements with Google Gemini
and keeps a persistent history of every analysis.

- **Passcode gate** — one shared passcode (`APP_PASSCODE`), no accounts
- **AI extraction** — PDF / PNG / JPG / WEBP / XLSX / XLS / CSV → income, expenses, net profit, balances, line items
- **Calculations** — totals, net variance, growth rate %, profit margin %, expense ratio, multiples
- **CEO Quick Summary** — Gemini writes bullet-point insights with 🔴 red flags (Myanmar or English)
- **Discrepancy alerts** — net ≠ income − expense, line items ≠ totals, balance roll-forward, abnormal swings
- **Ask about a report** — follow-up questions answered by Gemini from that report's data only
- **Excel export** — Summary, Totals, Ratios, Income, Expenses and Alerts sheets with real numbers
- **History & trends** — every report is stored; browse, delete (with confirmation), view trend lines

## Project layout

| File | Responsibility |
|---|---|
| `app.py` | Streamlit UI only |
| `finance.py` | Calculations and alerts — pure functions |
| `ai.py` | Gemini extraction, CEO summary, report Q&A |
| `export.py` | Excel workbook export |
| `storage.py` | Supabase / SQLite persistence |
| `tests/` | pytest suite, including headless UI tests |

## Tests

```bash
pip install pytest
python -m pytest -q
```

The suite needs no API key and makes no network calls: Gemini is replaced by fake clients,
storage uses a temporary SQLite file, and the UI runs headless through `streamlit.testing`.

## Storage

Two backends, chosen automatically:

| Backend | When it is used | Survives redeploy? |
|---|---|---|
| **Supabase (Postgres)** | `SUPABASE_URL` and `SUPABASE_KEY` are set | Yes |
| **SQLite** | otherwise (file at `ACE_DB_PATH`, default `data/ace_audit.db`) | Only on a persistent disk |

Streamlit Community Cloud wipes its filesystem on every reboot, so **use Supabase there** if the
CEO needs month-over-month history. The sidebar always shows which backend is live.

### Supabase setup (5 minutes)

1. Create a free project at https://supabase.com.
2. **SQL Editor → New query**, paste [`supabase_schema.sql`](supabase_schema.sql), press Run.
3. **Project Settings → API**, copy the Project URL and the **`service_role`** key.
4. Put both in your secrets (see below).

The `service_role` key is used only by the Streamlit server, never sent to the browser. The schema
enables Row Level Security with no policies, so the table is unreadable to anyone else.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Setting secrets

Two helper scripts avoid hand-editing TOML (a stray quote or an unsaved editor buffer is the
usual cause of "key not found"):

```bash
python3 configure.py                      # prompts for all four values, input hidden
python3 set_secret.py GEMINI_API_KEY      # takes one value from the macOS clipboard
```

`set_secret.py` accepts `APP_PASSCODE`, `GEMINI_API_KEY`, `SUPABASE_URL` or `SUPABASE_KEY`, and
rejects an obviously wrong paste (a URL where a key belongs, and vice versa). Neither script ever
prints a secret back. Or edit `.streamlit/secrets.toml` directly (see `secrets.toml.example`):

```toml
APP_PASSCODE   = "your-passcode"
GEMINI_API_KEY = "your-gemini-key"
SUPABASE_URL   = ""   # optional
SUPABASE_KEY   = ""   # optional
```

Every value must be wrapped in double quotes. Environment variables of the same names also work and
take precedence.

## Deploy on Streamlit Community Cloud

1. Push to GitHub, create the app at https://share.streamlit.io (main file `app.py`, Python 3.11).
2. **App settings → Secrets**: paste the same four keys as above, with Supabase filled in.
3. **App settings → Sharing**: keep it private, or set "Anyone with the link" — the passcode gate
   still applies either way.

## Deploy on a VPS

```bash
pip install -r requirements.txt
APP_PASSCODE=... GEMINI_API_KEY=... streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

Put nginx/Caddy in front for HTTPS. On a VPS the SQLite fallback is fine — back up `data/ace_audit.db`.

## Gemini free-tier quota

Google's free tier allows roughly **20 requests per day per model**. One analysis costs three
requests (two extractions plus the summary), so expect about six analyses per model per day.
When a model is exhausted the app says so and you can pick another in the sidebar. For regular use,
enable billing in Google AI Studio.
