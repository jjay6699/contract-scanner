import json
import os
from typing import Any, Dict, Optional

import requests


def _kv_config() -> Optional[Dict[str, str]]:
    # Support Vercel KV and Upstash Redis REST
    url = (
        os.environ.get("KV_REST_API_URL")
        or os.environ.get("VERCEL_KV_REST_API_URL")
        or os.environ.get("UPSTASH_REDIS_REST_URL")
    )
    token = (
        os.environ.get("KV_REST_API_TOKEN")
        or os.environ.get("VERCEL_KV_REST_API_TOKEN")
        or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    )
    if url and token:
        return {"url": url.rstrip("/"), "token": token}
    return None


def kv_available() -> bool:
    return _kv_config() is not None


def kv_get_json(key: str) -> Optional[Any]:
    cfg = _kv_config()
    if not cfg:
        return None
    # Upstash/Vercel KV REST GET
    url = f"{cfg['url']}/get/{key}"
    r = requests.get(url, headers={"Authorization": f"Bearer {cfg['token']}"}, timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    val = data.get("result")
    if val is None:
        return None
    try:
        return json.loads(val)
    except Exception:
        return val


def kv_set_json(key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    cfg = _kv_config()
    if not cfg:
        return
    body = {
        "value": json.dumps(value),
    }
    if ttl_seconds and ttl_seconds > 0:
        body["ex"] = ttl_seconds
    url = f"{cfg['url']}/set/{key}"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"},
        data=json.dumps(body),
        timeout=10,
    )
    r.raise_for_status()

