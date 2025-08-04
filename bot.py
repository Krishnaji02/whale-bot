import os
import time
import threading
from decimal import Decimal, getcontext
from flask import Flask, request
from web3 import Web3
from eth_utils import to_checksum_address
import requests

# ---------- Configuration & Helpers ----------
getcontext().prec = 28

def get_env(key: str, required=True):
    v = os.getenv(key)
    if required and not v:
        raise RuntimeError(f"Missing environment variable: {key}")
    return v.strip() if isinstance(v, str) else v

def parse_decimal_env(key, default):
    raw = os.getenv(key, default)
    if isinstance(raw, str):
        cleaned = raw.replace("$", "").replace(",", "").strip()
    else:
        cleaned = str(raw)
    try:
        return Decimal(cleaned)
    except Exception:
        print(f"Warning: invalid {key}='{raw}', falling back to {default}")
        return Decimal(default)

def parse_int_env(key, default):
    raw = os.getenv(key, default)
    if isinstance(raw, str):
        cleaned = "".join(ch for ch in raw if ch.isdigit())
    else:
        cleaned = str(raw)
    if cleaned == "":
        print(f"Warning: invalid {key}='{raw}', falling back to {default}")
        return int(default)
    return int(cleaned)

# Core environment variables
RPC_WS = get_env("RPC_WS")
RPC_HTTP = os.getenv("RPC_HTTP", "")
TARGET_WALLETS = [w.lower() for w in get_env("TARGET_WALLETS").split(",") if w.strip()]
UNISWAP_V2 = to_checksum_address(get_env("UNISWAP_V2"))
WETH = to_checksum_address(get_env("WETH"))
MY_ADDRESS = to_checksum_address(get_env("MY_ADDRESS"))
MY_PRIVATE_KEY = get_env("MY_PRIVATE_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

# Parsed numeric settings
BUY_USD = parse_decimal_env("BUY_USD", "10")           # dollars per mirrored buy
SLIPPAGE_BPS = parse_int_env("SLIPPAGE_BPS", "100")     # 100 = 1%
GAS_MULTIPLIER = parse_decimal_env("GAS_MULTIPLIER", "1.0")  # multiplier on whale gas price

# Build Web3 with websocket preferred, fallback to HTTP
def build_web3():
    try:
        w3 = Web3(Web3.LegacyWebSocketProvider(RPC_WS))
        if w3.is_connected():
            print("Connected via WebSocket (legacy)")
            return w3
        else:
            print("WebSocket endpoint refused connection")
    except AttributeError as e:
        print("WebSocket provider class missing or failed:", e)
    except Exception as e:
        print("WebSocket connection error:", e)

    if RPC_HTTP:
        try:
            w3 = Web3(Web3.HTTPProvider(RPC_HTTP))
            if w3.is_connected():
                print("Connected via HTTP fallback")
                return w3
            else:
                print("HTTP fallback refused connection")
        except Exception as e:
            print("HTTP fallback exception:", e)

    print("Cannot connect to RPC, retrying in 5s...")
    time.sleep(5)
    return build_web3()

w3 = build_web3()
print("Web3 connected. Latest block:", w3.eth.block_number)

# Minimal Uniswap V2 ABI pieces
UNISWAP_V2_ABI = [
    {
        "name": "getAmountsOut", "type": "function",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "path", "type": "address[]"}
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view"
    },
    {
        "name": "swapExactETHForTokens", "type": "function",
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"}
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "payable"
    },
    {
        "name": "swapExactTokensForETH", "type": "function",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"}
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "nonpayable"
    },
]

# Minimal ERC20 ABI
ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
]

# State tracking
mirror_state = {}  # (whale, token) -> {"last_whale_action": str, "we_mirrored": bool}
seen_actions = set()

# Telegram alert
def telegram_alert(token, chat_id, text):
    if not token or not chat_id:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
            "chat_id": chat_id,
            "text": text
        }, timeout=5)
    except Exception as e:
        print("Telegram error", e)

# Price fetching from CoinGecko
def get_eth_price_usd() -> Decimal:
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ethereum", "vs_currencies": "usd"},
            timeout=5,
        )
        data = resp.json()
        return Decimal(str(data["ethereum"]["usd"]))
    except Exception as e:
        print("CoinGecko fetch failed", e)
        return Decimal("3700")

def eth_for_usd(usd_amount: Decimal) -> int:
    price = get_eth_price_usd()
    eth_amount = usd_amount / price
    return int(eth_amount * Decimal(10**18))  # wei

# Router contract instance
router_v2 = w3.eth.contract(address=UNISWAP_V2, abi=UNISWAP_V2_ABI)

# Approval helper
def ensure_approval(token_addr):
    token = w3.eth.contract(address=to_checksum_address(token_addr), abi=ERC20_ABI)
    allowance = token.functions.allowance(MY_ADDRESS, UNISWAP_V2).call()
    if allowance > 0:
        return
    tx = token.functions.approve(UNISWAP_V2, 2**256 - 1).build_transaction({
        "from": MY_ADDRESS,
        "gas": 100000,
        "gasPrice": w3.eth.gas_price,
        "nonce": w3.eth.get_transaction_count(MY_ADDRESS),
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=MY_PRIVATE_KEY)
    h = w3.eth.send_raw_transaction(signed.rawTransaction)
    print(f"Approval tx sent for {token_addr}: {h.hex()}")

# Mirror BUY (ETH -> token)
def mirror_buy(token_address, whale_gas_price_wei, whale_short):
    token_address = to_checksum_address(token_address)
    amount_in_wei = eth_for_usd(BUY_USD)
    path = [WETH, token_address]
    try:
        amounts = router_v2.functions.getAmountsOut(amount_in_wei, path).call()
    except Exception as e:
        print("getAmountsOut failed for buy", e)
        return
    expected_out = amounts[-1]
    min_out = expected_out * (10000 - SLIPPAGE_BPS) // 10000
    gas_price = int(Decimal(whale_gas_price_wei) * GAS_MULTIPLIER)
    deadline = int(time.time()) + 30
    nonce = w3.eth.get_transaction_count(MY_ADDRESS)
    tx = router_v2.functions.swapExactETHForTokens(
        min_out,
        path,
        MY_ADDRESS,
        deadline,
    ).build_transaction({
        "from": MY_ADDRESS,
        "value": amount_in_wei,
        "gas": 400000,
        "gasPrice": gas_price,
        "nonce": nonce,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=MY_PRIVATE_KEY)
    try:
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"Mirrored BUY {token_address} whale {whale_short}, tx {tx_hash.hex()}")
        telegram_alert(TG_BOT_TOKEN, TG_CHAT_ID, f"Mirrored BUY {token_address} (whale {whale_short}) tx {tx_hash.hex()}")
    except Exception as e:
        print("Buy send failed", e)

# Mirror SELL (token -> ETH)
def mirror_sell(token_address, whale_gas_price_wei, whale_short):
    token_address = to_checksum_address(token_address)
    ensure_approval(token_address)
    token = w3.eth.contract(address=token_address, abi=ERC20_ABI)
    balance = token.functions.balanceOf(MY_ADDRESS).call()
    if balance == 0:
        print(f"No balance to sell for {token_address}")
        return
    path = [token_address, WETH]
    try:
        amounts = router_v2.functions.getAmountsOut(balance, path).call()
    except Exception as e:
        print("getAmountsOut failed for sell", e)
        return
    expected_out = amounts[-1]
    min_out = expected_out * (10000 - SLIPPAGE_BPS) // 10000
    gas_price = int(Decimal(whale_gas_price_wei) * GAS_MULTIPLIER)
    deadline = int(time.time()) + 30
    nonce = w3.eth.get_transaction_count(MY_ADDRESS)
    tx = router_v2.functions.swapExactTokensForETH(
        balance,
        min_out,
        path,
        MY_ADDRESS,
        deadline,
    ).build_transaction({
        "from": MY_ADDRESS,
        "gas": 400000,
        "gasPrice": gas_price,
        "nonce": nonce,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=MY_PRIVATE_KEY)
    try:
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"Mirrored SELL {token_address} whale {whale_short}, tx {tx_hash.hex()}")
        telegram_alert(TG_BOT_TOKEN, TG_CHAT_ID, f"Mirrored SELL {token_address} (whale {whale_short}) tx {tx_hash.hex()}")
    except Exception as e:
        print("Sell send failed", e)

# Whale detection & loop
SIG_SWAP_EXACT_ETH_FOR_TOKENS = "0x7ff36ab5"
SIG_SWAP_EXACT_TOKENS_FOR_ETH = "0x18cbafe5"

def process_block():
    block = w3.eth.get_block("latest", full_transactions=True)
    for tx in block["transactions"]:
        if not tx.get("from") or not tx.get("to"):
            continue
        frm = tx["from"].lower()
        if frm not in TARGET_WALLETS:
            continue
        input_data = tx.get("input", "") or ""
        if len(input_data) < 10:
            continue
        method_id = input_data[:10]
        whale_short = frm[:10]
        token_address = None
        action = None

        if method_id == SIG_SWAP_EXACT_ETH_FOR_TOKENS:
            try:
                raw = bytes.fromhex(input_data[2:])
                decoded = w3.codec.decode_abi(
                    ["uint256", "address[]", "address", "uint256"],
                    raw[4:]
                )
                path = decoded[1]
                if len(path) >= 2:
                    token_address = path[-1]
                action = "BUY"
            except Exception as e:
                print("Decode buy failed", e)
                continue
        elif method_id == SIG_SWAP_EXACT_TOKENS_FOR_ETH:
            try:
                raw = bytes.fromhex(input_data[2:])
                decoded = w3.codec.decode_abi(
                    ["uint256", "uint256", "address[]", "address", "uint256"],
                    raw[4:]
                )
                path = decoded[2]
                if len(path) >= 2:
                    token_address = path[0]
                action = "SELL"
            except Exception as e:
                print("Decode sell failed", e)
                continue
        else:
            continue

        if not token_address or not action:
            continue

        key = (frm, token_address.lower(), action)
        if key in seen_actions:
            continue
        seen_actions.add(key)

        state_key = (frm, token_address.lower())
        prev = mirror_state.get(state_key, {})
        last_whale_action = prev.get("last_whale_action")
        if last_whale_action == action and prev.get("we_mirrored"):
            print(f"Skipping duplicate mirror {action} for {token_address} from {frm}")
            continue

        if action == "BUY":
            mirror_buy(token_address, tx.get("gasPrice", w3.eth.gas_price), whale_short)
        elif action == "SELL":
            mirror_sell(token_address, tx.get("gasPrice", w3.eth.gas_price), whale_short)

        mirror_state[state_key] = {"last_whale_action": action, "we_mirrored": True}

def main_loop():
    print("Watcher started")
    while True:
        try:
            process_block()
        except Exception as e:
            print("Loop error", e)
        time.sleep(1)

# Flask for keepalive and manual sell
keepalive = Flask("keepalive")

@keepalive.route("/")
def health():
    return "OK", 200

@keepalive.route("/manual_sell")
def manual_sell():
    token = request.args.get("token")
    if not token:
        return "missing token", 400
    gas_price = w3.eth.gas_price
    mirror_sell(token, gas_price, "manual")
    return f"Triggered manual sell for {token}", 200

# start watcher thread
threading.Thread(target=main_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    keepalive.run(host="0.0.0.0", port=port)
