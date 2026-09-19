import re
import time
import httpx

# Etherscan V2 serves at most 1,000 rows per page, even when a larger offset is
# requested. A page of exactly PAGE_SIZE rows may be truncated.
PAGE_SIZE = 1000
RATE_LIMIT_RETRIES = 5
RATE_LIMIT_BACKOFF_S = 0.5


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
        sleep=time.sleep,
    ):
        self.api_key = api_key
        self.http = http
        self.base_url = base_url
        self._sleep = sleep

    def fetch(
        self,
        action: str,
        address: str,
        chain_id: int,
        end_block: int,
        start_block: int = 0,
    ) -> list[dict]:
        """Fetch one page; retry when Etherscan reports its per-second rate limit."""
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                return self._fetch_once(action, address, chain_id, end_block, start_block)
            except ExplorerError as exc:
                if "rate limit" not in str(exc).lower() or attempt == RATE_LIMIT_RETRIES:
                    raise
                self._sleep(RATE_LIMIT_BACKOFF_S * (attempt + 1))
        raise AssertionError("unreachable")

    def _fetch_once(
        self,
        action: str,
        address: str,
        chain_id: int,
        end_block: int,
        start_block: int,
    ) -> list[dict]:
        params = {
            "chainid": str(chain_id),
            "module": "account",
            "action": action,
            "address": address,
            "startblock": str(start_block),
            "endblock": str(end_block),
            "page": "1",
            "offset": str(PAGE_SIZE),
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
            raise ExplorerError(redact(f"status 1 but result is not a list: {result!r}"[:300]))

        if status == "0" and message == "No transactions found" and result == []:
            return []

        err_msg = redact(f"{message}: {result}")
        if self.api_key and self.api_key in err_msg:
            err_msg = err_msg.replace(self.api_key, "***")
        raise ExplorerError(err_msg)

    def fetch_all(
        self,
        action: str,
        address: str,
        chain_id: int,
        end_block: int,
    ) -> list[dict]:
        """Fetch every row up to end_block, paginating past the per-page row cap.

        A full page may end in the middle of a block. Instead of de-duplicating
        rows by a key (which can merge genuinely identical rows, e.g. two equal
        transfers in one transaction), the rows of the last block are dropped
        and that whole block is fetched again from the start of the next page.
        """
        all_rows: list[dict] = []
        start_block = 0

        while True:
            page = self.fetch(action, address, chain_id, end_block, start_block=start_block)
            if len(page) < PAGE_SIZE:
                all_rows.extend(page)
                return all_rows

            first_block = int(page[0]["blockNumber"])
            last_block = int(page[-1]["blockNumber"])
            if first_block == last_block:
                raise ExplorerError(
                    f"more than {PAGE_SIZE} rows in block {last_block}; cannot paginate"
                )
            all_rows.extend(r for r in page if int(r["blockNumber"]) != last_block)
            start_block = last_block
