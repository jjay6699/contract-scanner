"""
Simple console runner: scans every 2 minutes and prints the latest
contract created by the configured deployer on Base (chain id 8453).

No external packages required (uses urllib). Run with:
    python monitor.py

Edit ETHERSCAN_API_KEY, DEPLOYER if desired.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


# === Your Etherscan v2 key (fallback, used unless you delete or override) ===
ETHERSCAN_API_KEY = "WNX3XI8JS1WEC7WGMU8S3DS1UMYD1ZG4FZ"

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
CHAIN_ID = 8453  # Base mainnet
DEPLOYER = "0x048ef1062cbb39B338Ac2685dA72adf104b4cEF5".lower()

# How deep to search through recent normal txs (pages * 100 tx/page)
MAX_PAGES = 10
PAGE_SIZE = 100
TIMEOUT = 12
INTERVAL_SECONDS = 60


def get_json(url: str, tries: int = 3, timeout: int = TIMEOUT) -> Dict[str, Any]:
    last: Optional[Exception] = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                data = resp.read()
                return json.loads(data.decode("utf-8"))
        except Exception as e:  # network/parsing errors
            last = e
            time.sleep(0.4 + i * 0.4)
    raise SystemExit(f"HTTP failed: {last}")


def make_url(params: Dict[str, Any]) -> str:
    return f"{ETHERSCAN_V2}?{urllib.parse.urlencode(params)}"


def fetch_txs_page(page: int) -> List[Dict[str, Any]]:
    params = {
        "chainid": CHAIN_ID,
        "module": "account",
        "action": "txlist",
        "address": DEPLOYER,
        "startblock": 0,
        "endblock": 99999999,
        "page": page,
        "offset": PAGE_SIZE,
        "sort": "desc",
        "apikey": ETHERSCAN_API_KEY,
    }
    data = get_json(make_url(params))
    if data.get("status") != "1" or not isinstance(data.get("result"), list):
        raise SystemExit(f"Etherscan v2 error (txlist): {data}")
    return data["result"]


def fetch_internal_for_tx(txhash: str) -> List[Dict[str, Any]]:
    params = {
        "chainid": CHAIN_ID,
        "module": "account",
        "action": "txlistinternal",
        "txhash": txhash,
        "apikey": ETHERSCAN_API_KEY,
    }
    data = get_json(make_url(params))
    if data.get("status") != "1":
        return []
    return data["result"]


def find_latest_created_contract() -> Optional[Dict[str, str]]:
    for page in range(1, MAX_PAGES + 1):
        txs = fetch_txs_page(page)
        for tx in txs:
            txh = tx.get("hash")
            if not txh:
                continue
            internals = fetch_internal_for_tx(txh)
            for it in internals:
                caddr = (it.get("contractAddress") or "").lower()
                if not caddr or caddr == "0x0000000000000000000000000000000000000000":
                    continue
                typ = (it.get("type") or "").lower()
                if typ not in ("create", "create2", ""):
                    continue
                ts = int(it.get("timeStamp") or tx.get("timeStamp") or 0)
                return {
                    "contract": "0x" + caddr[2:] if caddr.startswith("0x") else caddr,
                    "tx": txh,
                    "block": tx.get("blockNumber"),
                    "utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)),
                }
        time.sleep(0.12)
    return None


def run_once() -> None:
    res = find_latest_created_contract()
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    if not res:
        print(f"[{now}] No recent contract creation found. Try increasing MAX_PAGES.")
        return
    print(f"[{now}] Latest deployment on Base")
    print(f"Contract:  {res['contract']}")
    print(f"UTC:       {res['utc']}")
    print(f"Block:     {res['block']}")
    print(f"Tx:        {res['tx']}")
    print(f"Tx link:   https://basescan.org/tx/{res['tx']}")
    print(f"Address:   https://basescan.org/address/{res['contract']}")


def main() -> None:
    print(
        f"Starting monitor: chain={CHAIN_ID}, deployer={DEPLOYER}, interval={INTERVAL_SECONDS}s"
    )
    while True:
        try:
            run_once()
        except Exception as e:
            now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            print(f"[{now}] ERROR: {e}")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
