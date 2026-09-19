from urllib.parse import urlsplit
import httpx


class RpcError(Exception):
    """Raised when an RPC request fails or returns an error/empty response."""
    pass


def _redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}/***"
    except Exception:
        return "***"


class RpcClient:
    def __init__(self, url: str, http: httpx.Client):
        self.url = url
        self.http = http
        self._redacted_url = _redact_url(url)

    def _call(self, method: str, params: list):
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        try:
            resp = self.http.post(self.url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            msg = str(exc).replace(self.url, self._redacted_url)
            raise RpcError(f"RPC request failed: {msg}") from exc

        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            err_str = str(err).replace(self.url, self._redacted_url)
            raise RpcError(f"RPC error: {err_str}")

        return data.get("result")

    def block_number(self) -> int:
        res = self._call("eth_blockNumber", [])
        if not res or not isinstance(res, str):
            raise RpcError("Invalid eth_blockNumber response")
        return int(res, 16)

    def get_balance(self, address: str, block: int) -> int:
        block_hex = hex(block)
        res = self._call("eth_getBalance", [address, block_hex])
        if res is None or not isinstance(res, str):
            raise RpcError(f"Invalid eth_getBalance response for {address}")
        return int(res, 16)

    def erc20_balance(self, token: str, owner: str, block: int) -> int:
        owner_clean = owner.lower().removeprefix("0x")
        data_call = "0x70a08231" + "0" * 24 + owner_clean
        block_hex = hex(block)

        call_obj = {
            "to": token,
            "data": data_call,
        }
        res = self._call("eth_call", [call_obj, block_hex])

        if not res or not isinstance(res, str) or res == "0x":
            raise RpcError(f"Invalid or empty eth_call response for token {token}")

        return int(res, 16)
