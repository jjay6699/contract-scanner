import os
import threading
import time
from typing import Any, Dict, Optional

import requests

from flask import Flask, jsonify, render_template, request, abort

from app.scan import scan_latest_created_contract, ScanError


def create_app() -> Flask:
    app = Flask(__name__)

    # --- Shared state for latest scan ---
    state: Dict[str, Any] = {
        "latest": None,  # type: Optional[Dict[str, Any]]
        "last_run_utc": None,  # type: Optional[str]
        "last_error": None,  # type: Optional[str]
        "runs": 0,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "history": [],  # list of recent results, most recent first
    }
    lock = threading.Lock()

    interval_seconds = int(os.environ.get("SCAN_INTERVAL_SECONDS", "10"))
    chain_id = int(os.environ.get("CHAIN_ID", "8453"))
    deployer = os.environ.get("DEPLOYER")  # default handled by scan function
    history_max = int(os.environ.get("HISTORY_MAX", "50"))
    bootstrap_count = int(os.environ.get("BOOTSTRAP_COUNT", "5"))
    bootstrap_pages = int(os.environ.get("BOOTSTRAP_MAX_PAGES", "30"))

    stop_event = threading.Event()

    def _get_env_first(*names: str) -> Optional[str]:
        for n in names:
            v = os.environ.get(n)
            if v:
                return v
        return None

    def _telegram_send(
        text: str,
        parse_mode: str = "HTML",
        *,
        token: Optional[str] = None,
        chat_id_override: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        token = token or _get_env_first(
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_TOKEN",
            "BOT_TOKEN",
            "TG_BOT_TOKEN",
        )
        chat_id = chat_id_override or _get_env_first(
            "TELEGRAM_CHAT_ID",
            "TELEGRAM_CHANNEL_ID",
            "TG_CHAT_ID",
        )
        if not token or not chat_id:
            return False  # Not configured
        try:
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            thread_id = os.environ.get("TELEGRAM_THREAD_ID")
            if thread_id:
                try:
                    payload["message_thread_id"] = int(thread_id)
                except ValueError:
                    pass
            silent = os.environ.get("TELEGRAM_SILENT", "0").strip().lower() in ("1", "true", "yes")
            if silent:
                payload["disable_notification"] = True
            timeout = int(os.environ.get("TELEGRAM_TIMEOUT", "10"))
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            r = requests.post(url, json=payload, timeout=timeout)
            if not r.ok:
                print(f"[telegram] sendMessage failed: {r.status_code} {r.text[:200]}")
                return False
            return True
        except Exception as e:
            print(f"[telegram] ERROR: {e}")
            return False

    def _short_hex(s: Optional[str], left: int = 6, right: int = 4) -> str:
        if not s:
            return ""
        if len(s) <= left + right + 2:
            return s
        return f"{s[:left]}…{s[-right:]}"

    def _telegram_send_new(latest: Optional[Dict[str, Any]]) -> None:
        if not latest:
            return
        contract = latest.get("contract") or ""
        tx = latest.get("tx") or ""
        block = latest.get("block") or ""
        utc = latest.get("utc") or ""
        short_c = _short_hex(contract, 8, 6)
        short_t = _short_hex(tx, 8, 6)
        show_buttons = os.environ.get("TELEGRAM_BUTTONS", "1").strip().lower() in ("1", "true", "yes")
        # Base header + deployer
        text = (
            "<b>New contract deployed on Zora.co</b>\n\n"
            f"👤 <b>Deployer</b>\n<code>{(deployer or 'default')}</code>\n\n"
        )
        # Only include the long link sections if buttons are disabled
        if not show_buttons:
            text += (
                f"📄 <b>Contract</b>\n<a href=\"https://basescan.org/address/{contract}\">{short_c}</a>\n\n"
                f"🔗 <b>Tx</b>\n<a href=\"https://basescan.org/tx/{tx}\">{short_t}</a>\n\n"
            )
        # Always include block and UTC; add Zora Project section only when not using buttons
        text += f"⛓ <b>Block</b>\n<code>{block}</code>\n\n"
        if not show_buttons:
            text += (
                f"🌐 <b>Zora Project</b>\n<a href=\"https://zora.co/coin/base:{contract}\">zora.co/coin/base:{short_c}</a>\n\n"
            )
        text += f"🕰 <b>UTC</b>\n<code>{utc}</code>"

        markup: Optional[Dict[str, Any]] = None
        if show_buttons:
            markup = {
                "inline_keyboard": [
                    [
                        {"text": "Address", "url": f"https://basescan.org/address/{contract}"},
                        {"text": "Tx", "url": f"https://basescan.org/tx/{tx}"},
                    ],
                    [
                        {"text": "Zora Project", "url": f"https://zora.co/coin/base:{contract}"}
                    ],
                ]
            }
        _telegram_send(text, reply_markup=markup)

    def scanner_loop():
        # Initial slight delay so app can start before first scan logs
        time.sleep(1.0)
        while not stop_event.is_set():
            started = time.time()
            started_utc = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(started))
            latest = None
            err: Optional[str] = None
            try:
                api_key = os.environ.get("ETHERSCAN_API_KEY") or "WNX3XI8JS1WEC7WGMU8S3DS1UMYD1ZG4FZ"
                # Bootstrap: on first run, prefill last N deployments
                first_run = int(state.get("runs", 0)) == 0 and not state.get("history")
                if first_run and bootstrap_count > 0:
                    from app.scan import scan_recent_created_contracts

                    recent = scan_recent_created_contracts(
                        api_key=api_key,
                        deployer=deployer,
                        chain_id=chain_id,
                        max_pages=bootstrap_pages,
                        limit=bootstrap_count,
                    )
                    if recent:
                        latest = recent[0]
                        print(
                            f"[bootstrap {started_utc}] Loaded {len(recent)} recent deployments; latest {latest['contract']}"
                        )
                        with lock:
                            # dedupe + cap
                            seen = set()
                            deduped = []
                            for item in recent:
                                txh = item.get("tx")
                                if not txh or txh in seen:
                                    continue
                                seen.add(txh)
                                deduped.append(item)
                                if len(deduped) >= history_max:
                                    break
                            state["history"] = deduped
                            state["latest"] = latest
                            state["last_run_utc"] = started_utc
                            state["last_error"] = None
                            state["runs"] = int(state.get("runs", 0)) + 1
                    else:
                        print(f"[bootstrap {started_utc}] No recent deployments found for bootstrap.")
                else:
                    # Regular incremental scan: just fetch the latest and insert when new
                    latest = scan_latest_created_contract(
                        api_key=api_key,
                        deployer=deployer,
                        chain_id=chain_id,
                    )
                if latest:
                    print(
                        f"[scan {started_utc}] Contract {latest['contract']} | Block {latest['block']} | Tx {latest['tx']}"
                    )
                else:
                    print(f"[scan {started_utc}] No recent contract creation found.")
            except ScanError as e:
                err = str(e)
                print(f"[scan {started_utc}] ERROR: {err}")

            notify_latest: Optional[Dict[str, Any]] = None
            with lock:
                prev_latest = state.get("latest") or {}
                # Update history on change (dedupe by tx hash)
                if latest and latest.get("tx") and latest.get("tx") != prev_latest.get("tx"):
                    hist = state.get("history") or []
                    # Insert newest at the beginning
                    hist.insert(0, latest)
                    # Dedupe by tx while preserving order and cap to history_max
                    seen = set()
                    deduped = []
                    for item in hist:
                        txh = item.get("tx")
                        if not txh or txh in seen:
                            continue
                        seen.add(txh)
                        deduped.append(item)
                        if len(deduped) >= history_max:
                            break
                    state["history"] = deduped
                    notify_latest = latest
                state["latest"] = latest
                state["last_run_utc"] = started_utc
                state["last_error"] = err
                state["runs"] = int(state.get("runs", 0)) + 1

            # Sleep until next interval, but allow fast shutdown via event
            if notify_latest:
                _telegram_send_new(notify_latest)
            stop_event.wait(interval_seconds)

    # Start background thread
    t = threading.Thread(target=scanner_loop, name="scanner", daemon=True)
    t.start()
    # Print a startup message immediately (compatible with Flask 2.x/3.x)
    print(
        f"Scanner started. Interval={interval_seconds}s, Chain={chain_id}, Deployer={deployer or 'default'}"
    )
    # Optional startup ping to Telegram
    tg_token_present = bool(
        _get_env_first("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN", "BOT_TOKEN", "TG_BOT_TOKEN")
    )
    tg_chat_present = bool(
        _get_env_first("TELEGRAM_CHAT_ID", "TELEGRAM_CHANNEL_ID", "TG_CHAT_ID")
    )
    print(
        f"Telegram configured: token={'Y' if tg_token_present else 'N'}, chat={'Y' if tg_chat_present else 'N'}"
    )
    if os.environ.get("TELEGRAM_STARTUP_PING", "0").strip().lower() in ("1", "true", "yes"):
        _telegram_send(
            (
                "✅ Contract scanner started\n"
                f"Chain: {chain_id}\n"
                f"Deployer: <code>{(deployer or 'default')}</code>\n"
                f"Interval: {interval_seconds}s"
            )
        )

    # Add no-cache headers so clients always see fresh JSON and HTML
    @app.after_request
    def _no_cache(resp):  # type: ignore[override]
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    @app.route("/")
    def index():  # type: ignore[override]
        with lock:
            view = dict(state)  # shallow copy for template
        view.update(
            {
                "interval_seconds": interval_seconds,
                "chain_id": chain_id,
                "deployer": deployer or "0x048ef1062cbb39B338Ac2685dA72adf104b4cEF5",
                "history_max": history_max,
            }
        )
        return render_template("index.html", **view)

    @app.route("/api/latest")
    def api_latest():  # type: ignore[override]
        with lock:
            return jsonify(state)

    @app.route("/api/test_telegram")
    def api_test_telegram():  # type: ignore[override]
        secret_env = os.environ.get("TELEGRAM_TEST_SECRET")
        if secret_env:
            if request.args.get("secret") != secret_env:
                return abort(403)

        # Build message once
        msg = (
            "✅ Telegram test from Contract Scanner\n"
            f"Chain: {chain_id}\n"
            f"Deployer: <code>{(deployer or 'default')}</code>\n"
            "This is a one-off test message."
        )

        # Normal send (supports optional token/chat_id overrides via query)
        if request.args.get("debug") != "1":
            override_token = request.args.get("token")
            override_chat = request.args.get("chat_id")
            ok = _telegram_send(msg, token=override_token, chat_id_override=override_chat)
            return jsonify({"ok": bool(ok)})

        # Debug mode: return HTTP status and body from Telegram
        token = request.args.get("token") or _get_env_first(
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_TOKEN",
            "BOT_TOKEN",
            "TG_BOT_TOKEN",
        )
        chat_id = request.args.get("chat_id") or _get_env_first(
            "TELEGRAM_CHAT_ID",
            "TELEGRAM_CHANNEL_ID",
            "TG_CHAT_ID",
        )
        token_present = bool(token)
        chat_present = bool(chat_id)
        if not token_present or not chat_present:
            return jsonify({"ok": False, "configured": False, "token_present": token_present, "chat_id_present": chat_present})
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        thread_id = os.environ.get("TELEGRAM_THREAD_ID")
        if thread_id:
            try:
                payload["message_thread_id"] = int(thread_id)
            except ValueError:
                pass
        silent = os.environ.get("TELEGRAM_SILENT", "0").strip().lower() in ("1", "true", "yes")
        if silent:
            payload["disable_notification"] = True
        timeout = int(os.environ.get("TELEGRAM_TIMEOUT", "10"))
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            body = r.text[:500]
            return jsonify({"ok": bool(r.ok), "status": r.status_code, "body": body})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/api/debug_env_telegram")
    def api_debug_env_telegram():  # type: ignore[override]
        secret_env = os.environ.get("TELEGRAM_TEST_SECRET")
        if secret_env:
            if request.args.get("secret") != secret_env:
                return abort(403)
        token_names = [
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_TOKEN",
            "BOT_TOKEN",
            "TG_BOT_TOKEN",
        ]
        chat_names = [
            "TELEGRAM_CHAT_ID",
            "TELEGRAM_CHANNEL_ID",
            "TG_CHAT_ID",
        ]
        present_tokens = [n for n in token_names if os.environ.get(n)]
        present_chats = [n for n in chat_names if os.environ.get(n)]
        # lengths only (no values)
        token_lengths = {n: len(os.environ.get(n) or "") for n in present_tokens}
        chat_lengths = {n: len(os.environ.get(n) or "") for n in present_chats}
        return jsonify(
            {
                "present_token_vars": present_tokens,
                "present_chat_vars": present_chats,
                "token_lengths": token_lengths,
                "chat_lengths": chat_lengths,
            }
        )

    @app.route("/api/debug_env_keys")
    def api_debug_env_keys():  # type: ignore[override]
        secret_env = os.environ.get("TELEGRAM_TEST_SECRET")
        if secret_env:
            if request.args.get("secret") != secret_env:
                return abort(403)
        # Return only env variable names (no values)
        keys = sorted(list(os.environ.keys()))
        # Filter common sensitive provider keys out of the list if desired (names only are usually safe)
        return jsonify({"keys": keys[:500], "count": len(keys)})

    @app.route("/healthz")
    def healthz():  # type: ignore[override]
        return "ok"

    return app


if __name__ == "__main__":
    # Running directly: useful for local dev
    app = create_app()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
