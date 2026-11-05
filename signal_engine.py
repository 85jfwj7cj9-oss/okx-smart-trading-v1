
import math
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
            raise ValueError(
                f"Missing candle columns: {missing}"
            )

        for col in [
            "open", "high", "low", "close", "volume"
        ]:
            df[col] = pd.to_numeric(
                df[col], errors="coerce"
            )

        df = df.dropna(
            subset=[
                "open", "high", "low",
                "close", "volume"
            ]
        )

        df = df.sort_values("timestamp")
        df = df.drop_duplicates(
            subset=["timestamp"], keep="last"
        )
        df = df.reset_index(drop=True)

        if len(df) < 30:
            raise ValueError(
                "Not enough confirmed candles"
            )

        if (
            (df["close"] <= 0).any()
            or (df["high"] <= 0).any()
            or (df["low"] <= 0).any()
            or (df["volume"] < 0).any()
        ):
            raise ValueError("Invalid candle prices or volume")

        if (
            (df["high"] < df["low"]).any()
            or (df["close"] > df["high"]).any()
            or (df["close"] < df["low"]).any()
        ):
            raise ValueError("Invalid OHLC candle structure")

        return df

    def _prepare_features(self, candles):
        df = self._candles_to_dataframe(candles)

        features = self.indicator_engine.calculate_all(df)

        if not isinstance(features, pd.DataFrame):
            raise TypeError(
                "Indicator engine must return DataFrame"
            )

        if features.empty:
            raise ValueError(
                "Indicator calculation returned no data"
            )

        return features

    @staticmethod
    def _extract_relative_strength(result):
        if not isinstance(result, dict):
            return None

        value = result.get("relative_strength_pct")

        if value is None:
            return None

        try:
            value = float(value)
        except (TypeError, ValueError):
            return None

        if not math.isfinite(value):
            return None

        return value

    @staticmethod
    def _safe_score(value):
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.0

        if not math.isfinite(score):
            return 0.0

        return score

    @classmethod
    def _normalize_strategy_result(cls, result):
        if not isinstance(result, dict):
            raise TypeError(
                "StrategyEngine must return a dictionary"
            )

        signals = result.get("signals", [])

        if not isinstance(signals, list):
            signals = []

        valid_signals = []

        for item in signals:
            if not isinstance(item, dict):
                continue

            direction = str(
                item.get("direction", "")
            ).upper()

            if direction not in ("LONG", "SHORT"):
                continue

            score = cls._safe_score(
                item.get("score", 0)
            )

            normalized_item = dict(item)
            normalized_item["direction"] = direction
            normalized_item["score"] = score

            valid_signals.append(normalized_item)

        best_signal = max(
            valid_signals,
            key=lambda item: item["score"],
            default=None
        )

        normalized = dict(result)

        if best_signal is None:
            normalized.update({
                "direction": "NEUTRAL",
                "candidate": False,
                "signal": None,
                "score": max(
                    cls._safe_score(
                        result.get("long_score", 0)
                    ),
                    cls._safe_score(
                        result.get("short_score", 0)
                    )
                ),
                "reasons": []
            })
        else:
            normalized.update({
                "direction": best_signal["direction"],
                "candidate": True,
                "signal": best_signal.get("signal"),
                "score": best_signal["score"],
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
            if not isinstance(inst_id, str):
                raise ValueError("Invalid instrument ID")

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

            if not isinstance(relative_strength, dict):
                raise ValueError(
                    "BTC relative strength data is invalid"
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

                # 優先讀取指標引擎實際輸出的 ATR 欄位。
                atr_value = latest.get("atr_14")

                # 相容舊版欄位名稱。
                if atr_value is None:
                    atr_value = latest.get("atr")

                if atr_value is None:
                    raise ValueError(
                        "ATR data is unavailable"
                    )

                try:
                    atr_value = float(atr_value)
                except (TypeError, ValueError):
                    raise ValueError(
                        "ATR data is invalid"
                    )

                if (
                    not math.isfinite(atr_value)
                    or atr_value <= 0
                ):
                    raise ValueError(
                        "ATR must be a finite positive number"
                    )

                entry_price = float(latest["close"])

                if (
                    not math.isfinite(entry_price)
                    or entry_price <= 0
                ):
                    raise ValueError(
                        "Entry price is invalid"
                    )

                trade_plan = self.risk_manager.create_trade_plan(
                    symbol=inst_id,
                    side=direction,
                    entry_price=entry_price,
                    atr=atr_value,
                    equity=equity,
                    daily_realized_pnl=daily_realized_pnl
                )

                if not isinstance(trade_plan, dict):
                    raise ValueError(
                        "Risk manager returned an invalid trade plan"
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
            self.analyze_symbol(
                symbol,
                equity=equity
            )
            for symbol in symbols
        ]
