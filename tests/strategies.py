
import pandas as pd

from strategy import StrategyEngine


def make_features(**overrides):
    features = {
        "close": 105.0,
        "previous_close": 103.0,
        "ema7": 104.0,
        "ema20": 102.0,
        "ema50": 100.0,
        "ema100": 98.0,
        "ema200": 95.0,
        "rsi": 58.0,
        "macd": 2.0,
        "macd_signal": 1.0,
        "macd_hist": 1.0,
        "previous_hist": 0.5,
        "adx": 25.0,
        "plus_di": 30.0,
        "minus_di": 15.0,
        "volume": 2000.0,
        "volume_ma": 1000.0,
        "high": 106.0,
        "low": 104.0,
        "atr": 2.0,
        "supertrend_direction": 1.0,
        "obv": 5000.0,
        "previous_obv": 4500.0,
        "bb_upper": 110.0,
        "bb_middle": 102.0,
        "bb_lower": 94.0,
        "bb_bandwidth": 0.15,
        "previous_bb_bandwidth": 0.12,
    }
    features.update(overrides)
    return features


def make_breakout_df():
    return pd.DataFrame({
        "high": [101.0, 102.0, 103.0, 104.0, 105.0],
        "low": [98.0, 99.0, 100.0, 101.0, 102.0],
        "close": [100.0, 101.0, 102.0, 103.0, 105.0],
    })


def make_breakdown_df():
    return pd.DataFrame({
        "high": [105.0, 104.0, 103.0, 102.0, 101.0],
        "low": [102.0, 101.0, 100.0, 99.0, 98.0],
        "close": [104.0, 103.0, 102.0, 101.0, 98.0],
    })


def test_long_and_short_relative_strength_are_opposite():
    engine = StrategyEngine()

    long_adjustment, _ = engine._relative_strength_adjustment(3.0, "LONG")
    short_adjustment, _ = engine._relative_strength_adjustment(3.0, "SHORT")

    assert long_adjustment > 0
    assert short_adjustment < 0


def test_early_long_requires_improving_momentum():
    engine = StrategyEngine()

    features = make_features(
        close=101.0,
        ema7=100.5,
        ema20=100.0,
        ema50=99.0,
        rsi=55.0,
        macd_hist=0.8,
        previous_hist=0.5,
    )

    assert engine._early_long(features) is True

    features["macd_hist"] = 0.3
    assert engine._early_long(features) is False


def test_early_short_requires_declining_momentum():
    engine = StrategyEngine()

    features = make_features(
        close=99.0,
        ema7=99.5,
        ema20=100.0,
        ema50=101.0,
        rsi=45.0,
        macd_hist=-0.8,
        previous_hist=-0.5,
    )

    assert engine._early_short(features) is True

    features["macd_hist"] = -0.3
    assert engine._early_short(features) is False


def test_breakout_long_requires_volume_confirmation():
    engine = StrategyEngine(breakout_lookback=3)
    df = make_breakout_df()

    features = make_features(
        close=105.0,
        ema7=104.0,
        ema20=102.0,
        macd_hist=1.0,
        previous_hist=0.5,
        volume=900.0,
        volume_ma=1000.0,
    )

    assert engine._breakout_long(features, df) is False


def test_breakdown_short_requires_volume_confirmation():
    engine = StrategyEngine(breakout_lookback=3)
    df = make_breakdown_df()

    features = make_features(
        close=98.0,
        ema7=99.0,
        ema20=100.0,
        macd_hist=-1.0,
        previous_hist=-0.5,
        volume=900.0,
        volume_ma=1000.0,
    )

    assert engine._breakdown_short(features, df) is False


def test_timeframe_weighting_uses_65_35():
    assert StrategyEngine._weighted_score(80, 60) == 73


def test_supertrend_confirmation_penalizes_opposite_direction():
    features = make_features(supertrend_direction=-1)

    points, reasons = StrategyEngine._optional_confirmation(
        features, "LONG"
    )

    assert any("衝突" in reason for reason in reasons)
    assert points < 0


def test_opposite_timeframes_receive_penalty():
    engine = StrategyEngine()

    bearish = make_features(
        ema7=99,
        ema20=100,
        plus_di=10,
        minus_di=30,
    )

    penalty, reasons = engine._timeframe_conflict(
        bearish,
        bearish,
        "LONG",
        "LONG-B",
    )

    assert penalty == -20
    assert any("相反" in reason for reason in reasons)


def test_mixed_timeframes_receive_penalty():
    engine = StrategyEngine()

    bullish = make_features()
    bearish = make_features(
        ema7=99,
        ema20=100,
        plus_di=10,
        minus_di=30,
    )

    penalty, reasons = engine._timeframe_conflict(
        bullish,
        bearish,
        "LONG",
        "LONG-A",
    )

    assert penalty < 0
    assert any("衝突" in reason for reason in reasons)


def test_missing_relative_strength_has_no_bonus():
    adjustment, reason = StrategyEngine._relative_strength_adjustment(
        None,
        "LONG",
    )

    assert adjustment == 0
    assert "缺失" in reason


def test_missing_relative_strength_caps_strategy_score():
    engine = StrategyEngine()
    features = make_features()

    score, reasons = engine._strategy_score(
        base_score=100,
        f=features,
        direction="LONG",
        strategy="LONG-A",
        fib_context=None,
        relative_strength_missing=True,
    )

    assert score <= 69
    assert any("資料不完整" in reason for reason in reasons)


def test_macd_improvement_is_not_double_counted():
    engine = StrategyEngine()
    features = make_features()

    score, reasons = engine._strategy_score(
        base_score=80,
        f=features,
        direction="LONG",
        strategy="LONG-A",
        fib_context=None,
    )

    assert score <= 100
    assert not any("多方動能改善" in reason for reason in reasons)


def test_breakout_rejects_unconfirmed_close():
    engine = StrategyEngine(breakout_lookback=3)

    df = make_breakout_df()

    features = make_features(
        close=103.0,
        volume=2000.0,
        volume_ma=1000.0,
    )

    assert engine._breakout_long(features, df) is False


def test_breakdown_rejects_unconfirmed_close():
    engine = StrategyEngine(breakout_lookback=3)

    df = make_breakdown_df()

    features = make_features(
        close=101.0,
        volume=2000.0,
        volume_ma=1000.0,
    )

    assert engine._breakdown_short(features, df) is False


def test_score_stays_within_zero_and_hundred():
    engine = StrategyEngine()
    features = make_features()

    score, reasons = engine._strategy_score(
        base_score=100,
        f=features,
        direction="LONG",
        strategy="LONG-A",
        fib_context=None,
    )

    assert 0 <= score <= 100
    assert isinstance(reasons, list)
