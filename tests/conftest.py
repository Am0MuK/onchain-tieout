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
