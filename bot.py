import os
import sys
from web3 import Web3

def get_env(name, required=True):
    v = os.getenv(name)
    if required and not v:
        print(f"ERROR: missing environment variable {name}")
        sys.exit(1)
    return v

# Read core config from environment
RPC_WS = get_env("RPC_WS")  # e.g. wss://eth-mainnet.g.alchemy.com/v2/your_key
MY_ADDRESS = Web3.toChecksumAddress(get_env("MY_ADDRESS"))
TARGET_WALLETS = get_env("TARGET_WALLETS")  # comma-separated list
UNISWAP_V2 = Web3.toChecksumAddress(get_env("UNISWAP_V2"))
UNISWAP_V3 = Web3.toChecksumAddress(get_env("UNISWAP_V3"))
UNISWAP_V3_ROUTER2 = Web3.toChecksumAddress(get_env("UNISWAP_V3_ROUTER2"))
WETH = Web3.toChecksumAddress(get_env("WETH"))

# Connect to Web3 using the legacy websocket provider
w3 = Web3(Web3.LegacyWebsocketProvider(RPC_WS))

if not w3.is_connected():
    print("ERROR: Could not connect to Ethereum node.")
    sys.exit(1)

print("Connected to node. Latest block:", w3.eth.block_number)

# Placeholder for future whale-mirroring logic
