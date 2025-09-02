Web app: Latest contract deployment scanner (Base)

What it does
- Runs a background scan every 2 minutes to find the most recent contract created by a deployer on Base (chain id 8453) using Etherscan v2 API.
- Serves a small Flask web UI at `/` and a JSON endpoint at `/api/latest` with the latest result.

Prerequisites
- Python 3.9+
- For the web UI: Flask and requests (installed via `pip`).
- For the console runner: no extra packages needed.

Configuration (env vars)
- `ETHERSCAN_API_KEY` (required): your API key.
- `DEPLOYER` (optional): deployer address to monitor. Default: `0x048ef1062cbb39B338Ac2685dA72adf104b4cEF5`.
- `CHAIN_ID` (optional): default `8453` (Base mainnet).
- `SCAN_INTERVAL_SECONDS` (optional): default `120`.
- `HOST`/`PORT` (optional): default `127.0.0.1:8000`.

Quick run (console, no installs)
```
python monitor.py
```

Install deps (for web UI)
```
pip install -r requirements.txt
```

Run the web app
```
python -m app.web
```

Endpoints
- `/` – simple HTML page with links to Basescan.
- `/api/latest` – JSON with `latest`, `last_run_utc`, `last_error`, `runs`.
- `/healthz` – returns `ok`.

Deploy to Vercel
- What’s included:
  - `public/index.html`: static UI that calls `/api/latest`.
  - `api/scan.py`: serverless function that performs one scan and persists to KV (if configured).
  - `api/latest.py`: returns the latest state from KV, or does a quick on-demand scan if KV is not set.
  - `vercel.json`: sets Python runtime and a 1-minute cron to hit `/api/scan`.
- Required env vars in Vercel Project Settings → Environment Variables:
  - `ETHERSCAN_API_KEY` (required)
  - `DEPLOYER` (optional)
  - `CHAIN_ID` (optional, default 8453)
  - `HISTORY_MAX` (optional, default 50)
  - (Optional KV) Either Vercel KV or Upstash Redis REST:
    - `KV_REST_API_URL` and `KV_REST_API_TOKEN` (Vercel KV), or
    - `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` (Upstash)
- Notes:
  - Without KV, `/api/latest` will run a reduced scan on-demand (default `MAX_PAGES_ON_DEMAND=3`). History is not persisted in serverless memory.
  - With KV configured, `/api/scan` (via cron) maintains a rolling history and `/api/latest` reads it instantly.

Git + GitHub quick start
1) Initialize repo
```
git init
git add .
git commit -m "Initial scanner + web + vercel"
```
2) Create GitHub repo (via web UI) and add remote
```
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main
git push -u origin main
```
3) Import into Vercel
- In Vercel, “Add New Project” → Import your GitHub repo.
- Set Environment Variables (see above), and add Vercel KV integration if you want history persistence.
- Deploy. The static UI will be at `/`, serverless functions at `/api/*`.

Notes
- The console runner and web app include a built-in fallback API key based on your original script; you can override by setting `ETHERSCAN_API_KEY`.
- The scanner logs a one-line summary for each run.
- If your environment blocks network access, scans will error until outbound HTTP is permitted.
