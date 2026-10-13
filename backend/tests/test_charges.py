from decimal import Decimal as D

import pytest

from app.ledger.charges import estimate


@pytest.mark.parametrize(
    ("broker", "side", "value", "expected"),
    [
        # STT 10 + exchange 0.307 + SEBI 0.01 + stamp 1.5 + GST 18% of 0.317.
        ("zerodha", "buy", "10000", "11.87"),
        # STT 10 + exchange 0.307 + SEBI 0.01 + DP 13 + GST 18% of 13.317.
        ("zerodha", "sell", "10000", "25.71"),
        # Brokerage 10 (0.1%) + STT 10 + exchange 0.297 + SEBI 0.01 + stamp 1.5 + GST of 10.307.
        ("groww", "buy", "10000", "23.66"),
        # Brokerage capped at 20: (20 + 1.485 + 0.05 + DP 20) x 1.18 + STT 50.
        ("groww", "sell", "50000", "99.01"),
        # Brokerage floor 5 (0.1% would be 1): (5 + 0.0297 + 0.001) x 1.18 + STT 1 + stamp 0.15.
        ("groww", "buy", "1000", "7.09"),
    ],
)
def test_estimate(broker, side, value, expected):
    assert estimate(broker, side, D(value)) == D(expected)


@pytest.mark.parametrize(
    ("amount", "text"),
    [("133381.63", "₹1,33,381.63"), ("-1940.45", "-₹1,940.45"), ("547", "₹547.00"),
     ("12345678.9", "₹1,23,45,678.90")],
)  # fmt: skip
def test_inr_uses_lakh_grouping(amount, text):
    from app.ledger.summary import inr

    assert inr(D(amount)) == text
