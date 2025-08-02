import time
from web3 import Web3
from telegram import Bot

def load_env(path="config.env"):
    env = {}
    with open(path) as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                env[k] = v
    return env

cfg = load_env()

RPC_WS = cfg["RPC_WS"]
TARGET_WALLETS = [w.lower() for w in cfg["TARGET_WALLETS"].split(",")]
UNISWAP_V2 = Web3.to_checksum_address(cfg["UNISWAP_V2"])
UNISWAP_V3 = Web3.to_checksum_address(cfg["UNISWAP_V3"])
UNISWAP_V3_ROUTER2 = Web3.to_checksum_address(cfg["UNISWAP_V3_ROUTER2"])
TG_BOT_TOKEN = cfg["TG_BOT_TOKEN"]
TG_CHAT_ID = cfg["TG_CHAT_ID"]

w3 = Web3(Web3.WebsocketProvider(RPC_WS))
bot = Bot(token=TG_BOT_TOKEN)
seen = set()

SIG_SWAP_EXACT_ETH_FOR_TOKENS = "0x7ff36ab5"
SIG_SWAP_EXACT_TOKENS_FOR_ETH = "0x18cbafe5"

def send_telegram(text):
    try:
        bot.send_message(chat_id=TG_CHAT_ID, text=text)
        print("[Telegram]", text)
    except Exception as e:
        print("Telegram error:", e)

def is_watched_router(addr):
    if not addr:
        return False
    a = addr.lower()
    return a in {UNISWAP_V2.lower(), UNISWAP_V3.lower(), UNISWAP_V3_ROUTER2.lower()}

def process_latest_block():
    block = w3.eth.get_block("latest", full_transactions=True)
    for tx in block["transactions"]:
        if not tx.get("from") or not tx.get("to"):
            continue
        if tx["from"].lower() not in TARGET_WALLETS:
            continue
        if not is_watched_router(tx["to"]):
            continue
        method_id = tx["input"][:10]
        action = None
        if method_id == SIG_SWAP_EXACT_ETH_FOR_TOKENS:
            action = "BUY"
        elif method_id == SIG_SWAP_EXACT_TOKENS_FOR_ETH:
            action = "SELL"
        else:
            continue
        key = f"{tx['from'].lower()}:{action}:{tx.hash.hex()}"
        if key in seen:
            continue
        seen.add(key)
        short = tx["from"][:10]
        send_telegram(f"Whale {short} did {action} via {tx['to'][:10]} tx {tx.hash.hex()}")

def main_loop():
    print("Starting watcher...")
    while True:
        try:
            process_latest_block()
        except Exception as e:
            print("Error:", e)
        time.sleep(1)

if __name__ == "__main__":
    main_loop()
