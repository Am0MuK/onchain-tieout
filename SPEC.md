# onchain-tieout — Specification (v0.1)

## Problem

Blockchain data pipelines (portfolio trackers, tax tools, indexers) reconstruct a
wallet's balances from transaction history supplied by an explorer or indexer API.
Several failure modes make that history silently incomplete or wrong while the
pipeline still "succeeds":

- The API answers HTTP 200 with `status: "0"` and an error message (e.g. "Free API
  access is not supported for this chain") — easy to misread as "no transactions".
- Result sets are capped (10,000 rows per query); without pagination the history
  is silently truncated.
- Reverted transactions appear in transaction lists with a non-zero `value`, but
  no value moved (the gas fee did).
- `WETH9.deposit()` / `withdraw()` emit `Deposit` / `Withdrawal`, never an ERC-20
  `Transfer`, so transfer-based token history never sees the WETH leg.
- Rebasing tokens (e.g. stETH) change balances without any transfer.

The only reliable check is a **tie-out**: compare the balance reconstructed from
history against the balance the chain itself reports, at the same block.

## Goal

A small CLI that, for one wallet on one EVM chain at one block, reconstructs
native and ERC-20 balances from explorer history, reads the real balances from
the chain via JSON-RPC at the same block, and reports every mismatch with a
probable cause where one can be identified.

```
tieout check <wallet> --chain 1 [--block N] [--json] [--dust 1e-9]
```

Exit code `0` = everything ties out, `1` = at least one mismatch or unreadable
balance, `2` = usage/configuration/data-source error.

## Inputs

| Input | Source | Notes |
|---|---|---|
| wallet | CLI arg | EOA address, `0x` + 40 hex; compared lowercase |
| chain id | `--chain` (default 1) | passed as `chainid` to Etherscan V2 |
| block | `--block` (default: head − 64) | one block for both history and chain reads |
| Etherscan API key | env `ETHERSCAN_API_KEY` | never printed, redacted from error messages |
| RPC URL | env `TIEOUT_RPC_URL` or `--rpc` | must serve state at the chosen block (archive node for old blocks) |

Default block is `eth_blockNumber − 64` so the explorer has indexed it.

## Data flow

1. Resolve block N (explicit or head − 64).
2. Fetch, with `endblock=N`, via Etherscan V2 (`https://api.etherscan.io/v2/api`):
   `txlist`, `txlistinternal`, `tokentx`.
3. Reconstruct:
   - native (wei): `+ value` of successful normal txs to wallet, `− value` of
     successful normal txs from wallet, `− gasUsed × gasPrice` of **every** normal
     tx sent by the wallet (including reverted), `+/−` successful internal txs.
     A tx is reverted if `isError == "1"` or `txreceipt_status == "0"`.
   - ERC-20 (raw units, per `contractAddress`): `+ value` in, `− value` out.
4. Read truth at N via RPC: `eth_getBalance(wallet, N)` and
   `eth_call(balanceOf(wallet), N)` for every token contract seen in history.
5. Compare with integer arithmetic. A row is a mismatch if
   `|actual − computed| > dust`, where dust defaults to 1e-9 token units
   (converted to raw units with the token's decimals; native uses 18).
6. Diagnose each mismatch (labels below), render text table or JSON.

## Explorer response handling (the core of the tool)

- `status == "1"` → rows in `result`.
- `status == "0"` and `message == "No transactions found"` and `result == []` →
  empty, valid.
- any other `status == "0"` → raise `ExplorerError(message, result)`; never
  treated as empty history.
- HTTP error / non-JSON → `ExplorerError`.
- Pagination: request `page=1&offset=10000&sort=asc`. If exactly 10,000 rows come
  back, request again with `startblock = last row's blockNumber` and de-duplicate
  (keys: `txlist` → `hash`; `txlistinternal` → `(hash, traceId)`;
  `tokentx` → `(hash, logIndex)`). Repeat until a page has < 10,000 rows.

## Diagnosis labels

| Label | Rule |
|---|---|
| `weth_wrap_unwrap_untracked` | token is the chain's WETH and the wallet sent txs to it with selector `0xd0e30db0` (deposit) or `0x2e1a7d4d` (withdraw); reported delta explained if it equals deposits − withdrawals |
| `rebasing_token` | token contract is in a known rebasing list (stETH mainnet `0xae7ab96520de3a18e5e111b5eaab095312d7fe84`) |
| `balance_read_failed` | `balanceOf` reverted / returned invalid data (spam or non-standard tokens) |
| `unexplained` | anything else |

WETH (chain 1): `0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2`.

## Output

Text: one row per asset — symbol, contract, computed, actual, delta, status
(`OK` / `MISMATCH` / `READ_FAILED`), label. JSON: same data, amounts as decimal
strings (never floats), plus `block`, `chain_id`, `wallet`, `ok` (bool).

## Known limitations (documented in README, not handled in v0.1)

- L2 chains (Optimism, Base, Arbitrum…): the L1 data fee is not in
  `gasUsed × gasPrice`, so native balances will not tie out exactly.
- Validator withdrawals, block rewards, genesis allocations, self-destruct
  credits are not in `txlist`/`txlistinternal`.
- Contract wallets (Safe etc.): native movements via internal calls only partly
  covered; v0.1 targets EOAs.
- Fee-on-transfer tokens surface as `unexplained`.

## Non-goals (v0.1)

No database, no UI, no multi-wallet batch, no prices, no tax logic, no
alternative data sources.

## Quality bar

- Python ≥ 3.11, dependencies: `httpx` only (tests: `pytest`).
- All tests offline via `httpx.MockTransport`; one test per failure mode above.
- Integer math for amounts (wei / raw units); `Decimal` only for display.
- GitHub Actions runs `pytest` on every push.
- A live smoke test (`@pytest.mark.live`) runs only when `ETHERSCAN_API_KEY` and
  `TIEOUT_RPC_URL` are set.
