# onchain-tieout

![tests](https://github.com/Am0MuK/onchain-tieout/actions/workflows/tests.yml/badge.svg)

`onchain-tieout` reconstructs native and ERC-20 balances for an EVM wallet at a specific block from Etherscan V2 transaction history.
It reads the ground truth directly from an Ethereum JSON-RPC archive node at the exact same block.
Every discrepancy is reported in a clean text table or JSON structure alongside an automated diagnosis explaining the likely cause.

Real run against a public wallet (vitalik.eth) on Ethereum mainnet, limited to five major tokens:

```
$ tieout check 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 --block 26006074 \
    --token 0x6b175474e89094c44da98b954eedeac495271d0f --token 0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48 \
    --token 0xdac17f958d2ee523a2206206994597c13d831ec7 --token 0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2 \
    --token 0xae7ab96520de3a18e5e111b5eaab095312d7fe84
wallet: 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 / chain: 1 / block: 26006074
SYMBOL  CONTRACT                                    COMPUTED                 ACTUAL                DELTA                   STATUS    LABEL
------  ------------------------------------------  -----------------------  --------------------  ----------------------  --------  --------------------------------------
ETH     -                                           6.712597953701629485     6.712597953701629485  0                       OK        -
DAI     0x6b175474e89094c44da98b954eedeac495271d0f  4.57207827332311288      4.57207827332311288   0                       OK        -
stETH   0xae7ab96520de3a18e5e111b5eaab095312d7fe84  0.000010179828756122     0.000010402510234962  0.00000022268147884     MISMATCH  rebasing_token
USDC    0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48  37.192124                37.192124             0                       OK        -
USDT    0xdac17f958d2ee523a2206206994597c13d831ec7  290.368219               290.368219            0                       OK        -
WETH    0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2  -569.831291758843272308  1.46189817401908887   571.293189932862361178  MISMATCH  weth_wrap_unwrap_untracked (explained)
FAIL: 2 of 6 rows do not tie out
  rebasing_token: 1
  weth_wrap_unwrap_untracked: 1
```

ETH, DAI, USDC and USDT tie out to the last unit. The two mismatches are the ones
transfer history cannot see: stETH rebases without transfers, and the WETH delta
equals the wallet's own `deposit()` minus `withdraw()` calls exactly.

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
- `--token`: Only check this ERC-20 contract; repeatable. The native balance is always checked. A listed token that never appears in history is still read (computed `0`), so missing history cannot pass silently.
- `--dust`: Dust tolerance in token units (default: `1e-9`).

### Wallets full of spam tokens

Without `--token`, every contract that ever emitted a `Transfer` involving the
wallet is checked. For a well-known address that is mostly airdropped spam: the
same wallet without `--token` produced 10,476 rows (8,281 OK, 2,113 mismatches,
80 unreadable, ~20 minutes, one `balanceOf` call per contract). Spam contracts
emit `Transfer` events that do not match their own `balanceOf`, some even
"spending" tokens the wallet never received, and many reuse real symbols
(USDC, WETH) on other contracts. The tool reports them rather than guessing which
are fake. Always compare the contract address, not the symbol.

## Exit Codes

- `0`: Everything ties out successfully.
- `1`: At least one balance mismatch or unreadable balance was detected.
- `2`: Usage, configuration, or data source error (e.g. invalid wallet, missing API key).

## Diagnosis Labels

| Label | Rule |
|---|---|
| `weth_wrap_unwrap_untracked` | Token is the chain's WETH and the wallet sent txs to it with selector `0xd0e30db0` (deposit) or `0x2e1a7d4d` (withdraw); reported delta explained if it equals deposits − withdrawals |
| `rebasing_token` | Token contract is in a known rebasing list (e.g. stETH mainnet `0xae7ab96520de3a18e5e111b5eaab095312d7fe84`) |
| `negative_history` | Transfer history says the wallet sent more than it ever received, impossible for a standard ERC-20; typical of spam tokens emitting fake `Transfer` events |
| `balance_read_failed` | `balanceOf` reverted / returned no usable data (spam or non-standard tokens). RPC transport failures (429/5xx, timeouts) are retried and then abort the run with exit `2`; they never produce this label |
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
