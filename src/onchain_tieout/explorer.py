import re
import httpx


class ExplorerError(Exception):
    """Raised when an explorer API call fails or returns an error status."""
    pass


def redact(text: str) -> str:
    """Redact sensitive API keys from URLs or error messages."""
    return re.sub(r"(apikey=)[^&\s]+", r"\1***", str(text), flags=re.IGNORECASE)


class EtherscanClient:
    def __init__(
        self,
        api_key: str,
        http: httpx.Client,
        base_url: str = "https://api.etherscan.io/v2/api",
    ):
        self.api_key = api_key
        self.http = http
        self.base_url = base_url

    def fetch(
        self,
        action: str,
        address: str,
        chain_id: int,
        end_block: int,
        start_block: int = 0,
    ) -> list[dict]:
        params = {
            "chainid": str(chain_id),
            "module": "account",
            "action": action,
            "address": address,
            "startblock": str(start_block),
            "endblock": str(end_block),
            "page": "1",
            "offset": "10000",
            "sort": "asc",
            "apikey": self.api_key,
        }

        try:
            resp = self.http.get(self.base_url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            msg = redact(str(exc))
            if self.api_key and self.api_key in msg:
                msg = msg.replace(self.api_key, "***")
            raise ExplorerError(f"Etherscan request failed: {msg}") from exc

        status = str(data.get("status", ""))
        message = str(data.get("message", ""))
        result = data.get("result")

        if status == "1":
            if isinstance(result, list):
                return result
            return []

        if status == "0" and message == "No transactions found" and result == []:
            return []

        err_msg = redact(f"{message}: {result}")
        if self.api_key and self.api_key in err_msg:
            err_msg = err_msg.replace(self.api_key, "***")
        raise ExplorerError(err_msg)
