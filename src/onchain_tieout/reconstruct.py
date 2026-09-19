from dataclasses import dataclass


@dataclass(frozen=True)
class TokenBalance:
    contract: str
    symbol: str
    decimals: int
    raw: int


def _is_reverted(tx: dict) -> bool:
    return tx.get("isError") == "1" or tx.get("txreceipt_status") == "0"


def native_balance(
    wallet: str,
    txs: list[dict],
    internal_txs: list[dict],
) -> int:
    w = wallet.lower()
    balance = 0

    for t in txs:
        frm = t.get("from", "").lower()
        to = t.get("to", "").lower()
        reverted = _is_reverted(t)

        # Gas is paid by the sender for every normal transaction, including reverted
        if frm == w:
            gas_used = int(t.get("gasUsed", 0))
            gas_price = int(t.get("gasPrice", 0))
            balance -= gas_used * gas_price

        # Value transfers only happen if transaction succeeded
        if not reverted:
            val = int(t.get("value", 0))
            if to == w:
                balance += val
            if frm == w:
                balance -= val

    for it in internal_txs:
        if _is_reverted(it):
            continue
        frm = it.get("from", "").lower()
        to = it.get("to", "").lower()
        val = int(it.get("value", 0))
        if to == w:
            balance += val
        if frm == w:
            balance -= val

    return balance


def token_balances(
    wallet: str,
    token_txs: list[dict],
) -> dict[str, TokenBalance]:
    w = wallet.lower()
    balances: dict[str, int] = {}
    symbols: dict[str, str] = {}
    decimals_map: dict[str, int] = {}

    for row in token_txs:
        contract = row.get("contractAddress", "").lower()
        if not contract:
            continue

        if contract not in balances:
            balances[contract] = 0
            symbols[contract] = row.get("tokenSymbol", "")
            raw_decimals = row.get("tokenDecimal")
            decimals_map[contract] = int(raw_decimals) if raw_decimals is not None and str(raw_decimals).strip() != "" else 18
        else:
            if not symbols[contract] and row.get("tokenSymbol"):
                symbols[contract] = row.get("tokenSymbol")

        val = int(row.get("value", 0))
        frm = row.get("from", "").lower()
        to = row.get("to", "").lower()

        if to == w:
            balances[contract] += val
        if frm == w:
            balances[contract] -= val

    return {
        c: TokenBalance(
            contract=c,
            symbol=symbols[c],
            decimals=decimals_map[c],
            raw=balances[c],
        )
        for c in balances
    }
