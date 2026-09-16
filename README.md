# ACE Audit AI

Streamlit web app that compares two monthly financial statements using Google Gemini.

- Upload two files (PDF, PNG/JPG/WEBP, XLSX/XLS, CSV)
- Gemini extracts income, expenses, net profit, balances and line items as JSON
- The app computes totals, net differences, growth rates, margins and ratios
- Discrepancies (net ≠ income − expense, line items ≠ totals, balance roll-forward, abnormal % swings) are flagged

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Enter your Gemini API key in the sidebar, or set it once:

```bash
export GEMINI_API_KEY="your-key"
```

## Deploy on Streamlit Cloud

1. Push this folder to a GitHub repo.
2. On https://share.streamlit.io create a new app, main file `app.py`.
3. In **App settings → Secrets** add:

```toml
GEMINI_API_KEY = "your-key"
```

Users can still override the key from the sidebar input box.

## Deploy on any server

```bash
pip install -r requirements.txt
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

Put it behind nginx/Caddy for HTTPS if exposed publicly.
