Contract Scanner (Base) — Local + Vercel

Overview
- Scans for the most recent contract created by a given deployer on Base (chain id 8453) using Etherscan v2.
- Local modes:
  - Console runner (`monitor.py`) every 60s, prints results.
  - Flask web UI (`app/web.py`) with background scanner every 60s and a live history table.
- Vercel serverless:
  - `/api/scan` runs one scan (via Cron every minute) and writes to KV (optional).
  - `/api/latest` serves the latest state; without KV it performs a quick on‑demand scan.
  - Static UI (`public/index.html`) polls `/api/latest` and renders history.

Features
- Latest result plus rolling history (default last 50), links to Basescan.
- 60‑second interval by default (local). Vercel schedules every minute via `vercel.json`.
- Minimal deps: only Flask + requests for the web UI; console runner uses stdlib.

Project Structure
- `monitor.py`: Console runner (no extra installs).
- `app/web.py`: Flask app + background scanner and JSON API.
- `app/scan.py`: Scanner logic (shared by local + serverless).
- `app/templates/index.html`: Local web UI template.
- `api/scan.py`: Vercel function to execute one scan and persist.
- `api/latest.py`: Vercel function to return current state.
- `api/kv.py`: Minimal REST client for Vercel KV or Upstash.
- `public/index.html`: Static Vercel UI.
- `vercel.json`: Vercel runtime + 1‑minute cron for `/api/scan`.
- `requirements.txt`: Deps for the Flask web app.

Local Usage
- Option A: Console (no installs)
  - Run: `python monitor.py`
  - Default interval: 60s (change in `monitor.py`).
  - Prints links to Basescan for the tx and address.

- Option B: Flask Web UI
  - Install deps: `pip install -r requirements.txt`
  - Run: `python -m app.web`
  - Open: `http://127.0.0.1:8000/`
  - Endpoints:
    - `/` — HTML UI (auto-refresh every 10s)
    - `/api/latest` — JSON (latest, history, metadata)
    - `/healthz` — returns `ok`

Configuration (env vars)
- Shared
  - `ETHERSCAN_API_KEY`: your key (recommended). If unset locally, the console/web fallback uses the embedded key from the original script (not recommended for public repos).
  - `DEPLOYER`: deployer address; default `0x048ef1062cbb39B338Ac2685dA72adf104b4cEF5`.
  - `CHAIN_ID`: default `8453`.
  - `HISTORY_MAX`: default `50`.
- Local only (Flask)
  - `SCAN_INTERVAL_SECONDS`: default `60`.
  - `HOST` / `PORT`: default `127.0.0.1:8000`.
- Serverless (Vercel) only
  - `MAX_PAGES_ON_DEMAND`: default `3` (when KV is not configured and `/api/latest` scans on demand).
  - KV (optional, enables persistent history):
    - Vercel KV: `KV_REST_API_URL`, `KV_REST_API_TOKEN`
    - Upstash Redis: `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`

Deploy to Vercel
1) Push to GitHub (or use the provided repo)
   - Ensure no secrets are committed. The serverless functions do NOT use a hardcoded key — set `ETHERSCAN_API_KEY` in Vercel.
2) Import the repo in Vercel → New Project
3) Set Environment Variables (Project Settings → Environment Variables)
   - Required: `ETHERSCAN_API_KEY`
   - Optional: `DEPLOYER`, `CHAIN_ID`, `HISTORY_MAX`
   - Optional KV for persistence: either Vercel KV or Upstash variables above
4) Deploy
   - Static UI: `/`
   - API: `/api/scan` and `/api/latest`
   - Cron: `vercel.json` schedules `/api/scan` every minute. You can also open `/api/scan` in a browser to trigger manually.

Security Notes
- Do not commit real API keys. The local console and web fallback mirror your original script for convenience, but for public repos you should set `ETHERSCAN_API_KEY` via env and remove the hardcoded key in `monitor.py` and the fallback in `app/web.py`.
- If a key was ever committed, rotate it in your Etherscan dashboard.

Troubleshooting
- Flask not reloading or stuck: stop with Ctrl+C and run again. For auto‑reload: PowerShell `setx FLASK_DEBUG 1` (new shell) or `$env:FLASK_DEBUG="1"; python -m app.web`.
- No history on Vercel: add KV env vars to persist state across invocations; without KV, `/api/latest` falls back to a quick scan each request.
- Rate limits: If you hit Etherscan limits, reduce pages (`MAX_PAGES_ON_DEMAND`) or increase the scan interval locally.

Notes
- The console runner and web app include a built-in fallback API key based on your original script; you can override by setting `ETHERSCAN_API_KEY`.
- The scanner logs a one-line summary for each run.
- If your environment blocks network access, scans will error until outbound HTTP is permitted.
