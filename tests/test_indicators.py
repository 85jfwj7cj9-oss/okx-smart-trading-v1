
import numpy as np
import pandas as pd
import pytest

from indicators import IndicatorEngine


def make_data(rows=250):
    x = np.arange(rows)

    close = (
        100
        + x * 0.15
        + 3 * np.sin(x / 8)
    )

    return pd.DataFrame({
        "open": close - 0.2,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1000 + x * 2
    })


def test_validate_data():
    df = make_data()
    result = IndicatorEngine.validate_data(df)

    assert len(result) == 250
    assert "close" in result.columns


def test_validate_missing_column():
    df = make_data().drop(columns=["volume"])

    with pytest.raises(ValueError):
        IndicatorEngine.validate_data(df)


def test_validate_invalid_price():
    df = make_data()
    df.loc[0, "high"] = 1

    with pytest.raises(ValueError):
        IndicatorEngine.validate_data(df)


def test_ema():
    df = make_data()
    result = IndicatorEngine.ema(df["close"], 20)

    assert len(result) == len(df)
    assert result.notna().any()


def test_rsi():
    df = make_data()
    result = IndicatorEngine.rsi(df["close"])

    valid = result.dropna()

    assert len(valid) > 0
    assert ((valid >= 0) & (valid <= 100)).all()


def test_macd():
    df = make_data()
    result = IndicatorEngine.macd(df["close"])

    assert "macd" in result.columns
    assert "macd_signal" in result.columns
    assert "macd_hist" in result.columns


def test_atr():
    df = make_data()
    result = IndicatorEngine.atr(df)

    assert result.dropna().gt(0).all()


def test_dmi_adx():
    df = make_data()
    result = IndicatorEngine.dmi_adx(df)

    assert "plus_di" in result.columns
    assert "minus_di" in result.columns
    assert "adx" in result.columns

    valid = result["adx"].dropna()
    assert ((valid >= 0) & (valid <= 100)).all()


def test_bollinger_bands():
    df = make_data()
    result = IndicatorEngine.bollinger_bands(df["close"])

    assert "bb_upper" in result.columns
    assert "bb_middle" in result.columns
    assert "bb_lower" in result.columns

    valid = result.dropna()

    assert (valid["bb_upper"] >= valid["bb_middle"]).all()
    assert (valid["bb_middle"] >= valid["bb_lower"]).all()


def test_obv():
    df = make_data()

    result = IndicatorEngine.obv(
        df["close"], df["volume"]
    )

    assert len(result) == len(df)
    assert result.notna().all()


def test_supertrend():
    df = make_data()
    result = IndicatorEngine.supertrend(df)

    assert "supertrend" in result.columns
    assert "supertrend_direction" in result.columns

    directions = set(
        result["supertrend_direction"].unique()
    )

    assert directions.issubset({-1, 0, 1})


def test_calculate_all():
    df = make_data()
    result = IndicatorEngine.calculate_all(df)

    expected_columns = [
        "ema_7",
        "ema_20",
        "ema_50",
        "ema_100",
        "ema_200",
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_hist",
        "atr_14",
        "plus_di",
        "minus_di",
        "adx",
        "bb_upper",
        "bb_middle",
        "bb_lower",
        "obv",
        "volume_ma_20",
        "supertrend",
        "supertrend_direction"
    ]

    for column in expected_columns:
        assert column in result.columns

    assert len(result) == len(df)


# ==========================================
# Supertrend additional validation tests
# ==========================================

def test_supertrend_atr_warmup():
    """ATR 尚未形成前，不應產生有效 Supertrend。"""
    df = make_data(rows=50)

    result = IndicatorEngine.supertrend(
        df,
        period=10,
        multiplier=3.0
    )

    # ATR 第 10 個有效資料位於索引 9
    assert result["supertrend"].iloc[:9].isna().all()
    assert result["supertrend"].iloc[9:].notna().any()

    # ATR 初始化前，趨勢方向應為 0
    assert (
        result["supertrend_direction"].iloc[:9] == 0
    ).all()


def test_supertrend_no_future_data_leakage():
    """加入未來 K 線，不應改變過去已計算的結果。"""
    df = make_data(rows=100)

    original = IndicatorEngine.supertrend(
        df,
        period=10,
        multiplier=3.0
    )

    future_df = make_data(rows=30).copy()

    future_df["open"] += 100
    future_df["high"] += 100
    future_df["low"] += 100
    future_df["close"] += 100

    extended_df = pd.concat(
        [df, future_df],
        ignore_index=True
    )

    extended = IndicatorEngine.supertrend(
        extended_df,
        period=10,
        multiplier=3.0
    )

    pd.testing.assert_series_equal(
        original["supertrend"],
        extended["supertrend"].iloc[:len(df)].reset_index(drop=True),
        check_names=False
    )

    pd.testing.assert_series_equal(
        original["supertrend_direction"],
        extended["supertrend_direction"].iloc[:len(df)].reset_index(drop=True),
        check_names=False
    )


def test_supertrend_direction_values():
    """Supertrend 方向只能是多方、空方或初始化狀態。"""
    df = make_data(rows=250)
    result = IndicatorEngine.supertrend(df)

    assert result["supertrend_direction"].isin(
        [-1, 0, 1]
    ).all()

    assert result["supertrend"].dropna().notna().all()
