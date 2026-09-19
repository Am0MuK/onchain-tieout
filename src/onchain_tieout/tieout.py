from dataclasses import dataclass
from decimal import Decimal
from onchain_tieout.diagnose import diagnose, WETH_BY_CHAIN
from onchain_tieout.reconstruct import native_balance, token_balances, TokenBalance
from onchain_tieout.rpc import ContractCallError


@dataclass(frozen=True)
class Row:
    kind: str            # "native" | "erc20"
    contract: str | None
    symbol: str
    decimals: int
    computed: int
    actual: int | None   # None when read failed
    status: str          # "OK" | "MISMATCH" | "READ_FAILED"
    label: str | None    # None when OK
    explained: bool


@dataclass(frozen=True)
class Report:
    wallet: str
    chain_id: int
    block: int
    rows: list[Row]

    @property
    def ok(self) -> bool:
        return all(r.status == "OK" for r in self.rows)


def _compare(*, kind, contract, symbol, decimals, computed, read_actual, dust, diagnose_delta) -> Row:
    """Read the on-chain balance and build one tie-out row."""
    base = dict(kind=kind, contract=contract, symbol=symbol, decimals=decimals, computed=computed)
    try:
        actual = read_actual()
    except ContractCallError:
        return Row(**base, actual=None, status="READ_FAILED",
                   label="balance_read_failed", explained=False)

    delta = actual - computed
    if abs(delta) <= int(dust * Decimal(10**decimals)):
        return Row(**base, actual=actual, status="OK", label=None, explained=False)

    label, explained = diagnose_delta(delta)
    return Row(**base, actual=actual, status="MISMATCH", label=label, explained=explained)


def run_tieout(
    wallet: str,
    chain_id: int,
    explorer,
    rpc,
    block: int | None = None,
    dust_units: str | float = "0.000000001",
    tokens: list[str] | None = None,
) -> Report:
    """Tie out one wallet at one block.

    ``tokens`` limits the ERC-20 check to these contracts (the native balance is
    always checked). A listed token that never appears in history is still read,
    with a computed balance of 0, so a gap in history cannot pass silently.
    """
    if block is None:
        block = rpc.block_number() - 64

    # Fetch history
    txs = explorer.fetch_all("txlist", wallet, chain_id, block)
    internals = explorer.fetch_all("txlistinternal", wallet, chain_id, block)
    token_txs = explorer.fetch_all("tokentx", wallet, chain_id, block)

    # Reconstruct balances
    computed_native = native_balance(wallet, txs, internals)
    reconstructed = token_balances(wallet, token_txs)

    # If chain's WETH was interacted with in txlist, ensure WETH is checked even if not in tokentx
    weth_contract = WETH_BY_CHAIN.get(chain_id, "").lower()
    if weth_contract and weth_contract not in reconstructed:
        has_weth_tx = any(t.get("to", "").lower() == weth_contract for t in txs)
        if has_weth_tx:
            reconstructed[weth_contract] = TokenBalance(
                contract=weth_contract,
                symbol="WETH",
                decimals=18,
                raw=0,
            )

    if tokens is not None:
        wanted = [t.lower() for t in tokens]
        selected = {}
        for c in wanted:
            if c in reconstructed:
                selected[c] = reconstructed[c]
            else:
                try:
                    decimals = rpc.erc20_decimals(c, block)
                except ContractCallError:
                    decimals = 0  # unknown: show raw units rather than guess a scale
                selected[c] = TokenBalance(contract=c, symbol="?", decimals=decimals, raw=0)
        reconstructed = selected

    dust = Decimal(str(dust_units))

    def read_native() -> int:
        return rpc.get_balance(wallet, block)

    native_row = _compare(
        kind="native", contract=None, symbol="ETH", decimals=18,
        computed=computed_native, read_actual=read_native, dust=dust,
        diagnose_delta=lambda delta: ("unexplained", False),
    )

    token_rows: list[Row] = []
    for token in reconstructed.values():
        token_rows.append(_compare(
            kind="erc20", contract=token.contract, symbol=token.symbol,
            decimals=token.decimals, computed=token.raw,
            read_actual=lambda t=token: rpc.erc20_balance(t.contract, wallet, block),
            dust=dust,
            diagnose_delta=lambda delta, t=token: diagnose(chain_id, wallet, t.contract, delta, txs, computed=t.raw),
        ))

    token_rows.sort(key=lambda r: (r.symbol.upper(), r.contract or ""))
    all_rows = [native_row] + token_rows

    return Report(
        wallet=wallet,
        chain_id=chain_id,
        block=block,
        rows=all_rows,
    )
