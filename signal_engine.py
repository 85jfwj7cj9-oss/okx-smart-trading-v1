
import math

import pandas as pd

from indicators import IndicatorEngine
from strategy import StrategyEngine
from risk_manager import RiskManager
from market_data import MarketData


class SignalEngine:
    """
    OKX SMART TRADING V1.1

    多時間週期訊號分析引擎。
    LONG-A、LONG-B、SHORT-A、SHORT-B 分別建立模擬交易計畫。
    僅分析及模擬，不執行真實下單。
    """

    TIMEFRAMES = ("1H", "4H")

    STRATEGY_NAMES = (
        "LONG-A",
        "LONG-B",
        "SHORT-A",
        "SHORT-B"
    )

    def __init__(
        self,
        market_data=None,
        indicator_engine=None,
        strategy_engine=None,
        risk_manager=None
    ):
        self.market_data = market_data or MarketData()
        self.indicator_engine = (
            indicator_engine or IndicatorEngine()
        )
        self.strategy_engine = (
            strategy_engine or StrategyEngine()
        )
        self.risk_manager = risk_manager or RiskManager()

    @staticmethod
    def _safe_float(value):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None

        if not math.isfinite(number):
            return None

        return number

    @staticmethod
    def _candles_to_dataframe(candles):
        if not isinstance(candles, list) or not candles:
            raise ValueError("Candle data is empty")

        df = pd.DataFrame(candles)

        required = [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]

        missing = [
            column for column in required
            if column not in df.columns
        ]

        if missing:
            raise ValueError(
                "Missing candle columns: "
                + ", ".join(missing)
            )

        for column in required:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce"
            )

        df = df.dropna(subset=required)

        if df.empty:
            raise ValueError(
                "Candle data has no valid rows"
            )

        df = df.sort_values("timestamp")

        df = df.drop_duplicates(
            subset=["timestamp"],
            keep="last"
        )

        df = df.reset_index(drop=True)

        if len(df) < 30:
            raise ValueError(
                "Insufficient candle history; "
                "at least 30 rows required"
            )

        invalid_ohlc = (
            (df["high"] < df["low"])
            | (df["high"] < df["open"])
            | (df["high"] < df["close"])
            | (df["low"] > df["open"])
            | (df["low"] > df["close"])
            | (df["volume"] < 0)
            | (df["open"] <= 0)
            | (df["high"] <= 0)
            | (df["low"] <= 0)
            | (df["close"] <= 0)
        )

        if invalid_ohlc.any():
            raise ValueError(
                "Invalid OHLCV candle data"
            )

        return df

    def _get_confirmed_candles(
        self,
        inst_id,
        timeframe
    ):
        candles = self.market_data.client.get_candles(
            inst_id,
            bar=timeframe,
            limit=100,
            confirmed_only=True
        )

        return self._candles_to_dataframe(candles)

    def _prepare_features(self, df):
        result = self.indicator_engine.calculate_all(
            df.copy()
        )

        if not isinstance(result, pd.DataFrame):
            raise ValueError(
                "Indicator engine must return a DataFrame"
            )

        if result.empty:
            raise ValueError(
                "Indicator result is empty"
            )

        return result

    @staticmethod
    def _extract_relative_strength(data):
        if not isinstance(data, dict):
            raise ValueError(
                "Invalid relative strength data"
            )

        values = {}

        for timeframe in ("1H", "4H"):
            item = data.get(timeframe)

            if not isinstance(item, dict):
                raise ValueError(
                    f"Missing relative strength data for {timeframe}"
                )

            value = SignalEngine._safe_float(
                item.get("relative_strength_pct")
            )

            if value is None:
                raise ValueError(
                    f"Invalid relative strength for {timeframe}"
                )

            values[timeframe] = value

        return values

    @staticmethod
    def _normalize_strategy_result(result):
        if not isinstance(result, dict):
            raise ValueError(
                "Strategy engine returned invalid result"
            )

        normalized = dict(result)

        raw_signals = result.get("signals", [])

        if not isinstance(raw_signals, list):
            raw_signals = []

        valid_signals = []

        for raw in raw_signals:
            if not isinstance(raw, dict):
                continue

            signal = dict(raw)

            name = str(
                signal.get("signal", "")
            ).upper()

            direction = str(
                signal.get("direction", "")
            ).upper()

            score = SignalEngine._safe_float(
                signal.get("score")
            )

            price = SignalEngine._safe_float(
                signal.get("price")
            )

            if name not in SignalEngine.STRATEGY_NAMES:
                continue

            expected_direction = (
                "LONG"
                if name.startswith("LONG")
                else "SHORT"
            )

            if direction != expected_direction:
                continue

            if score is None or not 0 <= score <= 100:
                continue

            if (
                signal.get("price") is not None
                and (price is None or price <= 0)
            ):
                continue

            signal["signal"] = name
            signal["direction"] = direction
            signal["score"] = score
            signal["price"] = price

            reasons = signal.get("reasons", [])

            if not isinstance(reasons, list):
                reasons = []

            signal["reasons"] = reasons
            signal["candidate"] = True
            signal["status"] = "simulation_only"

            valid_signals.append(signal)

        valid_signals.sort(
            key=lambda item: item["score"],
            reverse=True
        )

        normalized["signals"] = valid_signals

        if valid_signals:
            best = valid_signals[0]

            normalized["direction"] = best["direction"]
            normalized["candidate"] = True
            normalized["signal"] = best["signal"]
            normalized["score"] = best["score"]
            normalized["price"] = best["price"]
            normalized["reasons"] = best["reasons"]

        else:
            normalized["direction"] = "NEUTRAL"
            normalized["candidate"] = False
            normalized["signal"] = None
            normalized["score"] = 0
            normalized["price"] = None
            normalized["reasons"] = []

        normalized["status"] = "simulation_only"

        return normalized

    @staticmethod
    def _extract_latest_atr(features):
        if not isinstance(features, pd.DataFrame):
            return None

        if features.empty:
            return None

        # 優先使用 atr，沒有時相容 atr_14。
        for column in ("atr", "atr_14"):
            if column not in features.columns:
                continue

            value = SignalEngine._safe_float(
                features.iloc[-1][column]
            )

            if value is not None and value > 0:
                return value

        return None

    def _create_strategy_trade_plans(
        self,
        symbol,
        signals,
        atr,
        equity=None
    ):
        plans = {}

        for signal in signals:
            name = signal["signal"]
            direction = signal["direction"]
            entry_price = signal.get("price")

            if entry_price is None or entry_price <= 0:
                plans[name] = {
                    "symbol": symbol,
                    "strategy": name,
                    "direction": direction,
                    "status": "error",
                    "reason": "Invalid or missing entry price",
                    "auto_trading": False
                }

                signal["trade_plan"] = plans[name]
                continue

            try:
                plan = self.risk_manager.create_trade_plan(
                    symbol=symbol,
                    side=direction,
                    entry_price=entry_price,
                    atr=atr,
                    equity=equity
                )

                if not isinstance(plan, dict):
                    raise ValueError(
                        "Risk manager returned invalid trade plan"
                    )

                plan = dict(plan)

                plan["symbol"] = symbol
                plan["strategy"] = name
                plan["direction"] = direction
                plan["status"] = plan.get(
                    "status",
                    "simulation_only"
                )
                plan["auto_trading"] = False

                plans[name] = plan
                signal["trade_plan"] = plan

            except Exception as exc:
                plans[name] = {
                    "symbol": symbol,
                    "strategy": name,
                    "direction": direction,
                    "status": "error",
                    "reason": str(exc),
                    "auto_trading": False
                }

                signal["trade_plan"] = plans[name]

        return plans

    @staticmethod
    def _select_best_trade_plan(
        signals,
        trade_plans
    ):
        """
        選擇最高分且成功建立交易計畫的策略。
        不讓失敗的最高分策略遮蔽其他有效策略。
        """
        for signal in signals:
            name = signal.get("signal")
            plan = trade_plans.get(name)

            if not isinstance(plan, dict):
                continue

            if plan.get("status") == "error":
                continue

            return signal, plan

        return None, None

    def analyze_symbol(
        self,
        inst_id,
        equity=None
    ):
        symbol = inst_id

        try:
            if not isinstance(inst_id, str):
                raise ValueError(
                    "Invalid instrument ID"
                )

            inst_id = inst_id.strip().upper()
            symbol = inst_id

            if not inst_id.endswith("-USDT-SWAP"):
                raise ValueError(
                    "Only USDT perpetual swaps are supported"
                )

            if inst_id == "BTC-USDT-SWAP":
                raise ValueError(
                    "BTC is the benchmark and cannot be analyzed against itself"
                )

            df_1h = self._get_confirmed_candles(
                inst_id,
                "1H"
            )

            df_4h = self._get_confirmed_candles(
                inst_id,
                "4H"
            )

            features_1h = self._prepare_features(
                df_1h
            )

            features_4h = self._prepare_features(
                df_4h
            )

            relative_data = (
                self.market_data
                .get_multi_timeframe_relative_strength(
                    inst_id,
                    timeframes=self.TIMEFRAMES,
                    limit=100
                )
            )

            relative_strength = (
                self._extract_relative_strength(
                    relative_data
                )
            )

            strategy_result = self.strategy_engine.analyze(
                inst_id,
                features_1h,
                features_4h,
                relative_strength_1h=relative_strength["1H"],
                relative_strength_4h=relative_strength["4H"]
            )

            strategy = self._normalize_strategy_result(
                strategy_result
            )

            if not strategy["signals"]:
                return {
                    "symbol": inst_id,
                    "status": "analyzed",
                    "relative_strength": relative_strength,
                    "direction": "NEUTRAL",
                    "candidate": False,
                    "strategy": strategy,
                    "strategy_trade_plans": {},
                    "trade_plan": None,
                    "selected_signal": None,
                    "trading_mode": "simulation_only",
                    "auto_trading": False
                }

            atr = self._extract_latest_atr(
                features_1h
            )

            if atr is None:
                raise ValueError(
                    "ATR is missing or invalid; "
                    "cannot create trade plan"
                )

            strategy_trade_plans = (
                self._create_strategy_trade_plans(
                    symbol=inst_id,
                    signals=strategy["signals"],
                    atr=atr,
                    equity=equity
                )
            )

            selected_signal, trade_plan = (
                self._select_best_trade_plan(
                    strategy["signals"],
                    strategy_trade_plans
                )
            )

            return {
                "symbol": inst_id,
                "status": "analyzed",
                "relative_strength": relative_strength,
                "direction": strategy["direction"],
                "candidate": strategy["candidate"],
                "strategy": strategy,
                "strategy_trade_plans": strategy_trade_plans,
                "trade_plan": trade_plan,
                "selected_signal": (
                    selected_signal["signal"]
                    if selected_signal
                    else None
                ),
                "atr": atr,
                "trading_mode": "simulation_only",
                "auto_trading": False
            }

        except Exception as exc:
            return {
                "symbol": symbol,
                "status": "error",
                "error": str(exc),
                "direction": "NEUTRAL",
                "candidate": False,
                "strategy": {
                    "signals": [],
                    "direction": "NEUTRAL",
                    "candidate": False,
                    "status": "error"
                },
                "strategy_trade_plans": {},
                "trade_plan": None,
                "selected_signal": None,
                "trading_mode": "simulation_only",
                "auto_trading": False
            }

    def analyze_multiple(
        self,
        symbols,
        equity=None
    ):
        results = []

        for symbol in symbols:
            results.append(
                self.analyze_symbol(
                    symbol,
                    equity=equity
                )
            )

        return results
