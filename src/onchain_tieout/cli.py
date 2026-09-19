import argparse
import os
import re
import sys
import httpx
from onchain_tieout.explorer import EtherscanClient, ExplorerError, redact
from onchain_tieout.report import render_json, render_text
from onchain_tieout.rpc import RpcClient, RpcError
from onchain_tieout.tieout import run_tieout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tieout",
        description="Tie out an EVM wallet's reconstructed balances against on-chain state",
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    check_parser = subparsers.add_parser("check", help="Check balances for a wallet")
    check_parser.add_argument("wallet", help="EOA wallet address (0x + 40 hex chars)")
    check_parser.add_argument("--chain", type=int, default=1, help="Chain ID (default: 1)")
    check_parser.add_argument("--block", type=int, default=None, help="Block number (default: head - 64)")
    check_parser.add_argument("--rpc", default=None, help="RPC URL (or set TIEOUT_RPC_URL env)")
    check_parser.add_argument("--json", action="store_true", help="Output report in JSON format")
    check_parser.add_argument("--dust", default="0.000000001", help="Dust tolerance in token units (default: 1e-9)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.subcommand != "check":
        parser.print_help(sys.stderr)
        return 2

    # Validate wallet
    wallet = args.wallet.strip()
    if not re.match(r"^0x[0-9a-fA-F]{40}$", wallet):
        sys.stderr.write(f"Error: Invalid wallet address: {wallet}\n")
        return 2

    # Validate API key
    api_key = os.environ.get("ETHERSCAN_API_KEY", "").strip()
    if not api_key:
        sys.stderr.write("Error: ETHERSCAN_API_KEY environment variable is required\n")
        return 2

    # Validate RPC URL
    rpc_url = (args.rpc or os.environ.get("TIEOUT_RPC_URL") or "").strip()
    if not rpc_url:
        sys.stderr.write("Error: RPC URL is required (pass --rpc or set TIEOUT_RPC_URL)\n")
        return 2

    with httpx.Client() as http:
        explorer = EtherscanClient(api_key=api_key, http=http)
        rpc = RpcClient(url=rpc_url, http=http)

        try:
            report = run_tieout(
                wallet=wallet,
                chain_id=args.chain,
                explorer=explorer,
                rpc=rpc,
                block=args.block,
                dust_units=args.dust,
            )
        except ExplorerError as exc:
            msg = redact(str(exc))
            if api_key in msg:
                msg = msg.replace(api_key, "***")
            sys.stderr.write(f"Error: {msg}\n")
            return 2
        except RpcError as exc:
            msg = redact(str(exc))
            if api_key in msg:
                msg = msg.replace(api_key, "***")
            sys.stderr.write(f"Error: {msg}\n")
            return 2
        except Exception as exc:
            msg = redact(str(exc))
            if api_key in msg:
                msg = msg.replace(api_key, "***")
            sys.stderr.write(f"Error: {msg}\n")
            return 2

    if args.json:
        sys.stdout.write(render_json(report) + "\n")
    else:
        sys.stdout.write(render_text(report) + "\n")

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
