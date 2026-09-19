import os
import httpx
import pytest
from onchain_tieout.explorer import EtherscanClient
from onchain_tieout.rpc import RpcClient
from onchain_tieout.tieout import run_tieout

# Ethereum Foundation public address
PUBLIC_TEST_WALLET = "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe"


@pytest.mark.live
def test_live_smoke():
    api_key = os.environ.get("ETHERSCAN_API_KEY")
    rpc_url = os.environ.get("TIEOUT_RPC_URL")
    if not api_key or not rpc_url:
        pytest.skip("ETHERSCAN_API_KEY and TIEOUT_RPC_URL required for live test")

    with httpx.Client(timeout=30.0) as http:
        explorer = EtherscanClient(api_key=api_key, http=http)
        rpc = RpcClient(url=rpc_url, http=http)
        report = run_tieout(
            wallet=PUBLIC_TEST_WALLET,
            chain_id=1,
            explorer=explorer,
            rpc=rpc,
            block=19000000,
        )

    assert len(report.rows) >= 1
