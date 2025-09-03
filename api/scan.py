"""
Vercel serverless endpoint: triggers one scan and stores results in KV (if configured).

Cron: vercel.json includes a schedule to call this every minute.
"""

import os
import time
from typing import Any, Dict, List

from app.scan import scan_latest_created_contract
from api.kv import kv_available, kv_get_json, kv_set_json


def _dedupe_cap(history: List[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for item in history:
        tx = item.get("tx")
        if not tx or tx in seen:
            continue
        seen.add(tx)
        out.append(item)
        if len(out) >= cap:
            break
    return out


def handler(request):  # Vercel Python uses `handler`
    history_max = int(os.environ.get("HISTORY_MAX", "50"))

    latest = scan_latest_created_contract(
        api_key=os.environ.get("ETHERSCAN_API_KEY"),
        deployer=os.environ.get("DEPLOYER"),
        chain_id=int(os.environ.get("CHAIN_ID", "8453")),
    )

    now_utc = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    runs = 1
    history: List[Dict[str, Any]] = []

    if kv_available():
        prev = kv_get_json("scanner:state") or {}
        runs = int(prev.get("runs", 0)) + 1
        history = prev.get("history", [])
        prev_latest = prev.get("latest") or {}
        if latest and latest.get("tx") and latest.get("tx") != prev_latest.get("tx"):
            history.insert(0, latest)
            history = _dedupe_cap(history, history_max)
        state = {
            "latest": latest,
            "last_run_utc": now_utc,
            "last_error": None,
            "runs": runs,
            "history": history,
            "chain_id": int(os.environ.get("CHAIN_ID", "8453")),
            "deployer": os.environ.get("DEPLOYER") or "0x048ef1062cbb39B338Ac2685dA72adf104b4cEF5",
            "history_max": history_max,
            "interval_seconds": int(os.environ.get("SCAN_INTERVAL_SECONDS", "10")),
        }
        kv_set_json("scanner:state", state)

    # Response
    from flask import jsonify

    return jsonify(
        {
            "ok": True,
            "latest": latest,
            "last_run_utc": now_utc,
            "runs": runs,
            "history_added": bool(latest),
            "kv": kv_available(),
        }
    )
