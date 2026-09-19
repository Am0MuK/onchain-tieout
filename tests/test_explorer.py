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


def test_single_block_overflow_guard():
    def handler(request):
        rows = [{"hash": f"0x{i}", "blockNumber": "50"} for i in range(10000)]
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})

    c = EtherscanClient(api_key="k", http=mock_client(handler))
    with pytest.raises(ExplorerError, match="more than 10000 rows in block 50; cannot paginate"):
        c.fetch_all("txlist", WALLET, chain_id=1, end_block=10**9)

