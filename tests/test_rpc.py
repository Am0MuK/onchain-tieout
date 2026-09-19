import json
import httpx
import pytest
from onchain_tieout.rpc import RpcClient, RpcError, ContractCallError
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


def test_revert_raises_contract_call_error():
    with pytest.raises(ContractCallError):
        rpc({"eth_call": lambda p: {"error": {"code": 3, "message": "execution reverted"}}}).erc20_balance(USDC, WALLET, 1)


def test_empty_return_raises_contract_call_error():
    with pytest.raises(ContractCallError):
        rpc({"eth_call": lambda p: "0x"}).erc20_balance(USDC, WALLET, 1)


def _sequence_client(responses, sleeps):
    def handler(request):
        status, body = responses.pop(0)
        if body is None:
            return httpx.Response(status, content=b"")
        body = dict(body, jsonrpc="2.0", id=json.loads(request.content)["id"])
        return httpx.Response(status, json=body)
    return RpcClient("http://rpc/secret-key", http=mock_client(handler), sleep=sleeps.append)


def test_http_429_is_retried_then_succeeds():
    sleeps = []
    c = _sequence_client([(429, None), (429, None), (200, {"result": "0x2a"})], sleeps)
    assert c.get_balance(WALLET, 1) == 42
    assert len(sleeps) == 2


def test_persistent_429_raises_transport_error_not_contract_error():
    c = _sequence_client([(429, None)] * 10, [])
    with pytest.raises(RpcError) as e:
        c.erc20_balance(USDC, WALLET, 1)
    assert not isinstance(e.value, ContractCallError)
    assert "secret-key" not in str(e.value)
