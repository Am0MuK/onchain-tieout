import json
from unittest.mock import patch
import pytest
from onchain_tieout.cli import main
from onchain_tieout.explorer import ExplorerError
from onchain_tieout.tieout import Report, Row
from tests.conftest import WALLET, USDC, WETH


def test_invalid_address(capsys):
    rc = main(["check", "0xinvalid"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "Invalid wallet address" in captured.err or "invalid" in captured.err.lower()


def test_missing_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    rc = main(["check", WALLET, "--rpc", "http://rpc"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "ETHERSCAN_API_KEY" in captured.err


def test_missing_rpc_url(monkeypatch, capsys):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "dummy_key")
    monkeypatch.delenv("TIEOUT_RPC_URL", raising=False)
    rc = main(["check", WALLET])
    captured = capsys.readouterr()
    assert rc == 2
    assert "RPC" in captured.err


def test_explorer_error_returns_2_and_redacts(monkeypatch, capsys):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "SECRETKEY123")
    with patch("onchain_tieout.cli.run_tieout") as mock_run:
        mock_run.side_effect = ExplorerError("Etherscan failure with SECRETKEY123")
        rc = main(["check", WALLET, "--rpc", "http://rpc"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "SECRETKEY123" not in captured.err


def test_ok_report_returns_0(monkeypatch, capsys):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    row = Row(
        kind="native",
        contract=None,
        symbol="ETH",
        decimals=18,
        computed=10**18,
        actual=10**18,
        status="OK",
        label=None,
        explained=False,
    )
    rep = Report(wallet=WALLET, chain_id=1, block=100, rows=[row])
    with patch("onchain_tieout.cli.run_tieout", return_value=rep):
        rc = main(["check", WALLET, "--rpc", "http://rpc"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK: all balances tie out" in captured.out


def test_mismatch_report_returns_1(monkeypatch, capsys):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    row = Row(
        kind="erc20",
        contract=USDC,
        symbol="USDC",
        decimals=6,
        computed=100_000_000,
        actual=105_000_000,
        status="MISMATCH",
        label="unexplained",
        explained=False,
    )
    rep = Report(wallet=WALLET, chain_id=1, block=100, rows=[row])
    with patch("onchain_tieout.cli.run_tieout", return_value=rep):
        rc = main(["check", WALLET, "--rpc", "http://rpc"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "FAIL:" in captured.out


def test_json_output_amounts_are_strings(monkeypatch, capsys):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    row = Row(
        kind="erc20",
        contract=USDC,
        symbol="USDC",
        decimals=6,
        computed=100_000_000,
        actual=105_000_000,
        status="MISMATCH",
        label="unexplained",
        explained=False,
    )
    rep = Report(wallet=WALLET, chain_id=1, block=100, rows=[row])
    with patch("onchain_tieout.cli.run_tieout", return_value=rep):
        rc = main(["check", WALLET, "--rpc", "http://rpc", "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["wallet"] == WALLET
    assert data["chain_id"] == 1
    assert data["block"] == 100
    assert data["ok"] is False
    assert len(data["rows"]) == 1
    r0 = data["rows"][0]
    assert isinstance(r0["computed"], str)
    assert isinstance(r0["actual"], str)
    assert isinstance(r0["delta"], str)
    assert r0["computed"] == "100"
    assert r0["actual"] == "105"
    assert r0["delta"] == "5"


def test_token_flag_is_passed_through(monkeypatch):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    rep = Report(wallet=WALLET, chain_id=1, block=100, rows=[])
    with patch("onchain_tieout.cli.run_tieout", return_value=rep) as run:
        main(["check", WALLET, "--rpc", "http://rpc", "--token", USDC, "--token", WETH])
    assert run.call_args.kwargs["tokens"] == [USDC, WETH]


def test_invalid_token_address_returns_2(monkeypatch, capsys):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    rc = main(["check", WALLET, "--rpc", "http://rpc", "--token", "0x123"])
    assert rc == 2
    assert "Invalid token address" in capsys.readouterr().err


def test_text_summary_counts_labels(monkeypatch, capsys):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    def mk(label, status="MISMATCH"):
        return Row(kind="erc20", contract=USDC, symbol="X", decimals=0, computed=1,
                   actual=0 if status == "MISMATCH" else None, status=status, label=label, explained=False)
    rows = [mk("unexplained"), mk("unexplained"), mk("negative_history"),
            mk("balance_read_failed", "READ_FAILED")]
    rep = Report(wallet=WALLET, chain_id=1, block=100, rows=rows)
    with patch("onchain_tieout.cli.run_tieout", return_value=rep):
        main(["check", WALLET, "--rpc", "http://rpc"])
    out = capsys.readouterr().out
    assert "FAIL: 4 of 4 rows do not tie out" in out
    assert "unexplained: 2" in out
    assert "negative_history: 1" in out
    assert "balance_read_failed: 1" in out


def test_small_amounts_never_use_scientific_notation(monkeypatch, capsys):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    row = Row(kind="erc20", contract=USDC, symbol="stETH", decimals=18, computed=0,
              actual=222681478840, status="MISMATCH", label="rebasing_token", explained=False)
    rep = Report(wallet=WALLET, chain_id=1, block=100, rows=[row])
    with patch("onchain_tieout.cli.run_tieout", return_value=rep):
        main(["check", WALLET, "--rpc", "http://rpc"])
    out = capsys.readouterr().out
    assert "0.00000022268147884" in out
    assert "E-" not in out


def test_explained_mismatch_is_marked_in_text(monkeypatch, capsys):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    row = Row(kind="erc20", contract=WETH, symbol="WETH", decimals=18, computed=-1,
              actual=1, status="MISMATCH", label="weth_wrap_unwrap_untracked", explained=True)
    rep = Report(wallet=WALLET, chain_id=1, block=100, rows=[row])
    with patch("onchain_tieout.cli.run_tieout", return_value=rep):
        main(["check", WALLET, "--rpc", "http://rpc"])
    assert "weth_wrap_unwrap_untracked (explained)" in capsys.readouterr().out


def test_huge_amounts_are_not_rounded(monkeypatch, capsys):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    raw = 123456789012345678901234567890123456789
    row = Row(kind="erc20", contract=USDC, symbol="X", decimals=18, computed=raw,
              actual=raw, status="OK", label=None, explained=False)
    rep = Report(wallet=WALLET, chain_id=1, block=100, rows=[row])
    with patch("onchain_tieout.cli.run_tieout", return_value=rep):
        main(["check", WALLET, "--rpc", "http://rpc", "--json"])
    assert json.loads(capsys.readouterr().out)["rows"][0]["computed"] == "123456789012345678901.234567890123456789"
