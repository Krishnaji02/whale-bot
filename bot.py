import os
import time
import threading
import sys
from flask import Flask
from web3 import Web3

# --- tiny HTTP server so Render sees an open port ---
app = Flask("keepalive")

@app.route("/")
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()
# ---------------------------------------------------

def get_env(name, required=True):
    v = os.getenv(name)
    if required and (v is None or v == ""):
        print(f"ERROR: missing environment variable {name}")
        sys.exit(1)
    return v

# Load config
RPC_WS = get_env("RPC_WS")
TARGET_WALLETS_RAW = get_env("TARGET_WALLETS")
UNISWAP_V2 = get_env("UNISWAP_V2")
UNISWAP_V3 = get_env("UNISWAP_V3")
UNISWAP_V3_ROUTER2 = get_env("UNISWAP_V3_ROUTER2")
WETH = get_env("WETH")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

# --- Provider resolution: prefer websocket, fallback to HTTP ---
provider = None
# Try modern WebsocketProvider import
try:
    from web3.providers.websocket import WebsocketProvider
    provider = WebsocketProvider(RPC_WS)
except Exception:
    # Fallback to LegacyWebSocketProvider if available
    try:
        from web3.providers.websocket import LegacyWebSocketProvider
        provider = LegacyWebSocketProvider(RPC_WS)
    except Exception:
        # Last fallback to HTTP
        provider = Web3.HTTPProvider(RPC_WS)

w3 = Web3(provider)

if not w3.is_connected():
    print("ERROR: cannot connect to RPC:", RPC_WS)
    sys.exit(1)

# checksum helper (handles different API names)
def checksum(addr: str):
    if hasattr(Web3, "to_checksum_address"):
        return Web3.to_checksum_address(addr)
    elif hasattr(Web3, "toChecksumAddress"):
        return Web3.toChecksumAddress(addr)
    return addr

TARGET_WALLETS = [checksum(a.strip()).lower() for a in TARGET_WALLETS_RAW.split(",") if a.strip()]
UNISWAP_V2 = checksum(UNISWAP_V2).lower()
UNISWAP_V3 = checksum(UNISWAP_V3).lower()
UNISWAP_V3_ROUTER2 = checksum(UNISWAP_V3_ROUTER2).lower()
WETH = checksum(WETH).lower()

print("Starting watcher. Targets:", TARGET_WALLETS)
print("Routers:", UNISWAP_V2, UNISWAP_V3, UNISWAP_V3_ROUTER2)
print("Connected to node. Latest block:", w3.eth.block_number)

# Simple swap detection logic (you can expand later)
SIG_SWAP_EXACT_ETH_FOR_TOKENS = "0x7ff36ab5"
SIG_SWAP_EXACT_TOKENS_FOR_ETH = "0x18cbafe5"
seen = set()

def telegram_alert(token, chat_id, text):
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print("Telegram send error:", e)

def process_block():
    block = w3.eth.get_block("latest", full_transactions=True)
    for tx in block["transactions"]:
        if not tx.get("from") or not tx.get("to"):
            continue
        frm = tx["from"].lower()
        to = tx["to"].lower()
        if frm not in TARGET_WALLETS:
            continue
        if to not in {UNISWAP_V2, UNISWAP_V3, UNISWAP_V3_ROUTER2}:
            continue
        method_id = tx["input"][:10]
        action = None
        if method_id == SIG_SWAP_EXACT_ETH_FOR_TOKENS:
            action = "BUY"
        elif method_id == SIG_SWAP_EXACT_TOKENS_FOR_ETH:
            action = "SELL"
        else:
            continue
        key = f"{frm}:{action}:{tx.hash.hex()}"
        if key in seen:
            continue
        seen.add(key)
        short = frm[:10]
        msg = f"Whale {short} did {action} via {to[:10]} tx {tx.hash.hex()}"
        print(msg)
        if TG_BOT_TOKEN and TG_CHAT_ID:
            telegram_alert(TG_BOT_TOKEN, TG_CHAT_ID, msg)

def main_loop():
    while True:
        try:
            process_block()
        except Exception as e:
            print("Loop error:", e)
        time.sleep(1)

if __name__ == "__main__":
    main_loop()
