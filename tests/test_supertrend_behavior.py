
import pandas as pd

from indicators import IndicatorEngine


def make_trend_data():
    """
    建立可重現的測試行情：
    1. 前段橫盤
    2. 中段強勢上漲
    3. 後段明顯下跌
    """
    close = (
        [100.0] * 8
        + [105.0, 112.0, 120.0, 130.0, 140.0, 150.0]
        + [150.0] * 4
        + [140.0, 130.0, 120.0, 110.0, 100.0, 90.0, 80.0]
    )

    df = pd.DataFrame({
        "open": close,
        "high": [price + 1.0 for price in close],
        "low": [price - 1.0 for price in close],
        "close": close,
        "volume": [1000.0] * len(close),
    })

    return df


def test_supertrend_detects_bullish_and_bearish_trends():
    df = make_trend_data()

    result = IndicatorEngine.supertrend(
        df,
        period=3,
        multiplier=1.0,
    )

    directions = result["supertrend_direction"]

    assert 1 in directions.values
    assert -1 in directions.values

    valid_directions = directions[directions != 0]
    assert len(valid_directions) > 0

    assert (valid_directions.diff().abs() == 2).any()


def test_supertrend_line_is_valid_when_direction_is_active():
    df = make_trend_data()

    result = IndicatorEngine.supertrend(
        df,
        period=3,
        multiplier=1.0,
    )

    active = result["supertrend_direction"] != 0

    assert active.any()
    assert result.loc[active, "supertrend"].notna().all()


def test_supertrend_does_not_change_past_values():
    df = make_trend_data()

    original = IndicatorEngine.supertrend(
        df,
        period=3,
        multiplier=1.0,
    )

    extended_df = pd.concat(
        [
            df,
            pd.DataFrame({
                "open": [60.0, 50.0, 40.0],
                "high": [61.0, 51.0, 41.0],
                "low": [59.0, 49.0, 39.0],
                "close": [60.0, 50.0, 40.0],
                "volume": [1000.0] * 3,
            }),
        ],
        ignore_index=True,
    )

    extended = IndicatorEngine.supertrend(
        extended_df,
        period=3,
        multiplier=1.0,
    )

    pd.testing.assert_series_equal(
        original["supertrend"],
        extended["supertrend"].iloc[:len(df)].reset_index(drop=True),
        check_names=False,
    )

    pd.testing.assert_series_equal(
        original["supertrend_direction"],
        extended["supertrend_direction"].iloc[:len(df)].reset_index(drop=True),
        check_names=False,
    )
