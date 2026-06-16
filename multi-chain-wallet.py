#!/usr/bin/env python3
"""
Wallet tool terpadu:
  1. Scan native token — 1 chain
  2. Scan native token — semua chain
  3. Scan ERC-20 token (tokens.json)
  4. Kirim max native — 1 chain
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3
from web3.exceptions import Web3Exception

import colors as c
from prices import fetch_usd_prices, format_usd, to_usd

Account.enable_unaudited_hdwallet_features()

TRANSFER_GAS_LIMIT = 21_000
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]


@dataclass
class Chain:
    id: str
    name: str
    symbol: str
    chain_id: int
    decimals: int
    rpc_url: str
    coingecko_id: str


@dataclass
class Token:
    chain_id: str
    symbol: str
    contract: str
    decimals: int
    coingecko_id: str


@dataclass
class Wallet:
    index: int
    address: str
    private_key: str


@dataclass
class BalanceResult:
    wallet: Wallet
    chain: Chain
    balance_wei: int
    error: str | None = None


@dataclass
class TokenBalanceResult:
    wallet: Wallet
    chain: Chain
    token: Token
    balance_raw: int
    error: str | None = None


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_private_keys(path: str) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        print(c.error(f"Error: file private key tidak ditemukan: {file_path}"))
        sys.exit(1)

    keys: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("0x"):
            line = "0x" + line
        keys.append(line)

    if not keys:
        print(c.error(f"Error: tidak ada private key di {file_path}"))
        sys.exit(1)
    return keys


def load_chains(chains_file: Path, silent_skip: bool = False) -> list[Chain]:
    if not chains_file.exists():
        print(c.error(f"Error: {chains_file} tidak ditemukan"))
        sys.exit(1)

    data = json.loads(chains_file.read_text(encoding="utf-8"))
    chains: list[Chain] = []
    skipped: list[str] = []

    for item in data.get("chains", []):
        if not item.get("enabled", True):
            continue
        rpc_env = item.get("rpc_env", "")
        rpc_url = os.getenv(rpc_env, "").strip() if rpc_env else ""
        if not rpc_url:
            skipped.append(f"{item.get('name', item.get('id'))} ({rpc_env} kosong)")
            continue
        chains.append(
            Chain(
                id=item["id"],
                name=item["name"],
                symbol=item["symbol"],
                chain_id=int(item["chain_id"]),
                decimals=int(item.get("decimals", 18)),
                rpc_url=rpc_url,
                coingecko_id=item.get("coingecko_id", ""),
            )
        )

    if skipped and not silent_skip:
        print(c.warn("Chain dilewati (RPC belum diisi di .env):"))
        for s in skipped:
            print(c.dim(f"  - {s}"))
        print()

    if not chains:
        print(c.error("Error: tidak ada chain aktif. Isi minimal 1 RPC_* di .env"))
        sys.exit(1)
    return chains


def load_tokens(tokens_file: Path, active_chain_ids: set[str]) -> list[Token]:
    if not tokens_file.exists():
        print(c.error(f"Error: {tokens_file} tidak ditemukan"))
        sys.exit(1)

    data = json.loads(tokens_file.read_text(encoding="utf-8"))
    tokens: list[Token] = []
    for item in data.get("tokens", []):
        if not item.get("enabled", True):
            continue
        if item["chain_id"] not in active_chain_ids:
            continue
        tokens.append(
            Token(
                chain_id=item["chain_id"],
                symbol=item["symbol"],
                contract=item["contract"],
                decimals=int(item["decimals"]),
                coingecko_id=item.get("coingecko_id", ""),
            )
        )
    return tokens


def build_wallets(private_keys: list[str]) -> list[Wallet]:
    wallets: list[Wallet] = []
    for idx, pk in enumerate(private_keys, start=1):
        account = Account.from_key(pk)
        wallets.append(Wallet(index=idx, address=account.address, private_key=pk))
    return wallets


def show_usd_enabled() -> bool:
    return os.getenv("SHOW_USD", "true").strip().lower() not in ("0", "false", "no")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_decimal(raw: int, decimals: int) -> Decimal:
    return Decimal(raw) / Decimal(10**decimals)


def format_amount(raw: int, symbol: str, decimals: int) -> str:
    return f"{to_decimal(raw, decimals):.8f} {symbol}"


def get_w3(rpc_url: str, timeout: int = 30) -> Web3 | None:
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))
        if w3.is_connected():
            return w3
    except Web3Exception:
        pass
    return None


def get_w3_required(rpc_url: str) -> Web3:
    w3 = get_w3(rpc_url, timeout=60)
    if w3 is None:
        print(c.error("Error: tidak bisa terhubung ke RPC"))
        sys.exit(1)
    return w3


def fetch_prices(coin_ids: list[str], show_usd: bool) -> tuple[dict[str, Decimal], bool]:
    if not show_usd:
        return {}, False
    print(c.info("Mengambil harga USD (CoinGecko)..."))
    prices = fetch_usd_prices(coin_ids)
    if not prices:
        print(c.warn("Harga USD tidak tersedia — tampil tanpa konversi $"))
        return {}, False
    return prices, True


def usd_suffix(raw: int, decimals: int, coingecko_id: str, prices: dict[str, Decimal]) -> str:
    if not coingecko_id or coingecko_id not in prices:
        return ""
    value = to_usd(raw, decimals, prices[coingecko_id])
    return f"  {c.usd(f'({format_usd(value)})')}"


def prompt_yes_no(message: str) -> bool:
    while True:
        answer = input(f"{message} (y/n): ").strip().lower()
        if answer in ("y", "yes", "ya"):
            return True
        if answer in ("n", "no", "tidak"):
            return False
        print(c.warn("Jawab y/ya atau n/tidak."))


def pick_chain(chains: list[Chain], prompt: str) -> Chain:
    print(c.title(f"\n{prompt}"))
    for i, chain in enumerate(chains, start=1):
        print(f"  {c.label(str(i))}. {chain.name} ({chain.symbol})")
    while True:
        choice = input("\nPilih nomor chain: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(chains):
            return chains[int(choice) - 1]
        print(c.warn("Nomor tidak valid."))


# ---------------------------------------------------------------------------
# Native scan
# ---------------------------------------------------------------------------

def fetch_native_balance(wallet: Wallet, chain: Chain) -> BalanceResult:
    w3 = get_w3(chain.rpc_url)
    if w3 is None:
        return BalanceResult(wallet, chain, 0, error="RPC tidak terhubung")
    try:
        balance = w3.eth.get_balance(wallet.address)
        return BalanceResult(wallet, chain, balance)
    except Web3Exception as exc:
        return BalanceResult(wallet, chain, 0, error=str(exc))


def scan_native(wallets: list[Wallet], chains: list[Chain], workers: int = 8) -> list[BalanceResult]:
    tasks = [(w, ch) for w in wallets for ch in chains]
    results: list[BalanceResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch_native_balance, w, ch) for w, ch in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda r: (r.wallet.index, r.chain.name))
    return results


def print_native_report(
    wallets: list[Wallet],
    chains: list[Chain],
    results: list[BalanceResult],
    prices: dict[str, Decimal],
    show_usd: bool,
    title: str = "SALDO NATIVE TOKEN",
) -> None:
    lookup = {(r.wallet.address, r.chain.id): r for r in results}
    print("\n" + c.header("=" * 90))
    print(c.title(title))
    print(c.header("=" * 90))

    grand_total_usd = Decimal(0)

    for wallet in wallets:
        print(f"\n{c.label(f'[{wallet.index:>3}]')} {c.address(wallet.address)}")
        has_balance = False
        wallet_usd = Decimal(0)

        for chain in chains:
            result = lookup[(wallet.address, chain.id)]
            if result.error:
                print(f"      {c.chain_name(f'{chain.name:<22}')} {c.error(f'ERROR: {result.error}')}")
                continue
            if result.balance_wei > 0:
                has_balance = True
                amount = format_amount(result.balance_wei, chain.symbol, chain.decimals)
                suffix = ""
                if show_usd and chain.coingecko_id in prices:
                    usd_val = to_usd(result.balance_wei, chain.decimals, prices[chain.coingecko_id])
                    wallet_usd += usd_val
                    suffix = f"  {c.usd(f'({format_usd(usd_val)})')}"
                print(f"      {c.chain_name(f'{chain.name:<22}')} {c.balance(amount)}{suffix}")

        if not has_balance:
            print(c.dim("      (tidak ada saldo native)"))
        elif show_usd and wallet_usd > 0:
            print(f"      {c.dim('Subtotal wallet:')} {c.usd(format_usd(wallet_usd))}")

    print("\n" + c.header("-" * 90))
    print(c.title("TOTAL PER CHAIN"))
    print(c.header("-" * 90))

    for chain in chains:
        chain_results = [r for r in results if r.chain.id == chain.id and not r.error]
        total_wei = sum(r.balance_wei for r in chain_results)
        funded = sum(1 for r in chain_results if r.balance_wei > 0)
        if total_wei > 0:
            amount = format_amount(total_wei, chain.symbol, chain.decimals)
            suffix = ""
            if show_usd and chain.coingecko_id in prices:
                chain_usd = to_usd(total_wei, chain.decimals, prices[chain.coingecko_id])
                grand_total_usd += chain_usd
                suffix = f"  {c.usd(f'({format_usd(chain_usd)})')}"
            print(f"  {c.chain_name(f'{chain.name:<22}')} {c.total(amount)}  {c.dim(f'({funded} wallet)')}{suffix}")
        else:
            print(f"  {c.chain_name(f'{chain.name:<22}')} {c.zero(f'0 {chain.symbol}')}")

    if show_usd and grand_total_usd > 0:
        print("\n" + c.header("-" * 90))
        print(f"{c.title('GRAND TOTAL (USD):')} {c.usd(format_usd(grand_total_usd))}")

    errors = [r for r in results if r.error]
    if errors:
        print("\n" + c.header("-" * 90))
        print(c.error(f"RPC ERROR: {len(errors)} request gagal"))

    print(c.header("=" * 90) + "\n")


def run_native_single(wallets: list[Wallet], chains: list[Chain], show_usd: bool) -> None:
    chain = pick_chain(chains, "Pilih chain untuk scan native:")
    print(c.info(f"\nMemindai {chain.name}..."))
    results = scan_native(wallets, [chain])
    prices, show_usd = fetch_prices([chain.coingecko_id], show_usd)
    print_native_report(wallets, [chain], results, prices, show_usd, f"NATIVE — {chain.name.upper()}")


def run_native_all(wallets: list[Wallet], chains: list[Chain], show_usd: bool) -> None:
    print(c.info("Memindai semua chain..."))
    results = scan_native(wallets, chains)
    prices, show_usd = fetch_prices([ch.coingecko_id for ch in chains], show_usd)
    print_native_report(wallets, chains, results, prices, show_usd, "SALDO NATIVE — SEMUA CHAIN")


# ---------------------------------------------------------------------------
# ERC-20 scan
# ---------------------------------------------------------------------------

def fetch_token_balance(wallet: Wallet, chain: Chain, token: Token) -> TokenBalanceResult:
    w3 = get_w3(chain.rpc_url)
    if w3 is None:
        return TokenBalanceResult(wallet, chain, token, 0, error="RPC tidak terhubung")
    try:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(token.contract),
            abi=ERC20_ABI,
        )
        balance = contract.functions.balanceOf(Web3.to_checksum_address(wallet.address)).call()
        return TokenBalanceResult(wallet, chain, token, balance)
    except Web3Exception as exc:
        return TokenBalanceResult(wallet, chain, token, 0, error=str(exc))


def scan_tokens(
    wallets: list[Wallet],
    chains: list[Chain],
    tokens: list[Token],
    workers: int = 8,
) -> list[TokenBalanceResult]:
    chain_map = {ch.id: ch for ch in chains}
    tasks: list[tuple[Wallet, Chain, Token]] = []
    for token in tokens:
        chain = chain_map.get(token.chain_id)
        if chain:
            for wallet in wallets:
                tasks.append((wallet, chain, token))

    results: list[TokenBalanceResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch_token_balance, w, ch, t) for w, ch, t in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda r: (r.wallet.index, r.chain.name, r.token.symbol))
    return results


def print_token_report(
    wallets: list[Wallet],
    results: list[TokenBalanceResult],
    prices: dict[str, Decimal],
    show_usd: bool,
) -> None:
    print("\n" + c.header("=" * 90))
    print(c.title("SALDO ERC-20 TOKEN"))
    print(c.header("=" * 90))

    grand_total_usd = Decimal(0)

    for wallet in wallets:
        wallet_results = [r for r in results if r.wallet.address == wallet.address]
        funded = [r for r in wallet_results if r.balance_raw > 0 and not r.error]
        print(f"\n{c.label(f'[{wallet.index:>3}]')} {c.address(wallet.address)}")

        if not funded:
            errors = [r for r in wallet_results if r.error]
            if errors:
                for r in errors[:3]:
                    print(f"      {c.error(f'{r.chain.name} {r.token.symbol}: {r.error}')}")
            print(c.dim("      (tidak ada saldo token)"))
            continue

        wallet_usd = Decimal(0)
        for r in funded:
            amount = format_amount(r.balance_raw, r.token.symbol, r.token.decimals)
            suffix = ""
            if show_usd and r.token.coingecko_id in prices:
                usd_val = to_usd(r.balance_raw, r.token.decimals, prices[r.token.coingecko_id])
                wallet_usd += usd_val
                suffix = f"  {c.usd(f'({format_usd(usd_val)})')}"
            print(f"      {c.chain_name(f'{r.chain.name:<18}')} {c.balance(r.token.symbol + ':')} {c.balance(amount)}{suffix}")

        if show_usd and wallet_usd > 0:
            print(f"      {c.dim('Subtotal wallet:')} {c.usd(format_usd(wallet_usd))}")
            grand_total_usd += wallet_usd

    print("\n" + c.header("-" * 90))
    print(c.title("TOTAL PER TOKEN"))
    print(c.header("-" * 90))

    seen: set[tuple[str, str, str]] = set()
    for r in results:
        key = (r.chain.id, r.token.contract, r.token.symbol)
        if key in seen or r.error:
            continue
        seen.add(key)
        group = [
            x for x in results
            if x.chain.id == r.chain.id and x.token.contract == r.token.contract and not x.error
        ]
        total_raw = sum(x.balance_raw for x in group)
        funded = sum(1 for x in group if x.balance_raw > 0)
        if total_raw > 0:
            amount = format_amount(total_raw, r.token.symbol, r.token.decimals)
            suffix = ""
            if show_usd and r.token.coingecko_id in prices:
                token_usd = to_usd(total_raw, r.token.decimals, prices[r.token.coingecko_id])
                suffix = f"  {c.usd(f'({format_usd(token_usd)})')}"
            label = f"{r.chain.name} {r.token.symbol}"
            print(f"  {c.chain_name(f'{label:<28}')} {c.total(amount)}  {c.dim(f'({funded} wallet)')}{suffix}")

    if show_usd and grand_total_usd > 0:
        print("\n" + c.header("-" * 90))
        print(f"{c.title('GRAND TOTAL TOKEN (USD):')} {c.usd(format_usd(grand_total_usd))}")

    errors = [r for r in results if r.error]
    if errors:
        print("\n" + c.header("-" * 90))
        print(c.error(f"RPC ERROR: {len(errors)} request gagal"))

    print(c.header("=" * 90) + "\n")


def run_token_scan(wallets: list[Wallet], chains: list[Chain], tokens_file: Path, show_usd: bool) -> None:
    active_ids = {ch.id for ch in chains}
    tokens = load_tokens(tokens_file, active_ids)
    if not tokens:
        print(c.warn("Tidak ada token aktif. Edit tokens.json atau aktifkan RPC chain terkait."))
        return

    print(c.info(f"Memindai {len(tokens)} token di {len(chains)} chain..."))
    results = scan_tokens(wallets, chains, tokens)
    prices, show_usd = fetch_prices([t.coingecko_id for t in tokens], show_usd)
    print_token_report(wallets, results, prices, show_usd)


# ---------------------------------------------------------------------------
# Send max native
# ---------------------------------------------------------------------------

def get_gas_params(w3: Web3) -> tuple[int, int]:
    try:
        fee_history = w3.eth.fee_history(1, "latest", [50.0])
        base_fee = fee_history["baseFeePerGas"][-1]
        priority = w3.to_wei(1.5, "gwei")
        return base_fee * 2 + priority, priority
    except (Web3Exception, TypeError, IndexError, KeyError):
        gas_price = w3.eth.gas_price
        return gas_price, gas_price


def calculate_max_send(w3: Web3, balance: int) -> tuple[int, int, int, int, int]:
    max_fee, max_priority = get_gas_params(w3)
    gas_limit = TRANSFER_GAS_LIMIT
    gas_cost = gas_limit * max_fee
    return balance - gas_cost, gas_cost, max_fee, max_priority, gas_limit


def send_max_value(w3: Web3, private_key: str, destination: str, chain: Chain) -> bool:
    account = Account.from_key(private_key)
    from_addr = account.address
    to_addr = Web3.to_checksum_address(destination)
    balance = w3.eth.get_balance(from_addr)

    if balance == 0:
        print(c.dim(f"  Skip {from_addr}: saldo 0"))
        return False

    send_amount, gas_cost, max_fee, max_priority, gas_limit = calculate_max_send(w3, balance)
    if send_amount <= 0:
        print(c.warn(f"  Skip {from_addr}: saldo tidak cukup untuk gas"))
        return False

    tx = {
        "chainId": chain.chain_id,
        "from": from_addr,
        "to": to_addr,
        "value": send_amount,
        "gas": gas_limit,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": max_priority,
        "nonce": w3.eth.get_transaction_count(from_addr),
        "type": 2,
    }
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

    sym = chain.symbol
    if receipt["status"] == 1:
        print(c.success(f"  OK {from_addr}"))
        print(c.balance(f"     Kirim: {format_amount(send_amount, sym, chain.decimals)}"))
        print(c.dim(f"     Gas  : ~{format_amount(gas_cost, sym, chain.decimals)}"))
        print(c.info(f"     Tx   : {tx_hash.hex()}"))
        return True

    print(c.error(f"  GAGAL {from_addr} - tx: {tx_hash.hex()}"))
    return False


def run_send_max(wallets: list[Wallet], chains: list[Chain]) -> None:
    destination = os.getenv("DESTINATION_ADDRESS", "").strip()
    if not destination:
        print(c.warn("DESTINATION_ADDRESS belum diisi di .env"))
        return

    chain = pick_chain(chains, "Pilih chain untuk kirim max native:")
    w3 = get_w3_required(chain.rpc_url)
    dest = Web3.to_checksum_address(destination)

    print(c.info(f"\nChain   : {chain.name}"))
    print(c.info(f"Tujuan  : {c.address(dest)}"))
    print(c.info("Mode    : MAX value (saldo - gas fee)"))

    funded: list[tuple[Wallet, int]] = []
    for wallet in wallets:
        bal = w3.eth.get_balance(wallet.address)
        if bal > 0:
            funded.append((wallet, bal))

    if not funded:
        print(c.warn("Tidak ada wallet dengan saldo native di chain ini."))
        return

    if not prompt_yes_no(f"Kirim max dari {len(funded)} wallet?"):
        print(c.warn("Dibatalkan."))
        return

    print(c.title("\nPreview:"))
    for wallet, bal in funded:
        send_amount, gas_cost, _, _, _ = calculate_max_send(w3, bal)
        if send_amount > 0:
            print(
                f"  {c.label(f'[{wallet.index}]')} {c.address(wallet.address)}: "
                f"kirim {c.balance(format_amount(send_amount, chain.symbol, chain.decimals))} | "
                f"gas ~{c.dim(format_amount(gas_cost, chain.symbol, chain.decimals))}"
            )
        else:
            print(f"  {c.label(f'[{wallet.index}]')} {c.address(wallet.address)}: {c.warn('tidak cukup gas')}")

    if not prompt_yes_no("Lanjutkan transaksi?"):
        print(c.warn("Dibatalkan."))
        return

    success = 0
    for wallet, _ in funded:
        print(c.info(f"\nProses [{wallet.index}] {wallet.address}..."))
        if send_max_value(w3, wallet.private_key, dest, chain):
            success += 1
    print(f"\n{c.success('Selesai.')} Berhasil: {c.total(f'{success}/{len(funded)}')}")


# ---------------------------------------------------------------------------
# Menu & CLI
# ---------------------------------------------------------------------------

def print_menu() -> None:
    print(c.header("\n" + "=" * 50))
    print(c.title("       WALLET TOOL — MENU UTAMA"))
    print(c.header("=" * 50))
    print(f"  {c.label('1')}. Scan native token — 1 chain")
    print(f"  {c.label('2')}. Scan native token — semua chain")
    print(f"  {c.label('3')}. Scan ERC-20 token (tokens.json)")
    print(f"  {c.label('4')}. Kirim max native — 1 chain")
    print(f"  {c.label('0')}. Keluar")
    print(c.header("=" * 50))


def run_interactive(wallets: list[Wallet], chains: list[Chain], tokens_file: Path, show_usd: bool) -> None:
    actions = {
        "1": lambda: run_native_single(wallets, chains, show_usd),
        "2": lambda: run_native_all(wallets, chains, show_usd),
        "3": lambda: run_token_scan(wallets, chains, tokens_file, show_usd),
        "4": lambda: run_send_max(wallets, chains),
    }
    while True:
        print_menu()
        choice = input("\nPilih menu: ").strip()
        if choice == "0":
            print(c.info("Keluar."))
            break
        if choice in actions:
            actions[choice]()
            input(c.dim("\nTekan Enter untuk kembali ke menu..."))
        else:
            print(c.warn("Pilihan tidak valid."))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wallet tool — scan & kirim multi-chain")
    parser.add_argument(
        "--mode",
        choices=["menu", "native", "native-all", "tokens", "send"],
        default="menu",
        help="menu (default) | native | native-all | tokens | send",
    )
    parser.add_argument("--chain", help="ID chain dari chains.json (untuk mode native/send)")
    return parser.parse_args()


def resolve_chain(chains: list[Chain], chain_id: str | None) -> Chain:
    if not chain_id:
        return pick_chain(chains, "Pilih chain:")
    for chain in chains:
        if chain.id == chain_id:
            return chain
    print(c.error(f"Chain '{chain_id}' tidak ditemukan"))
    sys.exit(1)


def main() -> None:
    load_dotenv()
    args = parse_args()
    keys_file = os.getenv("PRIVATE_KEYS_FILE", "privatekey.txt").strip()
    chains_file = Path(os.getenv("CHAINS_FILE", "chains.json"))
    tokens_file = Path(os.getenv("TOKENS_FILE", "tokens.json"))
    show_usd = show_usd_enabled()

    private_keys = load_private_keys(keys_file)
    chains = load_chains(chains_file, silent_skip=args.mode != "menu")
    wallets = build_wallets(private_keys)

    print(c.info(f"Wallet loaded: {len(wallets)}"))
    print(c.info(f"Chain aktif  : {len(chains)}"))

    if args.mode == "menu":
        run_interactive(wallets, chains, tokens_file, show_usd)
    elif args.mode == "native":
        chain = resolve_chain(chains, args.chain)
        results = scan_native(wallets, [chain])
        prices, show_usd = fetch_prices([chain.coingecko_id], show_usd)
        print_native_report(wallets, [chain], results, prices, show_usd, f"NATIVE — {chain.name.upper()}")
    elif args.mode == "native-all":
        run_native_all(wallets, chains, show_usd)
    elif args.mode == "tokens":
        run_token_scan(wallets, chains, tokens_file, show_usd)
    elif args.mode == "send":
        if args.chain:
            chain = resolve_chain(chains, args.chain)
            # run send with pre-selected chain - reuse pick logic inline
            destination = os.getenv("DESTINATION_ADDRESS", "").strip()
            if not destination:
                print(c.warn("DESTINATION_ADDRESS belum diisi di .env"))
                return
            w3 = get_w3_required(chain.rpc_url)
            dest = Web3.to_checksum_address(destination)
            funded = [(w, w3.eth.get_balance(w.address)) for w in wallets if w3.eth.get_balance(w.address) > 0]
            if not funded:
                print(c.warn("Tidak ada saldo."))
                return
            if prompt_yes_no(f"Kirim max {len(funded)} wallet di {chain.name}?") and prompt_yes_no("Konfirmasi?"):
                success = sum(1 for w, _ in funded if send_max_value(w3, w.private_key, dest, chain))
                print(f"\n{c.success('Selesai.')} {success}/{len(funded)}")
        else:
            run_send_max(wallets, chains)


if __name__ == "__main__":
    main()
