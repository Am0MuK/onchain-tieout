from onchain_tieout.reconstruct import native_balance, token_balances
from tests.conftest import WALLET, OTHER, USDC


def tx(frm, to, value, gas_used=21000, gas_price=10, is_error="0", receipt="1"):
    return {"from": frm, "to": to, "value": str(value), "gasUsed": str(gas_used),
            "gasPrice": str(gas_price), "isError": is_error, "txreceipt_status": receipt}


def test_incoming_and_outgoing_with_gas():
    txs = [tx(OTHER, WALLET, 1000), tx(WALLET, OTHER, 300)]
    assert native_balance(WALLET, txs, []) == 1000 - 300 - 21000 * 10


def test_reverted_tx_value_ignored_gas_kept():
    txs = [tx(OTHER, WALLET, 10**18), tx(WALLET, OTHER, 5 * 10**17, is_error="1")]
    assert native_balance(WALLET, txs, []) == 10**18 - 21000 * 10


def test_receipt_status_zero_also_counts_as_reverted():
    txs = [tx(OTHER, WALLET, 100), tx(WALLET, OTHER, 50, is_error="0", receipt="0")]
    assert native_balance(WALLET, txs, []) == 100 - 21000 * 10


def test_incoming_tx_gas_is_not_charged_to_wallet():
    txs = [tx(OTHER, WALLET, 100, gas_used=50000, gas_price=99)]
    assert native_balance(WALLET, txs, []) == 100


def test_internal_transfers_counted_and_failed_internal_ignored():
    internals = [{"from": OTHER, "to": WALLET, "value": "700", "isError": "0"},
                 {"from": OTHER, "to": WALLET, "value": "999", "isError": "1"}]
    assert native_balance(WALLET, [], internals) == 700


def test_address_case_insensitive():
    txs = [tx(OTHER.upper().replace("0X", "0x"), WALLET.upper().replace("0X", "0x"), 5)]
    assert native_balance(WALLET, txs, []) == 5
