# onchain-tieout v0.1 Implementation Plan

> Executor: implement task by task, strictly TDD (write the test, see it fail, implement, see it pass, commit). Read `SPEC.md` first — it is the source of truth. Do not add features that are not in SPEC.md.

**Goal:** CLI that reconstructs one EVM wallet's native + ERC-20 balances from Etherscan V2 history and ties them out against JSON-RPC balances at the same block.

**Architecture:** Pure-function core (`reconstruct.py`, `diagnose.py`) with thin I/O clients (`explorer.py`, `rpc.py`) injected into an orchestrator (`tieout.py`). Clients take an `httpx.Client`, so tests pass an `httpx.Client(transport=httpx.MockTransport(handler))` — no network in tests.

**Tech Stack:** Python 3.11+, `httpx`, `pytest`, `argparse`, `hatchling` build backend.

**Global rules**
- Amounts are `int` (wei / raw token units) everywhere in the core. `Decimal` only in rendering.
- Addresses compared lowercase.
- Never print or log the API key. Any exception message that could contain a URL must pass through `redact()` (Task 1).
- Run tests with: `python -m pytest -q` from the repo root.
- Commit after every task with a conventional-commit message.

---

### Task 0: Scaffold

**Files:** Create `pyproject.toml`, `src/onchain_tieout/__init__.py`, `tests/__init__.py` (empty), `tests/conftest.py`, `.gitignore`, `LICENSE` (MIT, "Copyright (c) 2026 Eduard Codrean").

`pyproject.toml`:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "onchain-tieout"
version = "0.1.0"
description = "Tie out an EVM wallet's reconstructed balances against on-chain state"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
tieout = "onchain_tieout.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/onchain_tieout"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["live: hits real Etherscan/RPC; needs ETHERSCAN_API_KEY and TIEOUT_RPC_URL"]
addopts = "-m 'not live'"
```

`tests/conftest.py`:
```python
import httpx
import pytest

WALLET = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def wallet():
    return WALLET
```

Create a venv, `pip install -e .[dev]`, run `python -m pytest -q` (expect "no tests ran"), commit `chore: scaffold project`.

---

### Task 1: Explorer client — response status handling

**Files:** Create `src/onchain_tieout/explorer.py`, `tests/test_explorer.py`.

Test:
```python
import httpx
import pytest
from onchain_tieout.explorer import EtherscanClient, ExplorerError, redact
from tests.conftest import mock_client, WALLET


def _client(payload, status_code=200):
    def handler(request):
        return httpx.Response(status_code, json=payload)
    return EtherscanClient(api_key="SECRETKEY", http=mock_client(handler))


def test_ok_rows_returned():
    c = _client({"status": "1", "message": "OK", "result": [{"hash": "0xa", "blockNumber": "5"}]})
    assert c.fetch("txlist", WALLET, chain_id=1, end_block=100) == [{"hash": "0xa", "blockNumber": "5"}]


def test_no_transactions_is_valid_empty():
    c = _client({"status": "0", "message": "No transactions found", "result": []})
    assert c.fetch("txlist", WALLET, chain_id=1, end_block=100) == []


def test_status_zero_with_other_message_raises_not_empty():
    c = _client({"status": "0", "message": "NOTOK",
                 "result": "Free API access is not supported for this chain"})
    with pytest.raises(ExplorerError, match="Free API access is not supported"):
        c.fetch("txlist", WALLET, chain_id=8453, end_block=100)


def test_http_error_raises_and_redacts_key():
    c = _client({"x": 1}, status_code=500)
    with pytest.raises(ExplorerError) as e:
        c.fetch("txlist", WALLET, chain_id=1, end_block=100)
    assert "SECRETKEY" not in str(e.value)


def test_redact():
    assert "abc" not in redact("https://x/api?apikey=abc&module=account")
```

Implementation contract:
- `EtherscanClient(api_key: str, http: httpx.Client, base_url="https://api.etherscan.io/v2/api")`
- `fetch(action, address, chain_id, end_block, start_block=0) -> list[dict]` — one page: params `chainid, module=account, action, address, startblock, endblock, page=1, offset=10000, sort=asc, apikey`.
- `redact(text) -> str` replaces `apikey=<anything up to & or end>` with `apikey=***`.
- `ExplorerError(Exception)`.

Run, see fail, implement, see pass, commit `feat: etherscan client with strict status handling`.

---

### Task 2: Explorer pagination past the 10,000-row cap

**Files:** Modify `src/onchain_tieout/explorer.py`, add tests to `tests/test_explorer.py`.

Test:
```python
def test_paginates_by_startblock_and_dedupes():
    calls = []

    def handler(request):
        start = int(request.url.params["startblock"])
        calls.append(start)
        if start == 0:
            rows = [{"hash": f"0x{i}", "blockNumber": str(i // 10)} for i in range(10000)]
        else:
            # continuation starts AT the last block, so it repeats rows of block 999
            rows = [{"hash": f"0x{i}", "blockNumber": str(i // 10)} for i in range(9990, 10005)]
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})

    c = EtherscanClient(api_key="k", http=mock_client(handler))
    rows = c.fetch_all("txlist", WALLET, chain_id=1, end_block=10**9)
    assert calls == [0, 999]
    assert len(rows) == 10005
    assert len({r["hash"] for r in rows}) == 10005
```

Contract: `fetch_all(action, address, chain_id, end_block) -> list[dict]`. Loop: fetch page; if `len(page) == 10000`, next `start_block = int(page[-1]["blockNumber"])`; stop when page shorter than 10000. De-duplicate with `dedupe_key(action, row)`:
- `txlist` → `row["hash"]`
- `txlistinternal` → `(row["hash"], row.get("traceId", ""))`
- `tokentx` → `(row["hash"], row["logIndex"])` if `"logIndex"` in row, else `(row["hash"], row["contractAddress"].lower(), row["from"].lower(), row["to"].lower(), row["value"])`

Also add a guard: if a continuation page returns only already-seen rows and is still 10,000 long (a single block with >10,000 rows), raise `ExplorerError("more than 10000 rows in block N; cannot paginate")` instead of looping forever — with a test.

Commit `feat: paginate past 10k result cap with dedupe`.

---

### Task 3: Native balance reconstruction

**Files:** Create `src/onchain_tieout/reconstruct.py`, `tests/test_reconstruct.py`.

Test:
```python
from onchain_tieout.reconstruct import native_balance, token_balances
from tests.conftest import WALLET, OTHER, USDC


def tx(frm, to, value, gas_used=21000, gas_price=10, is_error="0", receipt="1"):
    return {"from": frm, "to": to, "value": str(value), "gasUsed": str(gas_used),
            "gasPrice": str(gas_price), "isError": is_error, "txreceipt_status": receipt}


def test_incoming_and_outgoing_with_gas():
    txs = [tx(OTHER, WALLET, 1000), tx(WALLET, OTHER, 300)]
    assert native_balance(WALLET, txs, []) == 1000 - 300 - 21000 * 10


def test_reverted_tx_value_ignored_gas_kept():
    txs = [tx(OTHER, WALLET, 10**18), tx(WALLET, OTHER, 5 * 10**17, is_error="1")]
    assert native_balance(WALLET, txs, []) == 10**18 - 21000 * 10


def test_receipt_status_zero_also_counts_as_reverted():
    txs = [tx(OTHER, WALLET, 100), tx(WALLET, OTHER, 50, is_error="0", receipt="0")]
    assert native_balance(WALLET, txs, []) == 100 - 21000 * 10


def test_incoming_tx_gas_is_not_charged_to_wallet():
    txs = [tx(OTHER, WALLET, 100, gas_used=50000, gas_price=99)]
    assert native_balance(WALLET, txs, []) == 100


def test_internal_transfers_counted_and_failed_internal_ignored():
    internals = [{"from": OTHER, "to": WALLET, "value": "700", "isError": "0"},
                 {"from": OTHER, "to": WALLET, "value": "999", "isError": "1"}]
    assert native_balance(WALLET, [], internals) == 700


def test_address_case_insensitive():
    txs = [tx(OTHER.upper().replace("0X", "0x"), WALLET.upper().replace("0X", "0x"), 5)]
    assert native_balance(WALLET, txs, []) == 5
```

Contract: `native_balance(wallet: str, txs: list[dict], internal_txs: list[dict]) -> int`. Reverted = `isError == "1"` or `txreceipt_status == "0"`. Gas charged for every tx where `from == wallet`, including reverted.

Commit `feat: native balance reconstruction`.

---

### Task 4: ERC-20 balance reconstruction

**Files:** Modify `src/onchain_tieout/reconstruct.py`, add tests.

Test:
```python
def ttx(frm, to, value, contract=USDC, symbol="USDC", decimals="6"):
    return {"from": frm, "to": to, "value": str(value), "contractAddress": contract,
            "tokenSymbol": symbol, "tokenDecimal": decimals}


def test_token_in_out_per_contract():
    rows = [ttx(OTHER, WALLET, 5_000_000), ttx(WALLET, OTHER, 1_500_000)]
    out = token_balances(WALLET, rows)
    assert out[USDC].raw == 3_500_000
    assert out[USDC].decimals == 6
    assert out[USDC].symbol == "USDC"


def test_self_transfer_nets_zero():
    out = token_balances(WALLET, [ttx(WALLET, WALLET, 42)])
    assert out[USDC].raw == 0
```

Contract: `token_balances(wallet, token_txs) -> dict[str, TokenBalance]` keyed by lowercase contract; `TokenBalance` is a frozen dataclass `(contract: str, symbol: str, decimals: int, raw: int)`.

Commit `feat: erc20 balance reconstruction`.

---

### Task 5: RPC client

**Files:** Create `src/onchain_tieout/rpc.py`, `tests/test_rpc.py`.

Test:
```python
import json
import httpx
import pytest
from onchain_tieout.rpc import RpcClient, RpcError
from tests.conftest import mock_client, WALLET, USDC


def rpc(handler_map):
    def handler(request):
        body = json.loads(request.content)
        result = handler_map[body["method"]](body["params"])
        if isinstance(result, dict) and "error" in result:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": result["error"]})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})
    return RpcClient("http://rpc", http=mock_client(handler))


def test_block_number():
    assert rpc({"eth_blockNumber": lambda p: "0x10"}).block_number() == 16


def test_get_balance_at_block():
    seen = {}
    def gb(p):
        seen["p"] = p
        return "0xde0b6b3a7640000"
    assert rpc({"eth_getBalance": gb}).get_balance(WALLET, 100) == 10**18
    assert seen["p"] == [WALLET, "0x64"]


def test_erc20_balance_of_encodes_call():
    seen = {}
    def call(p):
        seen["p"] = p
        return "0x" + "00" * 31 + "2a"
    assert rpc({"eth_call": call}).erc20_balance(USDC, WALLET, 100) == 42
    assert seen["p"][0]["to"] == USDC
    assert seen["p"][0]["data"] == "0x70a08231" + "0" * 24 + WALLET[2:]
    assert seen["p"][1] == "0x64"


def test_revert_raises_rpc_error():
    with pytest.raises(RpcError):
        rpc({"eth_call": lambda p: {"error": {"code": 3, "message": "execution reverted"}}}).erc20_balance(USDC, WALLET, 1)


def test_empty_return_raises_rpc_error():
    with pytest.raises(RpcError):
        rpc({"eth_call": lambda p: "0x"}).erc20_balance(USDC, WALLET, 1)
```

Contract: `RpcClient(url, http)`, methods `block_number()`, `get_balance(address, block) -> int`, `erc20_balance(token, owner, block) -> int`; JSON-RPC errors and empty/short return data raise `RpcError`. Error messages must not include the full RPC URL (it can contain a key) — use `redact`-style masking of the path/query.

Commit `feat: json-rpc client for balance reads`.

---

### Task 6: Diagnosis

**Files:** Create `src/onchain_tieout/diagnose.py`, `tests/test_diagnose.py`.

Test:
```python
from onchain_tieout.diagnose import diagnose, WETH_BY_CHAIN, REBASING
from tests.conftest import WALLET, OTHER, WETH, USDC


def call(to, selector, value="0", frm=WALLET, is_error="0"):
    return {"from": frm, "to": to, "input": selector + "00" * 32, "value": value,
            "isError": is_error, "txreceipt_status": "1"}


def test_weth_deposit_and_withdraw_explain_delta():
    txs = [call(WETH, "0xd0e30db0", value=str(3 * 10**18)),   # deposit 3 WETH
           {"from": WALLET, "to": WETH, "value": "0", "isError": "0", "txreceipt_status": "1",
            "input": "0x2e1a7d4d" + hex(10**18)[2:].rjust(64, "0")}]  # withdraw 1 WETH
    label, explained = diagnose(chain_id=1, wallet=WALLET, contract=WETH, delta=2 * 10**18, txs=txs)
    assert label == "weth_wrap_unwrap_untracked"
    assert explained is True


def test_weth_label_but_not_fully_explained():
    txs = [call(WETH, "0xd0e30db0", value="5")]
    label, explained = diagnose(1, WALLET, WETH, delta=7, txs=txs)
    assert label == "weth_wrap_unwrap_untracked"
    assert explained is False


def test_reverted_weth_calls_ignored():
    txs = [call(WETH, "0xd0e30db0", value="5", is_error="1")]
    assert diagnose(1, WALLET, WETH, delta=5, txs=txs) == ("unexplained", False)


def test_rebasing():
    assert diagnose(1, WALLET, REBASING[1][0], delta=123, txs=[]) == ("rebasing_token", False)


def test_unexplained():
    assert diagnose(1, WALLET, USDC, delta=1, txs=[]) == ("unexplained", False)
```

Contract: `diagnose(chain_id, wallet, contract, delta, txs) -> tuple[str, bool]` where `delta = actual − computed` (raw units). `WETH_BY_CHAIN = {1: "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"}`, `REBASING = {1: ["0xae7ab96520de3a18e5e111b5eaab095312d7fe84"]}`. WETH rule: consider successful txs (not reverted) from wallet to WETH. A deposit (`input` starts with `0xd0e30db0`) adds `int(value)`; a withdraw (`input` starts with `0x2e1a7d4d`) subtracts `int(input[10:74], 16)`. Deposits increase WETH held without a Transfer event (actual > computed → positive delta); withdrawals decrease it (negative delta). `explained = (deposits − withdrawals) == delta`. Label only if at least one such tx exists.

Commit `feat: mismatch diagnosis labels`.

---

### Task 7: Orchestrator

**Files:** Create `src/onchain_tieout/tieout.py`, `tests/test_tieout.py`.

Contract:
```python
@dataclass(frozen=True)
class Row:
    kind: str            # "native" | "erc20"
    contract: str | None
    symbol: str
    decimals: int
    computed: int
    actual: int | None   # None when read failed
    status: str          # "OK" | "MISMATCH" | "READ_FAILED"
    label: str | None    # None when OK
    explained: bool

@dataclass(frozen=True)
class Report:
    wallet: str
    chain_id: int
    block: int
    rows: list[Row]
    @property
    def ok(self) -> bool: ...   # all rows OK

def run_tieout(wallet, chain_id, explorer, rpc, block=None, dust_units="0.000000001") -> Report
```
- `block is None` → `rpc.block_number() - 64`.
- Fetch the three lists with `end_block=block`, reconstruct, read truth, compare: mismatch if `abs(actual - computed) > dust_raw` where `dust_raw = int(Decimal(dust_units) * 10**decimals)`.
- Native row: symbol `"ETH"` (v0.1), decimals 18, label via diagnose is not applicable → `"unexplained"` on mismatch.
- `RpcError` on a token read → row `READ_FAILED`, label `balance_read_failed`, run continues.
- Rows sorted: native first, then tokens by symbol.

Tests (use tiny fake explorer/rpc classes in the test file — no HTTP needed here):
1. everything ties out → `report.ok is True`.
2. WETH deposit case: tokentx has no WETH rows, txlist has a deposit of 1 ETH, rpc WETH balance = 1e18 → WETH row MISMATCH, label `weth_wrap_unwrap_untracked`, explained True; native row still OK (deposit value correctly subtracted as outgoing native value).
3. `balanceOf` raises `RpcError` for a spam token → READ_FAILED row, other rows unaffected, `report.ok is False`.
4. default block = head − 64 and that block is passed to all explorer calls and RPC reads.
5. delta within dust → OK.

Commit `feat: tie-out orchestrator`.

---

### Task 8: Rendering + CLI

**Files:** Create `src/onchain_tieout/report.py`, `src/onchain_tieout/cli.py`, `tests/test_cli.py`.

- `render_text(report) -> str`: header line `wallet / chain / block`, then aligned columns SYMBOL CONTRACT COMPUTED ACTUAL DELTA STATUS LABEL, amounts formatted with `Decimal(raw) / 10**decimals` (no float), final line `OK: all balances tie out` or `FAIL: N of M rows do not tie out`.
- `render_json(report) -> str`: amounts as decimal strings, keys `wallet, chain_id, block, ok, rows[]`.
- `cli.main(argv=None) -> int`: subcommand `check wallet [--chain 1] [--block N] [--rpc URL] [--json] [--dust 1e-9]`. Reads `ETHERSCAN_API_KEY`, RPC from `--rpc` or `TIEOUT_RPC_URL`. Missing config / invalid address / `ExplorerError` → message to stderr, return 2. Report ok → 0, else 1. `if __name__ == "__main__": sys.exit(main())`.

Tests: invalid address → 2; missing API key → 2 with a clear message; `ExplorerError` from a patched `run_tieout` → 2 and key not in output; mismatch report → 1; ok report → 0; `--json` output parses with `json.loads` and amounts are strings.

Commit `feat: cli with text and json output`.

---

### Task 9: Live smoke test, CI, README

**Files:** Create `tests/test_live.py`, `.github/workflows/tests.yml`, `README.md`.

`tests/test_live.py`: `@pytest.mark.live`, skip unless both env vars set; runs `run_tieout` for a well-known public address on chain 1 at an explicit block and asserts it returns a `Report` with at least one row (no assertion on OK — real wallets can legitimately fail tie-out).

`.github/workflows/tests.yml`:
```yaml
name: tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e .[dev]
      - run: python -m pytest -q
```

README sections: what it does (3 lines + example output block produced by actually running the text renderer on the Task 7 WETH fixture), why (the five silent failure modes, one line each), install, usage, exit codes, diagnosis labels table, known limitations (copy from SPEC.md), how tests work (offline MockTransport, one test per failure mode), license. Add a CI badge line `![tests](https://github.com/Am0MuK/onchain-tieout/actions/workflows/tests.yml/badge.svg)`.

Commit `docs: readme, ci workflow, live smoke test`.

---

### Done criteria
- `python -m pytest -q` green, zero network access (run once with networking unavailable if possible).
- `tieout check 0xinvalid` exits 2.
- No API key, RPC URL, or personal address anywhere in the repo (`git grep -i apikey=` shows only the redaction code/tests).
