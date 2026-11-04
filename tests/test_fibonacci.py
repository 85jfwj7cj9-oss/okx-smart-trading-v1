
import numpy as np
import pandas as pd
import pytest

from fibonacci import FibonacciEngine


def make_data():
    close = [
        10, 11, 13, 15, 14, 12, 10, 11,
        13, 16, 18, 17, 15, 13, 11, 12,
        14, 16, 15, 13
    ]

    return pd.DataFrame({
        "high": [x + 1 for x in close],
        "low": [x - 1 for x in close],
        "close": close
    })


def test_validate_data():
    result = FibonacciEngine.validate_data(make_data())
    assert len(result) == 20


def test_validate_missing_column():
    df = make_data().drop(columns=["high"])

    with pytest.raises(ValueError):
        FibonacciEngine.validate_data(df)


def test_validate_invalid_price():
    df = make_data()
    df.loc[0, "high"] = 1

    with pytest.raises(ValueError):
        FibonacciEngine.validate_data(df)


def test_find_swings():
    result = FibonacciEngine.find_swings(
        make_data(), left=2, right=2
    )

    assert "swing_highs" in result
    assert "swing_lows" in result
    assert len(result["swing_highs"]) > 0
    assert len(result["swing_lows"]) > 0


def test_swing_confirmation_position():
    df = make_data()

    result = FibonacciEngine.find_swings(
        df, left=2, right=2
    )

    for swing in result["swing_highs"]:
        assert (
            swing["confirmed_position"]
            == swing["position"] + 2
        )

    for swing in result["swing_lows"]:
        assert (
            swing["confirmed_position"]
            == swing["position"] + 2
        )


def test_bullish_retracement():
    result = FibonacciEngine.calculate_retracement(
        100, 200
    )

    assert result[0.382] == pytest.approx(161.8)
    assert result[0.5] == pytest.approx(150)
    assert result[0.618] == pytest.approx(138.2)
    assert result[0.786] == pytest.approx(121.4)


def test_bearish_retracement():
    result = FibonacciEngine.calculate_bearish_retracement(
        200, 100
    )

    assert result[0.382] == pytest.approx(138.2)
    assert result[0.5] == pytest.approx(150)
    assert result[0.618] == pytest.approx(161.8)
    assert result[0.786] == pytest.approx(178.6)


def test_bullish_extension():
    result = FibonacciEngine.calculate_extension(
        100, 200
    )

    assert result[1.272] == pytest.approx(227.2)
    assert result[1.618] == pytest.approx(261.8)


def test_bearish_extension():
    result = FibonacciEngine.calculate_bearish_extension(
        200, 100
    )

    assert result[1.272] == pytest.approx(72.8)
    assert result[1.618] == pytest.approx(38.2)


def test_invalid_swing_prices():
    with pytest.raises(ValueError):
        FibonacciEngine.calculate_retracement(200, 100)

    with pytest.raises(ValueError):
        FibonacciEngine.calculate_extension(100, 100)


def test_analyze_structure():
    result = FibonacciEngine.analyze(
        make_data(), left=2, right=2
    )

    assert "current_price" in result
    assert "swings" in result
    assert "bullish" in result
    assert "bearish" in result


def test_invalid_period():
    with pytest.raises(ValueError):
        FibonacciEngine.find_swings(
            make_data(), left=0, right=2
        )


def test_unsorted_datetime_index():
    df = make_data()
    df.index = pd.date_range(
        "2026-01-01", periods=len(df), freq="h"
    )
    df = df.iloc[::-1]

    with pytest.raises(ValueError):
        FibonacciEngine.validate_data(df)
