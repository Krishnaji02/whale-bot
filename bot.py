import os
from web3 import Web3
from flask import Flask

def get_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Missing environment variable: {key}")
    return val.strip()

# Load required env vars
RPC_WS = get_env("RPC_WS")              # e.g. wss://eth-mainnet.g.alchemy.com/v2/yourkey
MY_ADDRESS = Web3.to_checksum_address(get_env("MY_ADDRESS"))
PRIVATE_KEY = get_env("PRIVATE_KEY")    # your wallet private key (keep secret)
UNISWAP_V2 = Web3.to_checksum_address(get_env("UNISWAP_V2"))
WETH = Web3.to_checksum_address(get_env("WETH"))

# Initialize Web3 with fallback for provider class name differences
try:
    provider = Web3.WebsocketProvider(RPC_WS)
except AttributeError:
    provider = Web3.LegacyWebSocketProvider(RPC_WS)

w3 = Web3(provider)

if not w3.is_connected():
    print("ERROR: cannot connect to RPC:", RPC_WS)
    raise SystemExit(1)
print("Connected to Web3")

# Simple keep-alive web service
keepalive = Flask("keepalive")

@keepalive.route("/")
def health():
    return "OK", 200

# (Here you would add the wallet tracking / mirror logic using w3, UNISWAP_V2, etc.)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    keepalive.run(host="0.0.0.0", port=port)
