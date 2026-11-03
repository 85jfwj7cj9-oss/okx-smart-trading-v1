
import pandas as pd

from config import Config
from market_data import MarketData
from indicators import IndicatorEngine
from strategy import StrategyEngine
from risk_manager import RiskManager


class SignalEngine:
    """OKX SMART TRADING V1.0 訊號整合引擎。"""

    def __init__(
        self,
        market_data=None,
        indicator_engine=None,
        strategy_engine=None,
        risk_manager=None
    ):
        self.market_data = market_data or MarketData()
        self.indicator_engine = indicator_engine or IndicatorEngine()
        self.strategy_engine = strategy_engine or StrategyEngine()
        self.risk_manager = risk_manager or RiskManager()

    @staticmethod
    def _candles_to_dataframe(candles):
        if not candles:
            raise ValueError("No candle data received")

        df = pd.DataFrame(candles)

        required = [
            "timestamp", "open", "high",
            "low", "close", "volume"
        ]

        missing = [
            col for col in required if col not in df.columns
        ]

        if missing:
            raise ValueError(f"Missing candle columns: {missing}")

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(
            subset=["open", "high", "low", "close", "volume"]
        )

        df = df.sort_values("timestamp")
        df = df.drop_duplicates(
            subset=["timestamp"], keep="last"
        )
        df = df.reset_index(drop=True)

        if len(df) < 30:
            raise ValueError("Not enough confirmed candles")

        return df

    def _prepare_features(self, candles):
        df = self._candles_to_dataframe(candles)
        features = self.indicator_engine.calculate_all(df)

        if not isinstance(features, pd.DataFrame):
            raise TypeError("Indicator engine must return DataFrame")

        if features.empty:
            raise ValueError("Indicator calculation returned no data")

        return features

    @staticmethod
    def _extract_relative_strength(result):
        if not isinstance(result, dict):
            return None

        value = result.get("relative_strength_pct")

        if value is None:
            return None

        return float(value)

    @staticmethod
    def _normalize_strategy_result(result):
        if not isinstance(result, dict):
            raise TypeError("StrategyEngine must return a dictionary")

        signals = result.get("signals", [])

        if not isinstance(signals, list):
            signals = []

        valid_signals = [
            item for item in signals
            if isinstance(item, dict)
            and str(item.get("direction", "")).upper()
            in ("LONG", "SHORT")
        ]

        best_signal = max(
            valid_signals,
            key=lambda item: float(item.get("score", 0)),
            default=None
        )

        normalized = dict(result)

        if best_signal is None:
            normalized.update({
                "direction": "NEUTRAL",
                "candidate": False,
                "signal": None,
                "score": max(
                    float(result.get("long_score", 0)),
                    float(result.get("short_score", 0))
                ),
                "reasons": []
            })
        else:
            normalized.update({
                "direction": best_signal["direction"].upper(),
                "candidate": True,
                "signal": best_signal.get("signal"),
                "score": float(best_signal.get("score", 0)),
                "price": best_signal.get("price"),
                "reasons": best_signal.get("reasons", [])
            })

        return normalized

    def analyze_symbol(
        self,
        inst_id,
        equity=None,
        daily_realized_pnl=0
    ):
        """分析單一 USDT 永續合約，只產生模擬交易計畫。"""

        try:
            if not inst_id.endswith("-USDT-SWAP"):
                raise ValueError(
                    "Only USDT perpetual contracts are supported"
                )

            if inst_id == Config.BTC_BENCHMARK:
                raise ValueError(
                    "BTC is the benchmark and cannot be analyzed against itself"
                )

            candles_1h = self.market_data.client.get_candles(
                inst_id,
                bar="1H",
                limit=100,
                confirmed_only=True
            )

            candles_4h = self.market_data.client.get_candles(
                inst_id,
                bar="4H",
                limit=100,
                confirmed_only=True
            )

            features_1h = self._prepare_features(candles_1h)
            features_4h = self._prepare_features(candles_4h)

            relative_strength = (
                self.market_data.get_multi_timeframe_relative_strength(
                    inst_id,
                    timeframes=("1H", "4H"),
                    limit=100
                )
            )

            rs_1h = self._extract_relative_strength(
                relative_strength.get("1H")
            )
            rs_4h = self._extract_relative_strength(
                relative_strength.get("4H")
            )

            if rs_1h is None or rs_4h is None:
                raise ValueError(
                    "BTC relative strength data is incomplete"
                )

            strategy_result = self.strategy_engine.analyze(
                inst_id,
                features_1h,
                features_4h,
                relative_strength_1h=rs_1h,
                relative_strength_4h=rs_4h
            )

            strategy_result = self._normalize_strategy_result(
                strategy_result
            )

            direction = strategy_result["direction"]
            candidate = strategy_result["candidate"]

            trade_plan = None

            if candidate and direction in ("LONG", "SHORT"):
                latest = features_1h.iloc[-1]

                atr_value = latest.get("atr")

                if atr_value is None or pd.isna(atr_value):
                    raise ValueError("ATR data is unavailable")

                atr_value = float(atr_value)

                if atr_value <= 0:
                    raise ValueError("ATR must be greater than zero")

                entry_price = float(latest["close"])

                trade_plan = self.risk_manager.create_trade_plan(
                    symbol=inst_id,
                    side=direction,
                    entry_price=entry_price,
                    atr=atr_value,
                    equity=equity,
                    daily_realized_pnl=daily_realized_pnl
                )

            return {
                "symbol": inst_id,
                "status": "analyzed",
                "timeframes": ["1H", "4H"],
                "relative_strength": {
                    "1H": rs_1h,
                    "4H": rs_4h
                },
                "direction": direction,
                "candidate": candidate,
                "strategy": strategy_result,
                "trade_plan": trade_plan,
                "trading_mode": "simulation_only",
                "auto_trading": False
            }

        except Exception as exc:
            return {
                "symbol": inst_id,
                "status": "error",
                "error": str(exc),
                "trade_plan": None,
                "trading_mode": "simulation_only",
                "auto_trading": False
            }

    def analyze_multiple(self, symbols, equity=None):
        return [
            self.analyze_symbol(symbol, equity=equity)
            for symbol in symbols
        ]
