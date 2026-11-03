
import pandas as pd
import pytest

from signal_engine import SignalEngine


class FakeClient:
    def get_candles(
        self,
        inst_id,
        bar="1H",
        limit=100,
        confirmed_only=True
    ):
        return [
            {
                "timestamp": i,
                "open": 100,
                "high": 102,
                "low": 98,
                "close": 100,
                "volume": 1000
            }
            for i in range(40)
        ]


class FakeMarketData:
    def __init__(self):
        self.client = FakeClient()

    def get_multi_timeframe_relative_strength(
        self,
        inst_id,
        timeframes=("1H", "4H"),
        limit=100
    ):
        return {
            "1H": {"relative_strength_pct": 2.5},
            "4H": {"relative_strength_pct": 1.5}
        }


class FakeIndicatorEngine:
    def calculate_all(self, df):
        result = df.copy()

        result["ema_7"] = 101
        result["ema_20"] = 100
        result["ema_50"] = 99
        result["rsi_14"] = 55
        result["macd"] = 2
        result["macd_signal"] = 1
        result["macd_hist"] = 1
        result["adx"] = 25
        result["plus_di"] = 30
        result["minus_di"] = 10
        result["volume_ma_20"] = 900
        result["atr"] = 2

        return result


class FakeStrategyEngine:
    def analyze(
        self,
        inst_id,
        df_1h,
        df_4h,
        relative_strength_1h=None,
        relative_strength_4h=None
    ):
        return {
            "symbol": inst_id,
            "long_score": 85,
            "short_score": 20,
            "signals": [
                {
                    "symbol": inst_id,
                    "signal": "LONG-A",
                    "direction": "LONG",
                    "score": 85,
                    "price": 100,
                    "reasons": ["強於 BTC"],
                    "status": "simulation_only"
                }
            ],
            "status": "simulation_only"
        }


class FakeRiskManager:
    def create_trade_plan(
        self,
        symbol,
        side,
        entry_price,
        atr,
        equity=None,
        daily_realized_pnl=0
    ):
        return {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "atr": atr,
            "stop_loss": 96,
            "take_profit": 108,
            "status": "simulation_only"
        }


def make_engine(strategy_engine=None, risk_manager=None):
    return SignalEngine(
        market_data=FakeMarketData(),
        indicator_engine=FakeIndicatorEngine(),
        strategy_engine=strategy_engine or FakeStrategyEngine(),
        risk_manager=risk_manager or FakeRiskManager()
    )


def test_successful_long_analysis():
    engine = make_engine()

    result = engine.analyze_symbol("ETH-USDT-SWAP")

    assert result["status"] == "analyzed"
    assert result["direction"] == "LONG"
    assert result["candidate"] is True
    assert result["strategy"]["signal"] == "LONG-A"
    assert result["trade_plan"]["side"] == "LONG"
    assert result["trading_mode"] == "simulation_only"
    assert result["auto_trading"] is False


def test_relative_strength_is_passed_to_strategy():
    class RecordingStrategy(FakeStrategyEngine):
        def analyze(
            self,
            inst_id,
            df_1h,
            df_4h,
            relative_strength_1h=None,
            relative_strength_4h=None
        ):
            assert relative_strength_1h == 2.5
            assert relative_strength_4h == 1.5
            return super().analyze(
                inst_id,
                df_1h,
                df_4h,
                relative_strength_1h,
                relative_strength_4h
            )

    engine = make_engine(strategy_engine=RecordingStrategy())

    result = engine.analyze_symbol("ETH-USDT-SWAP")

    assert result["status"] == "analyzed"


def test_no_signal_creates_no_trade_plan():
    class NoSignalStrategy:
        def analyze(self, *args, **kwargs):
            return {
                "symbol": "ETH-USDT-SWAP",
                "long_score": 40,
                "short_score": 30,
                "signals": [],
                "status": "simulation_only"
            }

    engine = make_engine(strategy_engine=NoSignalStrategy())

    result = engine.analyze_symbol("ETH-USDT-SWAP")

    assert result["status"] == "analyzed"
    assert result["direction"] == "NEUTRAL"
    assert result["candidate"] is False
    assert result["trade_plan"] is None


def test_btc_cannot_be_analyzed_against_itself():
    engine = make_engine()

    result = engine.analyze_symbol("BTC-USDT-SWAP")

    assert result["status"] == "error"
    assert "benchmark" in result["error"]


def test_non_usdt_swap_is_rejected():
    engine = make_engine()

    result = engine.analyze_symbol("ETH-USDT")

    assert result["status"] == "error"
    assert "USDT perpetual" in result["error"]


def test_missing_relative_strength_is_rejected():
    class IncompleteMarketData(FakeMarketData):
        def get_multi_timeframe_relative_strength(
            self,
            inst_id,
            timeframes=("1H", "4H"),
            limit=100
        ):
            return {
                "1H": {"relative_strength_pct": 2.5},
                "4H": {"relative_strength_pct": None}
            }

    engine = SignalEngine(
        market_data=IncompleteMarketData(),
        indicator_engine=FakeIndicatorEngine(),
        strategy_engine=FakeStrategyEngine(),
        risk_manager=FakeRiskManager()
    )

    result = engine.analyze_symbol("ETH-USDT-SWAP")

    assert result["status"] == "error"
    assert "relative strength" in result["error"]


def test_invalid_atr_prevents_trade_plan():
    class InvalidAtrIndicator(FakeIndicatorEngine):
        def calculate_all(self, df):
            result = super().calculate_all(df)
            result["atr"] = 0
            return result

    engine = SignalEngine(
        market_data=FakeMarketData(),
        indicator_engine=InvalidAtrIndicator(),
        strategy_engine=FakeStrategyEngine(),
        risk_manager=FakeRiskManager()
    )

    result = engine.analyze_symbol("ETH-USDT-SWAP")

    assert result["status"] == "error"
    assert "ATR" in result["error"]
    assert result["trade_plan"] is None


def test_normalized_strategy_selects_highest_score():
    result = {
        "symbol": "ETH-USDT-SWAP",
        "long_score": 85,
        "short_score": 80,
        "signals": [
            {
                "signal": "LONG-A",
                "direction": "LONG",
                "score": 85,
                "reasons": ["多方"]
            },
            {
                "signal": "SHORT-A",
                "direction": "SHORT",
                "score": 80,
                "reasons": ["空方"]
            }
        ]
    }

    normalized = SignalEngine._normalize_strategy_result(result)

    assert normalized["direction"] == "LONG"
    assert normalized["candidate"] is True
    assert normalized["signal"] == "LONG-A"
