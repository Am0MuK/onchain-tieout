import httpx
import pytest
from onchain_tieout.explorer import EtherscanClient, ExplorerError, redact, PAGE_SIZE
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


def test_paginates_by_startblock_refetching_boundary_block():
    calls = []

    def handler(request):
        start = int(request.url.params["startblock"])
        calls.append(start)
        if start == 0:
            rows = [{"hash": f"0x{i}", "blockNumber": str(i // 10)} for i in range(PAGE_SIZE)]
        else:
            # continuation starts AT the last block, so it repeats rows of block 999
            rows = [{"hash": f"0x{i}", "blockNumber": str(i // 10)} for i in range(PAGE_SIZE - 10, PAGE_SIZE + 5)]
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})

    c = EtherscanClient(api_key="k", http=mock_client(handler))
    rows = c.fetch_all("txlist", WALLET, chain_id=1, end_block=10**9)
    assert calls == [0, PAGE_SIZE // 10 - 1]
    assert len(rows) == PAGE_SIZE + 5
    assert len({r["hash"] for r in rows}) == PAGE_SIZE + 5


def test_single_block_overflow_guard():
    def handler(request):
        rows = [{"hash": f"0x{i}", "blockNumber": "50"} for i in range(PAGE_SIZE)]
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})

    c = EtherscanClient(api_key="k", http=mock_client(handler))
    with pytest.raises(ExplorerError, match="rows in block 50; cannot paginate"):
        c.fetch_all("txlist", WALLET, chain_id=1, end_block=10**9)



def test_status_one_with_non_list_result_raises_not_empty():
    c = _client({"status": "1", "message": "OK", "result": "unexpected string payload"})
    with pytest.raises(ExplorerError, match="unexpected"):
        c.fetch("txlist", WALLET, chain_id=1, end_block=100)


def test_identical_transfers_in_one_tx_survive_page_boundary():
    # Two identical transfers (same tx, token, from, to, value) and no logIndex
    # field. They sit in the boundary block of a full page and are returned
    # again by the continuation page. Both must be kept - collapsing them
    # would silently undercount the balance.
    dup = {"hash": "0xdup", "blockNumber": str(PAGE_SIZE), "contractAddress": "0xt",
           "from": "0xa", "to": WALLET, "value": "5"}

    def handler(request):
        start = int(request.url.params["startblock"])
        if start == 0:
            rows = [{"hash": f"0x{i}", "blockNumber": str(i // 10), "contractAddress": "0xt",
                     "from": "0xa", "to": WALLET, "value": "1"} for i in range(PAGE_SIZE - 2)]
            rows += [dict(dup), dict(dup)]
        else:
            rows = [dict(dup), dict(dup)]
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": rows})

    c = EtherscanClient(api_key="k", http=mock_client(handler))
    rows = c.fetch_all("tokentx", WALLET, chain_id=1, end_block=10**9)
    assert sum(1 for r in rows if r["hash"] == "0xdup") == 2


def test_page_size_is_what_etherscan_actually_serves():
    # Etherscan V2 returns at most 1,000 rows per page even when a larger
    # offset is requested; a 1,000-row page must be treated as possibly
    # truncated, never as the end of history.
    assert PAGE_SIZE == 1000

    def handler(request):
        assert request.url.params["offset"] == str(PAGE_SIZE)
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": []})

    EtherscanClient(api_key="k", http=mock_client(handler)).fetch("txlist", WALLET, 1, 100)


def test_rate_limit_is_retried_then_succeeds():
    responses = [
        {"status": "0", "message": "NOTOK", "result": "Max calls per sec rate limit reached (3/sec)"},
        {"status": "0", "message": "NOTOK", "result": "Max calls per sec rate limit reached (3/sec)"},
        {"status": "1", "message": "OK", "result": [{"hash": "0xa", "blockNumber": "1"}]},
    ]
    sleeps = []

    def handler(request):
        return httpx.Response(200, json=responses.pop(0))

    c = EtherscanClient(api_key="k", http=mock_client(handler), sleep=sleeps.append)
    assert c.fetch("txlist", WALLET, 1, 100) == [{"hash": "0xa", "blockNumber": "1"}]
    assert len(sleeps) == 2


def test_rate_limit_gives_up_after_retries():
    def handler(request):
        return httpx.Response(200, json={"status": "0", "message": "NOTOK",
                                         "result": "Max calls per sec rate limit reached (3/sec)"})

    c = EtherscanClient(api_key="k", http=mock_client(handler), sleep=lambda s: None)
    with pytest.raises(ExplorerError, match="rate limit"):
        c.fetch("txlist", WALLET, 1, 100)
