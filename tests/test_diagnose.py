from onchain_tieout.diagnose import diagnose, WETH_BY_CHAIN, REBASING
from tests.conftest import WALLET, OTHER, WETH, USDC


def call(to, selector, value="0", frm=WALLET, is_error="0"):
    return {"from": frm, "to": to, "input": selector + "00" * 32, "value": value,
            "isError": is_error, "txreceipt_status": "1"}


def test_weth_deposit_and_withdraw_explain_delta():
    txs = [call(WETH, "0xd0e30db0", value=str(3 * 10**18)),   # deposit 3 WETH
           {"from": WALLET, "to": WETH, "value": "0", "isError": "0", "txreceipt_status": "1",
            "input": "0x2e1a7d4d" + hex(10**18)[2:].rjust(64, "0")}]  # withdraw 1 WETH
    label, explained = diagnose(chain_id=1, wallet=WALLET, contract=WETH, delta=2 * 10**18, txs=txs)
    assert label == "weth_wrap_unwrap_untracked"
    assert explained is True


def test_weth_label_but_not_fully_explained():
    txs = [call(WETH, "0xd0e30db0", value="5")]
    label, explained = diagnose(1, WALLET, WETH, delta=7, txs=txs)
    assert label == "weth_wrap_unwrap_untracked"
    assert explained is False


def test_reverted_weth_calls_ignored():
    txs = [call(WETH, "0xd0e30db0", value="5", is_error="1")]
    assert diagnose(1, WALLET, WETH, delta=5, txs=txs) == ("unexplained", False)


def test_rebasing():
    assert diagnose(1, WALLET, REBASING[1][0], delta=123, txs=[]) == ("rebasing_token", False)


def test_unexplained():
    assert diagnose(1, WALLET, USDC, delta=1, txs=[]) == ("unexplained", False)


def test_negative_history_on_ordinary_token():
    # History says the wallet sent more than it ever received: impossible for a
    # standard ERC-20, typical of spam tokens that emit fake Transfer events.
    assert diagnose(1, WALLET, USDC, delta=500, txs=[], computed=-500) == ("negative_history", False)


def test_negative_weth_history_stays_weth_label():
    # WETH legitimately goes negative in transfer history when the wallet unwraps.
    txs = [call(WETH, "0xd0e30db0", value="5")]
    label, _ = diagnose(1, WALLET, WETH, delta=5, txs=txs, computed=-5)
    assert label == "weth_wrap_unwrap_untracked"
