import time
from urllib.parse import urlsplit

import httpx

RETRIES = 5
BACKOFF_S = 0.5
_RETRY_STATUS = {429, 500, 502, 503, 504}


class RpcError(Exception):
    """The RPC endpoint could not answer (transport, rate limit, bad response).

    Says nothing about the queried contract; a tie-out run must not continue
    as if the balance were merely unreadable.
    """


class ContractCallError(RpcError):
    """The node answered, but the contract call reverted or returned no usable data."""


def _redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}/***"
    except Exception:
        return "***"


def _is_rate_limit(error: dict) -> bool:
    message = str(error.get("message", "")).lower()
    return error.get("code") in (429, -32005) or "rate" in message or "limit" in message


def _is_revert(error: dict) -> bool:
    return error.get("code") == 3 or "revert" in str(error.get("message", "")).lower()


class RpcClient:
    def __init__(self, url: str, http: httpx.Client, sleep=time.sleep):
        self.url = url
        self.http = http
        self._redacted_url = _redact_url(url)
        self._sleep = sleep

    def _clean(self, text) -> str:
        return str(text).replace(self.url, self._redacted_url)

    def _call(self, method: str, params: list):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last_problem = "no attempt made"

        for attempt in range(RETRIES + 1):
            if attempt:
                self._sleep(BACKOFF_S * attempt)
            try:
                resp = self.http.post(self.url, json=payload)
            except httpx.HTTPError as exc:
                last_problem = f"transport error: {self._clean(exc)}"
                continue

            if resp.status_code in _RETRY_STATUS:
                last_problem = f"HTTP {resp.status_code}"
                continue
            if resp.status_code >= 400:
                raise RpcError(f"RPC HTTP {resp.status_code} from {self._redacted_url}")

            try:
                data = resp.json()
            except ValueError:
                last_problem = "non-JSON response"
                continue

            error = data.get("error") if isinstance(data, dict) else None
            if error:
                if _is_revert(error):
                    raise ContractCallError(f"call reverted: {self._clean(error)}")
                if _is_rate_limit(error):
                    last_problem = f"rate limited: {self._clean(error)}"
                    continue
                raise RpcError(f"RPC error: {self._clean(error)}")

            return data.get("result")

        raise RpcError(
            f"RPC unavailable after {RETRIES + 1} attempts ({last_problem}) at {self._redacted_url}"
        )

    def block_number(self) -> int:
        res = self._call("eth_blockNumber", [])
        if not isinstance(res, str) or not res:
            raise RpcError("invalid eth_blockNumber response")
        return int(res, 16)

    def get_balance(self, address: str, block: int) -> int:
        res = self._call("eth_getBalance", [address, hex(block)])
        if not isinstance(res, str) or not res:
            raise RpcError(f"invalid eth_getBalance response for {address}")
        return int(res, 16)

    def erc20_balance(self, token: str, owner: str, block: int) -> int:
        data = "0x70a08231" + "0" * 24 + owner.lower().removeprefix("0x")
        res = self._call("eth_call", [{"to": token, "data": data}, hex(block)])
        if not isinstance(res, str) or len(res) < 66:
            raise ContractCallError(f"balanceOf returned no usable data for token {token}")
        return int(res[:66], 16)

    def erc20_decimals(self, token: str, block: int) -> int:
        res = self._call("eth_call", [{"to": token, "data": "0x313ce567"}, hex(block)])
        if not isinstance(res, str) or len(res) < 66:
            raise ContractCallError(f"decimals() returned no usable data for token {token}")
        return int(res[:66], 16)
