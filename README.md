# Wallet Tools

Tool sederhana untuk cek saldo wallet EVM (native + ERC-20) dari banyak private key sekaligus, dengan opsi kirim saldo max native.

## Fitur

- Scan **native token** — 1 chain atau semua chain
- Scan **ERC-20** (USDT, USDC, dll.) via `tokens.json`
- Konversi saldo ke **USD** (CoinGecko)
- **Kirim max** native ke wallet tujuan (saldo − gas fee)
- Output terminal **berwarna**

## Persyaratan

- Python 3.10+
- Koneksi internet (RPC + harga USD)

## Instalasi

```powershell
cd "E:\wallet tools"
pip install -r requirements.txt
```

## Setup

1. Copy config:
   ```powershell
   copy .env.example .env
   ```

2. Isi **`.env`** — RPC per chain (`RPC_ETHEREUM`, `RPC_BSC`, `RPC_VANA`, dll.) dan `DESTINATION_ADDRESS` untuk kirim max.

3. Buat **`privatekey.txt`** — satu private key per baris:
   ```
   0xabc...
   0xdef...
   ```

> **Jangan** taruh private key di `.env`. File `privatekey.txt` sudah di-ignore git.

## Cara Pakai

```powershell
python multi-chain-wallet.py
```

Menu:

| No | Fungsi |
|----|--------|
| 1 | Scan native — 1 chain |
| 2 | Scan native — semua chain |
| 3 | Scan ERC-20 token |
| 4 | Kirim max native — 1 chain |

### CLI (tanpa menu)

```powershell
python multi-chain-wallet.py --mode native-all
python multi-chain-wallet.py --mode native --chain ethereum
python multi-chain-wallet.py --mode tokens
python multi-chain-wallet.py --mode send --chain bsc
```

## Struktur File

| File | Keterangan |
|------|------------|
| `multi-chain-wallet.py` | Script utama |
| `chains.json` | Daftar chain + RPC env |
| `tokens.json` | Daftar ERC-20 untuk scan |
| `privatekey.txt` | Private key (rahasia) |
| `.env` | RPC URL & config |
| `colors.py` / `prices.py` | Helper warna & harga USD |

## Tambah Chain / Token

**Chain baru** — edit `chains.json`, lalu tambah RPC di `.env`:
```env
RPC_NAMACHAIN=https://rpc.example.com
```

**Token ERC-20** — edit `tokens.json`:
```json
{
  "chain_id": "bsc",
  "symbol": "USDT",
  "contract": "0x...",
  "decimals": 18,
  "coingecko_id": "tether",
  "enabled": true
}
```

## Opsi `.env`

```env
SHOW_USD=true          # tampilkan nilai USD
PRIVATE_KEYS_FILE=privatekey.txt
CHAINS_FILE=chains.json
TOKENS_FILE=tokens.json
```

Matikan warna terminal: `$env:NO_COLOR=1`

## Keamanan

- Jangan commit `privatekey.txt` atau `.env`
- Uji di testnet dulu sebelum mainnet
- Kirim max membutuhkan konfirmasi 2x — pastikan `DESTINATION_ADDRESS` benar
