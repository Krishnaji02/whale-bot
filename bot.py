import os
import threading
import time
import logging
from flask import Flask
from web3 import Web3

# ------------ tiny webserver for Render health check -------------
app = Flask("keepalive")

@app.route("/")
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()
# ---------------------------------------------------------------

# basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("whale-mirror-bot")

# helpers to load environment variables
def get_env(key: str, default=None, required=True):
    val = os.environ.get(key, default)
    if required and (val is None or val == ""):
        log.error(f"Missing required environment variable: {key}")
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val

# Telegram alert helper (optional)
def telegram_alert(token: str, chat_id: str, text: str):
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        log.warning(f"Failed to send Telegram alert: {e}")

# load config from env
RPC_WS = get_env("RPC_WS")
TARGET_WALLETS_RAW = get_env("TARGET_WALLETS")  # comma separated
UNISWAP_V2 = get_env("UNISWAP_V2")
UNISWAP_V3 = get_env("UNISWAP_V3")
UNISWAP_V3_ROUTER2 = get_env("UNISWAP_V3_ROUTER2")
WETH = get_env("WETH")

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

# connect to provider (try websocket if wss:// else HTTP)
if RPC_WS.startswith("ws"):
    # some versions use LegacyWebSocketProvider fallback
    try:
        provider = Web3.WebsocketProvider(RPC_WS)
    except AttributeError:
        from web3 import Web3 as _Web3_module
        provider = getattr(Web3, "LegacyWebSocketProvider")(RPC_WS)
else:
    provider = Web3.HTTPProvider(RPC_WS)

w3 = Web3(provider)

# checksum utility (support different Web3 versions)
def checksum(addr: str):
    try:
        return Web3.toChecksumAddress(addr)
    except AttributeError:
        # older versions might expose as toChecksumAddress
        return getattr(w3, "toChecksumAddress")(addr)

# normalize addresses
try:
    TARGET_WALLETS = [checksum(a.strip()) for a in TARGET_WALLETS_RAW.split(",") if a.strip()]
    UNISWAP_V2 = checksum(UNISWAP_V2)
    UNISWAP_V3 = checksum(UNISWAP_V3)
    UNISWAP_V3_ROUTER2 = checksum(UNISWAP_V3_ROUTER2)
    WETH = checksum(WETH)
except Exception as e:
    log.error(f"Address normalization failed: {e}")
    raise

def main_loop():
    if not w3.is_connected():
        log.error("Web3 provider not connected.")
        return

    log.info("Connected to Web3. Monitoring wallets: " + ", ".join(TARGET_WALLETS))
    last_balances = {}
    # initial snapshot
    for wallet in TARGET_WALLETS:
        try:
            bal = w3.eth.get_balance(wallet)
            last_balances[wallet] = bal
        except Exception:
            last_balances[wallet] = None

    # main polling loop (placeholder for real sniper logic)
    while True:
        for wallet in TARGET_WALLETS:
            try:
                bal = w3.eth.get_balance(wallet)
                prev = last_balances.get(wallet)
                if prev is not None and bal != prev:
                    diff = bal - prev
                    msg = f"Wallet {wallet} balance changed: {prev} -> {bal} (Δ {diff})"
                    log.info(msg)
                    if TG_BOT_TOKEN and TG_CHAT_ID:
                        telegram_alert(TG_BOT_TOKEN, TG_CHAT_ID, msg)
                last_balances[wallet] = bal
            except Exception as e:
                log.warning(f"Error fetching balance for {wallet}: {e}")
        # TODO: add wholesale sniffing of their swaps / mirror logic here
        time.sleep(10)  # adjust frequency as needed

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        log.info("Exiting on user interrupt.")
    except Exception as e:
        log.exception(f"Unhandled exception: {e}")
