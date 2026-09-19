# onchain-tieout

![tests](https://github.com/Am0MuK/onchain-tieout/actions/workflows/tests.yml/badge.svg)

`onchain-tieout` reconstructs native and ERC-20 balances for an EVM wallet at a specific block from Etherscan V2 transaction history.
It reads the ground truth directly from an Ethereum JSON-RPC archive node at the exact same block.
Every discrepancy is reported in a clean text table or JSON structure alongside an automated diagnosis explaining the likely cause.

```
wallet: 0x1111111111111111111111111111111111111111 / chain: 1 / block: 100
SYMBOL  CONTRACT                                    COMPUTED  ACTUAL   DELTA  STATUS    LABEL                     
------  ------------------------------------------  --------  -------  -----  --------  --------------------------
ETH     -                                           0.99979   0.99979  0      OK        -                         
WETH    0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2  0         1        1      MISMATCH  weth_wrap_unwrap_untracked
FAIL: 1 of 2 rows do not tie out
```

## Why

Blockchain data pipelines routinely encounter silent failure modes where ingestion finishes without errors but balances are incomplete or incorrect:
- **Status 0 Errors**: Explorer APIs return HTTP 200 with `status: "0"` on errors or unsupported chains, easily mistaken for empty history.
- **Silent Truncation**: Explorer pages are capped (Etherscan V2 serves 1,000 rows per page even when 10,000 are requested); treating a short page as "the end" silently truncates history.
- **Reverted Transactions**: Reverted transactions include non-zero `value` in explorer results despite no value moving (only gas was spent).
- **WETH Wrap/Unwrap**: `WETH9.deposit()` and `withdraw()` emit `Deposit` and `Withdrawal` events rather than ERC-20 `Transfer`, rendering WETH legs invisible to transfer indexers.
- **Rebasing Tokens**: Tokens such as stETH adjust balances continuously without emitting on-chain transfer events.

## Installation

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Usage

Set your Etherscan API key and RPC URL (or pass `--rpc`):

```bash
export ETHERSCAN_API_KEY="your-api-key"
export TIEOUT_RPC_URL="https://eth-mainnet.g.alchemy.com/v2/your-key"

tieout check 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 --chain 1
```

Options:
- `--chain`: EVM chain ID (default: `1`).
- `--block`: Block number to check (default: head − 64).
- `--rpc`: JSON-RPC provider URL (overrides `TIEOUT_RPC_URL`).
- `--json`: Output as JSON.
- `--dust`: Dust tolerance in token units (default: `1e-9`).

## Exit Codes

- `0`: Everything ties out successfully.
- `1`: At least one balance mismatch or unreadable balance was detected.
- `2`: Usage, configuration, or data source error (e.g. invalid wallet, missing API key).

## Diagnosis Labels

| Label | Rule |
|---|---|
| `weth_wrap_unwrap_untracked` | Token is the chain's WETH and the wallet sent txs to it with selector `0xd0e30db0` (deposit) or `0x2e1a7d4d` (withdraw); reported delta explained if it equals deposits − withdrawals |
| `rebasing_token` | Token contract is in a known rebasing list (e.g. stETH mainnet `0xae7ab96520de3a18e5e111b5eaab095312d7fe84`) |
| `balance_read_failed` | `balanceOf` reverted / returned invalid data (spam or non-standard tokens) |
| `unexplained` | Anything else |

## Known Limitations

- **L2 chains** (Optimism, Base, Arbitrum…): The L1 data fee is not in `gasUsed × gasPrice`, so native balances will not tie out exactly.
- **Non-transaction movements**: Validator withdrawals, block rewards, genesis allocations, and self-destruct credits are not captured in `txlist`/`txlistinternal`.
- **Contract wallets** (Safe, etc.): Native movements via internal calls are only partly covered; v0.1 targets EOAs.
- **Fee-on-transfer tokens**: Surface as `unexplained`.

## Testing

All tests run completely offline with no network access using `httpx.MockTransport`:

```bash
python -m pytest -q
```

A live smoke test against mainnet is marked with `@pytest.mark.live` and can be run when credentials are provided:

```bash
ETHERSCAN_API_KEY="..." TIEOUT_RPC_URL="..." pytest -m live
```

## License

MIT License. Copyright (c) 2026 Eduard Codrean.
