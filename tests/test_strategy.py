
import pandas as pd
import pytest

from config import Config
from strategy import StrategyEngine


def make_features(
    close=101,
    high=102,
    low=100,
    ema7=100.5,
    ema20=101,
    ema50=99,
    rsi=55,
    macd=1,
    macd_signal=0.5,
    macd_hist=0.2,
    previous_hist=0.1,
    adx=25,
    plus_di=30,
    minus_di=15,
    volume=200,
    volume_ma=100,
    previous_high=110,
    previous_low=90
):
    return pd.DataFrame([
        {
            "close": close - 1,
            "high": previous_high,
            "low": previous_low,
            "volume": 100,
            "ema_7": ema7,
            "ema_20": ema20,
            "ema_50": ema50,
            "rsi_14": rsi,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": previous_hist,
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "volume_ma_20": volume_ma
        },
        {
            "close": close,
            "high": high,
            "low": low,
            "volume": volume,
            "ema_7": ema7,
            "ema_20": ema20,
            "ema_50": ema50,
            "rsi_14": rsi,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "volume_ma_20": volume_ma
        }
    ])


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(Config, "ENABLE_LONG", True)
    monkeypatch.setattr(Config, "ENABLE_SHORT", True)
    return StrategyEngine(min_score=0)


def test_invalid_1h_data(engine):
    result = engine.analyze(
        "ETH-USDT-SWAP",
        pd.DataFrame(),
        make_features()
    )
    assert result["status"] == "insufficient_data"
    assert result["signals"] == []


def test_invalid_4h_data(engine):
    result = engine.analyze(
        "ETH-USDT-SWAP",
        make_features(),
        pd.DataFrame()
    )
    assert result["status"] == "insufficient_data"
    assert result["signals"] == []


def test_missing_indicator_column(engine):
    df = make_features().drop(columns=["ema_20"])
    result = engine.analyze(
        "ETH-USDT-SWAP",
        df,
        make_features()
    )
    assert result["status"] == "insufficient_data"


def test_invalid_close_price(engine):
    df = make_features(close=0)
    result = engine.analyze(
        "ETH-USDT-SWAP",
        df,
        make_features()
    )
    assert result["status"] == "insufficient_data"


def test_long_early_entry(engine):
    df = make_features(
        close=101,
        ema7=100.5,
        ema20=101,
        ema50=99,
        rsi=55,
        macd_hist=0.2,
        previous_hist=0.1,
        previous_high=110
    )
    result = engine.analyze(
        "ETH-USDT-SWAP",
        df,
        df,
        relative_strength_1h=2,
        relative_strength_4h=1
    )
    signals = [item["signal"] for item in result["signals"]]
    assert "LONG-A" in signals


def test_long_breakout_confirmation(engine):
    df = make_features(
        close=106,
        high=107,
        low=103,
        ema7=105.8,
        ema20=104,
        ema50=100,
        rsi=65,
        macd=2,
        macd_signal=1,
        macd_hist=0.5,
        previous_hist=0.2,
        previous_high=105
    )
    result = engine.analyze(
        "ETH-USDT-SWAP",
        df,
        df,
        relative_strength_1h=2,
        relative_strength_4h=2
    )
    signals = [item["signal"] for item in result["signals"]]
    assert "LONG-B" in signals


def test_short_early_entry(engine):
    df = make_features(
        close=99,
        high=102,
        low=98,
        ema7=99.5,
        ema20=100,
        ema50=101,
        rsi=50,
        macd=-1,
        macd_signal=-0.5,
        macd_hist=-0.2,
        previous_hist=-0.1,
        plus_di=15,
        minus_di=30,
        previous_low=90
    )
    result = engine.analyze(
        "ETH-USDT-SWAP",
        df,
        df,
        relative_strength_1h=-2,
        relative_strength_4h=-1
    )
    signals = [item["signal"] for item in result["signals"]]
    assert "SHORT-A" in signals


def test_short_breakdown_confirmation(engine):
    df = make_features(
        close=92,
        high=95,
        low=91,
        ema7=94,
        ema20=96,
        ema50=100,
        rsi=35,
        macd=-2,
        macd_signal=-1,
        macd_hist=-0.5,
        previous_hist=-0.2,
        plus_di=10,
        minus_di=35,
        previous_low=94
    )
    result = engine.analyze(
        "ETH-USDT-SWAP",
        df,
        df,
        relative_strength_1h=-2,
        relative_strength_4h=-2
    )
    signals = [item["signal"] for item in result["signals"]]
    assert "SHORT-B" in signals


def test_long_score_increases_when_stronger_than_btc(engine):
    features = engine._common_features(make_features())
    score_without_rs, _ = engine._score_long(features, relative_strength=0)
    score_with_rs, _ = engine._score_long(features, relative_strength=3)
    assert score_with_rs > score_without_rs


def test_short_score_increases_when_weaker_than_btc(engine):
    features = engine._common_features(make_features())
    score_without_rs, _ = engine._score_short(features, relative_strength=0)
    score_with_rs, _ = engine._score_short(features, relative_strength=-3)
    assert score_with_rs > score_without_rs


def test_long_score_penalty_when_weak_against_btc(engine):
    features = engine._common_features(make_features())
    normal_score, _ = engine._score_long(features, relative_strength=0)
    weak_score, _ = engine._score_long(features, relative_strength=-3)
    assert weak_score < normal_score


def test_short_score_penalty_when_strong_against_btc(engine):
    features = engine._common_features(make_features())
    normal_score, _ = engine._score_short(features, relative_strength=0)
    strong_score, _ = engine._score_short(features, relative_strength=3)
    assert strong_score < normal_score


def test_minimum_score_blocks_signal(engine):
    engine.min_score = 101
    df = make_features()
    result = engine.analyze("ETH-USDT-SWAP", df, df)
    assert result["signals"] == []


def test_long_signal_can_be_disabled(engine, monkeypatch):
    monkeypatch.setattr(Config, "ENABLE_LONG", False)
    df = make_features()
    result = engine.analyze("ETH-USDT-SWAP", df, df)
    assert all(item["direction"] != "LONG" for item in result["signals"])


def test_short_signal_can_be_disabled(engine, monkeypatch):
    monkeypatch.setattr(Config, "ENABLE_SHORT", False)
    df = make_features(
        close=99,
        high=102,
        low=98,
        ema7=99.5,
        ema20=100,
        ema50=101,
        rsi=50,
        macd=-1,
        macd_signal=-0.5,
        macd_hist=-0.2,
        previous_hist=-0.1,
        plus_di=15,
        minus_di=30
    )
    result = engine.analyze("ETH-USDT-SWAP", df, df)
    assert all(item["direction"] != "SHORT" for item in result["signals"])


def test_signal_is_simulation_only(engine):
    df = make_features()
    result = engine.analyze("ETH-USDT-SWAP", df, df)
    for signal in result["signals"]:
        assert signal["status"] == "simulation_only"


def test_1h_4h_weighted_score(engine):
    df_1h = make_features()
    df_4h = make_features()

    f1 = engine._common_features(df_1h)
    f4 = engine._common_features(df_4h)

    score_1h, _ = engine._score_long(f1, 2)
    score_4h, _ = engine._score_long(f4, 1)

    expected = round(score_1h * 0.65 + score_4h * 0.35)

    result = engine.analyze(
        "ETH-USDT-SWAP",
        df_1h,
        df_4h,
        relative_strength_1h=2,
        relative_strength_4h=1
    )

    assert result["long_score"] == expected
