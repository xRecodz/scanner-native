"""Ambil harga token native dalam USD via CoinGecko."""

from __future__ import annotations

from decimal import Decimal

import requests

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


def fetch_usd_prices(coin_ids: list[str]) -> dict[str, Decimal]:
    unique = sorted({coin_id for coin_id in coin_ids if coin_id})
    if not unique:
        return {}

    try:
        response = requests.get(
            COINGECKO_URL,
            params={"ids": ",".join(unique), "vs_currencies": "usd"},
            timeout=15,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        return {
            coin_id: Decimal(str(item["usd"]))
            for coin_id, item in data.items()
            if isinstance(item, dict) and "usd" in item
        }
    except (requests.RequestException, ValueError, KeyError):
        return {}


def to_usd(wei: int, decimals: int, price_usd: Decimal) -> Decimal:
    amount = Decimal(wei) / Decimal(10**decimals)
    return amount * price_usd


def format_usd(value: Decimal) -> str:
    if value >= 1000:
        return f"${value:,.2f}"
    if value >= 1:
        return f"${value:.2f}"
    if value >= 0.01:
        return f"${value:.4f}"
    if value > 0:
        return f"${value:.6f}"
    return "$0.00"
