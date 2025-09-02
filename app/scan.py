import os
import time
from typing import Any, Dict, Optional

import requests


# Default API base supports multi-chain via chainid param
ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"


class ScanError(Exception):
    pass


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


def _get_json(url: str, tries: int = 3, timeout: int = 12) -> Dict[str, Any]:
    last_exc: Optional[Exception] = None
    with requests.Session() as s:
        for i in range(tries):
            try:
                r = s.get(url, timeout=timeout)
                r.raise_for_status()
                return r.json()
            except Exception as e:  # broad: network, decoding, etc.
                last_exc = e
                time.sleep(0.4 + i * 0.4)
    raise ScanError(f"HTTP failed: {last_exc}")


def _fetch_txs_page(
    api_key: str,
    chain_id: int,
    deployer: str,
    page: int,
    page_size: int = 100,
    timeout: int = 12,
    api_base: str = ETHERSCAN_V2,
) -> Any:
    """Recent normal transactions (descending) for the deployer."""
    params = {
        "chainid": chain_id,
        "module": "account",
        "action": "txlist",
        "address": deployer,
        "startblock": 0,
        "endblock": 99999999,
        "page": page,
        "offset": page_size,
        "sort": "desc",
        "apikey": api_key,
    }
    url = requests.Request("GET", api_base, params=params).prepare().url
    data = _get_json(url, timeout=timeout)
    if data.get("status") != "1" or not isinstance(data.get("result"), list):
        raise ScanError(f"Etherscan error (txlist): {data}")
    return data["result"]


def _fetch_internal_for_tx(
    api_key: str,
    chain_id: int,
    txhash: str,
    timeout: int = 12,
    api_base: str = ETHERSCAN_V2,
) -> Any:
    """Internal traces for a single parent tx; where the CREATE happens."""
    params = {
        "chainid": chain_id,
        "module": "account",
        "action": "txlistinternal",
        "txhash": txhash,
        "apikey": api_key,
    }
    url = requests.Request("GET", api_base, params=params).prepare().url
    data = _get_json(url, timeout=timeout)
    # When there are no internal traces, many explorers respond with status "0"/"No transactions found".
    if data.get("status") != "1":
        return []
    return data["result"]


def scan_latest_created_contract(
    api_key: Optional[str] = None,
    deployer: Optional[str] = None,
    chain_id: int = 8453,
    max_pages: int = 10,
    page_size: int = 100,
    timeout: int = 12,
    api_base: str = ETHERSCAN_V2,
) -> Optional[Dict[str, str]]:
    """Walk recent parent txs → return first internal CREATE/CREATE2 with a contractAddress.

    Returns a dict with keys: contract, tx, block, utc; or None if not found.
    """
    api_key = api_key or _get_env("ETHERSCAN_API_KEY")
    if not api_key:
        raise ScanError("ETHERSCAN_API_KEY is not set")

    deployer = (deployer or _get_env("DEPLOYER") or "0x048ef1062cbb39B338Ac2685dA72adf104b4cEF5").lower()

    for page in range(1, max_pages + 1):
        txs = _fetch_txs_page(api_key, chain_id, deployer, page, page_size, timeout, api_base)
        for tx in txs:
            txh = tx.get("hash")
            if not txh:
                continue
            internals = _fetch_internal_for_tx(api_key, chain_id, txh, timeout, api_base)
            # Look for internal creates with a non-zero contractAddress
            for it in internals:
                caddr = (it.get("contractAddress") or "").lower()
                if not caddr or caddr == "0x0000000000000000000000000000000000000000":
                    continue
                typ = (it.get("type") or "").lower()
                # Accept when type is "create" or "create2" (some explorers omit it)
                if typ not in ("create", "create2", ""):
                    continue
                # Use internal timestamp if present; otherwise parent tx's
                ts = int(it.get("timeStamp") or tx.get("timeStamp") or 0)
                return {
                    "contract": "0x" + caddr[2:] if caddr.startswith("0x") else caddr,
                    "tx": txh,
                    "block": tx.get("blockNumber"),
                    "utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)),
                }
        time.sleep(0.12)  # polite to API
    return None

