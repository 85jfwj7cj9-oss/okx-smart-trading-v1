
import pandas as pd

from config import Config
from market_data import MarketData
from indicators import IndicatorEngine
from strategy import StrategyEngine
from risk_manager import RiskManager


class SignalEngine:
    """
    OKX SMART TRADING V1.0
    行情、技術指標、策略及風險管理整合引擎。

    僅產生模擬交易計畫，不會執行真實下單。
    """

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
                f"Missing candle columns: {missing}"
            )

        for column in [
            "open", "high", "low", "close", "volume"
        ]:
            df[column] = pd.to_numeric(
                df[column], errors="coerce"
            )

        df = df.dropna(
            subset=[
                "open", "high", "low", "close", "volume"
            ]
        )

        df = df.sort_values("timestamp")
        df = df.drop_duplicates(
            subset=["timestamp"],
            keep="last"
        )

        df = df.reset_index(drop=True)

        if len(df) < 30:
            raise ValueError(
                "Not enough confirmed candles for analysis"
            )

        return df

    def _prepare_features(self, candles):
        df = self._candles_to_dataframe(candles)

        features = self.indicator_engine.calculate_all(df)

        if not isinstance(features, pd.DataFrame):
            raise TypeError(
                "IndicatorEngine.calculate_all must return a DataFrame"
            )

        if features.empty:
            raise ValueError("Indicator calculation returned no data")

        return features

    @staticmethod
    def _extract_relative_strength(result):
        if not isinstance(result, dict):
            return None

        if result.get("relative_strength_pct") is None:
            return None

        return float(result["relative_strength_pct"])

    def analyze_symbol(
        self,
        inst_id,
        equity=None,
        daily_realized_pnl=0
    ):
        """
        分析單一 USDT 永續合約。

        只使用已收盤的 1H / 4H K 線。
        """

        try:
            if not inst_id.endswith("-USDT-SWAP"):
                raise ValueError(
                    "Only USDT perpetual contracts are supported"
                )

            if inst_id == Config.BTC_BENCHMARK:
                raise ValueError(
                    "BTC is the benchmark and is not analyzed against itself"
                )

            # 取得已收盤 K 線。
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

            # 計算技術指標。
            features_1h = self._prepare_features(candles_1h)
            features_4h = self._prepare_features(candles_4h)

            # 取得 BTC 相對強度。
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

            # 交由交易策略分析。
            strategy_result = self.strategy_engine.analyze(
                features_1h,
                features_4h,
                relative_strength=rs_1h
            )

            if not isinstance(strategy_result, dict):
                raise TypeError(
                    "StrategyEngine must return a dictionary"
                )

            # 保留完整策略結果，不自行假設訊號成立。
            direction = str(
                strategy_result.get("direction", "")
            ).upper()

            candidate = bool(
                strategy_result.get(
                    "candidate",
                    strategy_result.get("is_candidate", False)
                )
            )

            trade_plan = None

            if candidate and direction in ("LONG", "SHORT"):
                latest = features_1h.iloc[-1]

                atr_value = latest.get("atr")

                if pd.isna(atr_value) or float(atr_value) <= 0:
                    raise ValueError(
                        "Valid ATR is required for risk calculation"
                    )

                entry_price = float(latest["close"])

                trade_plan = self.risk_manager.create_trade_plan(
                    symbol=inst_id,
                    side=direction,
                    entry_price=entry_price,
                    atr=float(atr_value),
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
        """
        批次分析幣種。
        """
        results = []

        for symbol in symbols:
            result = self.analyze_symbol(
                symbol,
                equity=equity
            )

            results.append(result)

        return results
