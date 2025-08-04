import os
from web3 import Web3
from flask import Flask

def get_env(name, required=True):
    val = os.environ.get(name)
    if required and not val:
        raise RuntimeError(f"Missing env var: {name}")
    return val

# Load & normalize addresses
RPC_WS = get_env("RPC_WS")  # e.g. wss://eth-mainnet.g.alchemy.com/v2/your_full_key
MY_PRIVATE_KEY = get_env("MY_PRIVATE_KEY")
MY_ADDRESS = Web3.toChecksumAddress(get_env("MY_ADDRESS"))
TARGET_WALLETS = [w.strip() for w in get_env("TARGET_WALLETS", required=False).split(",") if w.strip()]
UNISWAP_V2 = Web3.toChecksumAddress(get_env("UNISWAP_V2"))
UNISWAP_V3 = Web3.toChecksumAddress(get_env("UNISWAP_V3"))
WETH = Web3.toChecksumAddress(get_env("WETH"))
TG_BOT_TOKEN = get_env("TG_BOT_TOKEN")
TG_CHAT_ID = get_env("TG_CHAT_ID")

# Web3 connection with fallback name
try:
    provider = Web3.WebsocketProvider(RPC_WS)
except AttributeError:
    provider = Web3.LegacyWebSocketProvider(RPC_WS)

w3 = Web3(provider)
if not w3.is_connected():
    print("ERROR: cannot connect to RPC:", RPC_WS)
    # Depending on your logic, you might exit or retry
else:
    print("Connected to Web3")

# Flask for keepalive
app = Flask("keepalive")

@app.route("/")
def home():
    return "Bot is alive"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    # Your main bot startup logic would go here or in a background thread
    app.run(host="0.0.0.0", port=port)
