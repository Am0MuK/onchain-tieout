import json
from decimal import Decimal
from onchain_tieout.tieout import Report, Row


def _format_amount(raw: int | None, decimals: int) -> str:
    if raw is None:
        return "N/A"
    return str(Decimal(raw) / Decimal(10**decimals))


def render_text(report: Report) -> str:
    lines = []
    lines.append(f"wallet: {report.wallet} / chain: {report.chain_id} / block: {report.block}")

    # Prepare table headers and rows
    headers = ["SYMBOL", "CONTRACT", "COMPUTED", "ACTUAL", "DELTA", "STATUS", "LABEL"]
    table_rows = []

    for r in report.rows:
        sym = r.symbol or ""
        contract = r.contract or "-"
        computed_str = _format_amount(r.computed, r.decimals)
        actual_str = _format_amount(r.actual, r.decimals)
        if r.actual is not None:
            delta_str = _format_amount(r.actual - r.computed, r.decimals)
        else:
            delta_str = "N/A"
        status = r.status
        label = r.label or "-"
        table_rows.append([sym, contract, computed_str, actual_str, delta_str, status, label])

    # Compute column widths
    col_widths = [len(h) for h in headers]
    for row in table_rows:
        for idx, cell in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(cell))

    # Format header line
    header_line = "  ".join(f"{h:<{w}}" for h, w in zip(headers, col_widths))
    sep_line = "  ".join("-" * w for w in col_widths)
    lines.append(header_line)
    lines.append(sep_line)

    for row in table_rows:
        lines.append("  ".join(f"{cell:<{w}}" for cell, w in zip(row, col_widths)))

    # Final summary line
    if report.ok:
        lines.append("OK: all balances tie out")
    else:
        mismatches = sum(1 for r in report.rows if r.status != "OK")
        lines.append(f"FAIL: {mismatches} of {len(report.rows)} rows do not tie out")

    return "\n".join(lines)


def render_json(report: Report) -> str:
    row_dicts = []
    for r in report.rows:
        computed_str = _format_amount(r.computed, r.decimals)
        if r.actual is not None:
            actual_str = _format_amount(r.actual, r.decimals)
            delta_str = _format_amount(r.actual - r.computed, r.decimals)
        else:
            actual_str = None
            delta_str = None

        row_dicts.append(
            {
                "kind": r.kind,
                "contract": r.contract,
                "symbol": r.symbol,
                "decimals": r.decimals,
                "computed": computed_str,
                "actual": actual_str,
                "delta": delta_str,
                "status": r.status,
                "label": r.label,
                "explained": r.explained,
            }
        )

    data = {
        "wallet": report.wallet,
        "chain_id": report.chain_id,
        "block": report.block,
        "ok": report.ok,
        "rows": row_dicts,
    }
    return json.dumps(data, indent=2)
