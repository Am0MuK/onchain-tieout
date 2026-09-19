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
