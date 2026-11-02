
import pytest

from market_data import MarketData


def make_candle(timestamp, close):
    return {
        "timestamp": timestamp,
        "close": close
    }


def test_calculate_return():
    candles = [
        make_candle(i, 100 + i)
        for i in range(21)
    ]

    result = MarketData.calculate_return(
        candles,
        lookback=20
    )

    expected = (120 / 100 - 1) * 100

    assert result == pytest.approx(expected)


def test_calculate_return_insufficient_data():
    candles = [
        make_candle(i, 100 + i)
        for i in range(10)
    ]

    result = MarketData.calculate_return(
        candles,
        lookback=20
    )

    assert result is None


def test_calculate_return_invalid_price():
    candles = [
        make_candle(i, 0 if i == 0 else 100 + i)
        for i in range(21)
    ]

    result = MarketData.calculate_return(
        candles,
        lookback=20
    )

    assert result is None


def test_align_candles():
    asset = [
        make_candle(1, 100),
        make_candle(2, 110),
        make_candle(3, 120)
    ]

    btc = [
        make_candle(2, 50000),
        make_candle(3, 51000),
        make_candle(4, 52000)
    ]

    result = MarketData.align_candles(
        asset,
        btc
    )

    assert len(result) == 2
    assert result[0][0]["timestamp"] == 2
    assert result[1][0]["timestamp"] == 3


def test_calculate_relative_strength():
    asset = [
        make_candle(i, 100)
        for i in range(21)
    ]

    btc = [
        make_candle(i, 100)
        for i in range(21)
    ]

    asset[-1]["close"] = 120
    btc[-1]["close"] = 110

    market = MarketData()

    result = market.calculate_relative_strength(
        asset,
        btc,
        lookback=20
    )

    assert result is not None
    assert result["asset_return_pct"] == pytest.approx(20)
    assert result["btc_return_pct"] == pytest.approx(10)
    assert result["relative_strength_pct"] == pytest.approx(10)


def test_relative_strength_insufficient_data():
    asset = [
        make_candle(i, 100)
        for i in range(10)
    ]

    btc = [
        make_candle(i, 100)
        for i in range(10)
    ]

    market = MarketData()

    result = market.calculate_relative_strength(
        asset,
        btc,
        lookback=20
    )

    assert result is None


def test_relative_strength_zero_price():
    asset = [
        make_candle(i, 100)
        for i in range(21)
    ]

    btc = [
        make_candle(i, 100)
        for i in range(21)
    ]

    asset[0]["close"] = 0

    market = MarketData()

    result = market.calculate_relative_strength(
        asset,
        btc,
        lookback=20
    )

    assert result is None
