from dataclasses import dataclass
from decimal import Decimal
from onchain_tieout.diagnose import diagnose, WETH_BY_CHAIN
from onchain_tieout.reconstruct import native_balance, token_balances, TokenBalance
from onchain_tieout.rpc import RpcError


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


def run_tieout(
    wallet: str,
    chain_id: int,
    explorer,
    rpc,
    block: int | None = None,
    dust_units: str | float = "0.000000001",
) -> Report:
    w = wallet.lower()
    if block is None:
        block = rpc.block_number() - 64

    # Fetch history
    txs = explorer.fetch_all("txlist", wallet, chain_id, block)
    internals = explorer.fetch_all("txlistinternal", wallet, chain_id, block)
    token_txs = explorer.fetch_all("tokentx", wallet, chain_id, block)

    # Reconstruct balances
    computed_native = native_balance(wallet, txs, internals)
    tokens = token_balances(wallet, token_txs)

    # If chain's WETH was interacted with in txlist, ensure WETH is checked even if not in tokentx
    weth_contract = WETH_BY_CHAIN.get(chain_id, "").lower()
    if weth_contract and weth_contract not in tokens:
        has_weth_tx = any(t.get("to", "").lower() == weth_contract for t in txs)
        if has_weth_tx:
            tokens[weth_contract] = TokenBalance(
                contract=weth_contract,
                symbol="WETH",
                decimals=18,
                raw=0,
            )

    dust_dec = Decimal(str(dust_units))

    # Native balance check
    native_dust_raw = int(dust_dec * Decimal(10**18))
    try:
        actual_native = rpc.get_balance(wallet, block)
        delta_native = actual_native - computed_native
        if abs(delta_native) <= native_dust_raw:
            native_row = Row(
                kind="native",
                contract=None,
                symbol="ETH",
                decimals=18,
                computed=computed_native,
                actual=actual_native,
                status="OK",
                label=None,
                explained=False,
            )
        else:
            native_row = Row(
                kind="native",
                contract=None,
                symbol="ETH",
                decimals=18,
                computed=computed_native,
                actual=actual_native,
                status="MISMATCH",
                label="unexplained",
                explained=False,
            )
    except RpcError:
        native_row = Row(
            kind="native",
            contract=None,
            symbol="ETH",
            decimals=18,
            computed=computed_native,
            actual=None,
            status="READ_FAILED",
            label="balance_read_failed",
            explained=False,
        )

    # Token rows
    token_rows: list[Row] = []
    for token in tokens.values():
        token_dust_raw = int(dust_dec * Decimal(10**token.decimals))
        try:
            actual = rpc.erc20_balance(token.contract, wallet, block)
            delta = actual - token.raw
            if abs(delta) <= token_dust_raw:
                token_rows.append(
                    Row(
                        kind="erc20",
                        contract=token.contract,
                        symbol=token.symbol,
                        decimals=token.decimals,
                        computed=token.raw,
                        actual=actual,
                        status="OK",
                        label=None,
                        explained=False,
                    )
                )
            else:
                label, explained = diagnose(chain_id, wallet, token.contract, delta, txs)
                token_rows.append(
                    Row(
                        kind="erc20",
                        contract=token.contract,
                        symbol=token.symbol,
                        decimals=token.decimals,
                        computed=token.raw,
                        actual=actual,
                        status="MISMATCH",
                        label=label,
                        explained=explained,
                    )
                )
        except RpcError:
            token_rows.append(
                Row(
                    kind="erc20",
                    contract=token.contract,
                    symbol=token.symbol,
                    decimals=token.decimals,
                    computed=token.raw,
                    actual=None,
                    status="READ_FAILED",
                    label="balance_read_failed",
                    explained=False,
                )
            )

    token_rows.sort(key=lambda r: (r.symbol.upper(), r.contract or ""))
    all_rows = [native_row] + token_rows

    return Report(
        wallet=wallet,
        chain_id=chain_id,
        block=block,
        rows=all_rows,
    )
