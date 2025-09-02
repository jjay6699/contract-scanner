"""
Vercel serverless endpoint: returns latest scanner state.

If KV is configured, reads persisted state. Otherwise, does a quick on-demand scan.
"""

import os
import time
from typing import Any, Dict

from flask import jsonify

from app.scan import scan_latest_created_contract
from api.kv import kv_available, kv_get_json


def handler(request):
    if kv_available():
        state = kv_get_json("scanner:state") or {}
        return jsonify(state)

    # Fallback: run a quick scan (reduced pages) to return something without KV
    latest = scan_latest_created_contract(
        api_key=os.environ.get("ETHERSCAN_API_KEY"),
        deployer=os.environ.get("DEPLOYER"),
        chain_id=int(os.environ.get("CHAIN_ID", "8453")),
        max_pages=int(os.environ.get("MAX_PAGES_ON_DEMAND", "3")),
    )
    now_utc = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    return jsonify(
        {
            "latest": latest,
            "last_run_utc": now_utc,
            "last_error": None,
            "runs": 1,
            "history": [latest] if latest else [],
            "chain_id": int(os.environ.get("CHAIN_ID", "8453")),
            "deployer": os.environ.get("DEPLOYER") or "0x048ef1062cbb39B338Ac2685dA72adf104b4cEF5",
            "history_max": int(os.environ.get("HISTORY_MAX", "50")),
            "interval_seconds": int(os.environ.get("SCAN_INTERVAL_SECONDS", "60")),
            "kv": False,
        }
    )

