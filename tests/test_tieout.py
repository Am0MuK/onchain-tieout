import pytest
from onchain_tieout.tieout import run_tieout, Row, Report
from onchain_tieout.rpc import RpcError
from tests.conftest import WALLET, OTHER, WETH, USDC


class FakeExplorer:
    def __init__(self, txs=None, internals=None, tokentx=None):
        self.txs = txs or []
        self.internals = internals or []
        self.tokentx = tokentx or []
        self.calls = []

    def fetch_all(self, action, address, chain_id, end_block):
        self.calls.append((action, address, chain_id, end_block))
        if action == "txlist":
            return self.txs
        elif action == "txlistinternal":
            return self.internals
        elif action == "tokentx":
            return self.tokentx
        return []


class FakeRpc:
    def __init__(self, head=1000, native_balance=0, token_balances=None, fail_tokens=None):
        self.head = head
        self._native_balance = native_balance
        self._token_balances = token_balances or {}
        self.fail_tokens = {t.lower() for t in (fail_tokens or set())}
        self.calls = []

    def block_number(self):
        self.calls.append("block_number")
        return self.head

    def get_balance(self, address, block):
        self.calls.append(("get_balance", address, block))
        return self._native_balance

    def erc20_balance(self, token, owner, block):
        self.calls.append(("erc20_balance", token, owner, block))
        if token.lower() in self.fail_tokens:
            raise RpcError(f"balanceOf failed for {token}")
        return self._token_balances.get(token.lower(), 0)


def test_everything_ties_out():
    txs = [{"from": OTHER, "to": WALLET, "value": str(10**18), "gasUsed": "0", "gasPrice": "0", "isError": "0", "txreceipt_status": "1"}]
    tokentx = [{"from": OTHER, "to": WALLET, "value": "100000000", "contractAddress": USDC, "tokenSymbol": "USDC", "tokenDecimal": "6"}]

    exp = FakeExplorer(txs=txs, internals=[], tokentx=tokentx)
    rpc = FakeRpc(native_balance=10**18, token_balances={USDC: 100000000})

    report = run_tieout(WALLET, 1, exp, rpc, block=100)
    assert report.ok is True
    assert len(report.rows) == 2
    assert report.rows[0].kind == "native"
    assert report.rows[0].status == "OK"
    assert report.rows[1].kind == "erc20"
    assert report.rows[1].status == "OK"


def test_weth_deposit_case():
    txs = [
        {"from": OTHER, "to": WALLET, "value": str(2 * 10**18), "gasUsed": "0", "gasPrice": "0", "isError": "0", "txreceipt_status": "1"},
        {"from": WALLET, "to": WETH, "value": str(10**18), "input": "0xd0e30db0" + "00" * 32, "gasUsed": "21000", "gasPrice": "10", "isError": "0", "txreceipt_status": "1"},
    ]
    # tokentx has no WETH rows
    tokentx = []
    expected_native = 2 * 10**18 - 10**18 - 21000 * 10

    exp = FakeExplorer(txs=txs, internals=[], tokentx=tokentx)
    rpc = FakeRpc(native_balance=expected_native, token_balances={WETH: 10**18})

    report = run_tieout(WALLET, 1, exp, rpc, block=100)
    assert report.ok is False
    native_row = next(r for r in report.rows if r.kind == "native")
    assert native_row.status == "OK"

    weth_row = next(r for r in report.rows if r.contract == WETH)
    assert weth_row.status == "MISMATCH"
    assert weth_row.label == "weth_wrap_unwrap_untracked"
    assert weth_row.explained is True


def test_balance_of_raises_rpc_error():
    spam = "0x9999999999999999999999999999999999999999"
    tokentx = [{"from": OTHER, "to": WALLET, "value": "50", "contractAddress": spam, "tokenSymbol": "SPAM", "tokenDecimal": "18"}]

    exp = FakeExplorer(txs=[], internals=[], tokentx=tokentx)
    rpc = FakeRpc(native_balance=0, fail_tokens={spam})

    report = run_tieout(WALLET, 1, exp, rpc, block=100)
    assert report.ok is False
    spam_row = next(r for r in report.rows if r.contract == spam)
    assert spam_row.status == "READ_FAILED"
    assert spam_row.label == "balance_read_failed"
    assert spam_row.actual is None

    native_row = next(r for r in report.rows if r.kind == "native")
    assert native_row.status == "OK"


def test_default_block_is_head_minus_64():
    exp = FakeExplorer(txs=[], internals=[], tokentx=[])
    rpc = FakeRpc(head=200, native_balance=0)

    report = run_tieout(WALLET, 1, exp, rpc, block=None)
    assert report.block == 136
    # Explorer was called with end_block=136
    assert all(call[3] == 136 for call in exp.calls)
    # RPC was called with block 136
    assert any(call == ("get_balance", WALLET, 136) for call in rpc.calls)


def test_delta_within_dust():
    # Difference is 100 wei, default dust is 1e-9 ETH = 10**9 wei
    txs = [{"from": OTHER, "to": WALLET, "value": str(10**18), "gasUsed": "0", "gasPrice": "0", "isError": "0", "txreceipt_status": "1"}]
    exp = FakeExplorer(txs=txs, internals=[], tokentx=[])
    rpc = FakeRpc(native_balance=10**18 + 100)

    report = run_tieout(WALLET, 1, exp, rpc, block=100)
    native_row = report.rows[0]
    assert native_row.status == "OK"
    assert native_row.label is None
