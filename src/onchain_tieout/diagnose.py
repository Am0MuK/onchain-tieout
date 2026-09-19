WETH_BY_CHAIN = {
    1: "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
}

REBASING = {
    1: ["0xae7ab96520de3a18e5e111b5eaab095312d7fe84"],
}


def _is_reverted(tx: dict) -> bool:
    return tx.get("isError") == "1" or tx.get("txreceipt_status") == "0"


def diagnose(
    chain_id: int,
    wallet: str,
    contract: str | None,
    delta: int,
    txs: list[dict],
) -> tuple[str, bool]:
    w = wallet.lower()
    c = contract.lower() if contract else None

    # Check WETH
    weth_address = WETH_BY_CHAIN.get(chain_id, "").lower()
    if c and weth_address and c == weth_address:
        deposits = 0
        withdrawals = 0
        found_weth_tx = False

        for t in txs:
            if _is_reverted(t):
                continue
            if t.get("from", "").lower() != w:
                continue
            if t.get("to", "").lower() != c:
                continue

            inp = t.get("input", "").lower()
            if inp.startswith("0xd0e30db0"):
                found_weth_tx = True
                deposits += int(t.get("value", 0))
            elif inp.startswith("0x2e1a7d4d"):
                found_weth_tx = True
                if len(inp) >= 74:
                    withdrawals += int(inp[10:74], 16)

        if found_weth_tx:
            explained = (deposits - withdrawals) == delta
            return ("weth_wrap_unwrap_untracked", explained)

    # Check Rebasing
    rebasing_list = [addr.lower() for addr in REBASING.get(chain_id, [])]
    if c and c in rebasing_list:
        return ("rebasing_token", False)

    return ("unexplained", False)
