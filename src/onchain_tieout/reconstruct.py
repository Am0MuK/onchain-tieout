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


def token_balances(wallet: str, token_txs: list[dict]):
    raise NotImplementedError
