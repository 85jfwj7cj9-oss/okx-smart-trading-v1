
import math
from datetime import datetime, timezone

from config import Config
from signal_engine import SignalEngine
from market_data import MarketData


class MarketScanner:
    """
    OKX SMART TRADING V1.1

    USDT 永續合約市場掃描器。

    支援：
    - LONG-A 提前埋伏做多
    - LONG-B 突破確認做多
    - SHORT-A 提前埋伏做空
    - SHORT-B 跌破確認做空

    僅分析行情與模擬交易訊號，不執行真實下單。
    """

    STRATEGY_NAMES = (
        "LONG-A",
        "LONG-B",
        "SHORT-A",
        "SHORT-B"
    )

    def __init__(
        self,
        market_data=None,
        signal_engine=None,
        max_symbols=20,
        min_relative_strength=0.0
    ):
        self.market_data = market_data or MarketData()

        self.signal_engine = signal_engine or SignalEngine(
            market_data=self.market_data
        )

        self.max_symbols = max(
            1,
            min(int(max_symbols), 100)
        )

        self.min_relative_strength = float(
            min_relative_strength
        )

        if not math.isfinite(self.min_relative_strength):
            raise ValueError(
                "min_relative_strength must be finite"
            )

    @staticmethod
    def _safe_float(value, default=None):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return default

        if not math.isfinite(number):
            return default

        return number

    @classmethod
    def _get_score(cls, result):
        if not isinstance(result, dict):
            return 0.0

        strategy = result.get("strategy") or {}

        if not isinstance(strategy, dict):
            strategy = {}

        for key in ("score", "signal_score", "total_score"):
            value = cls._safe_float(strategy.get(key))

            if value is not None:
                return value

        return 0.0

    @staticmethod
    def _get_direction(result):
        if not isinstance(result, dict):
            return "NEUTRAL"

        strategy = result.get("strategy") or {}

        if not isinstance(strategy, dict):
            strategy = {}

        direction = str(
            strategy.get(
                "direction",
                result.get("direction", "")
            )
        ).upper()

        if direction in ("LONG", "SHORT"):
            return direction

        return "NEUTRAL"

    @staticmethod
    def _get_candidate(result):
        if not isinstance(result, dict):
            return False

        strategy = result.get("strategy") or {}

        if not isinstance(strategy, dict):
            strategy = {}

        value = strategy.get(
            "candidate",
            strategy.get("is_candidate", False)
        )

        return value is True

    @classmethod
    def _get_relative_strength(cls, result):
        if not isinstance(result, dict):
            return None

        relative = result.get("relative_strength") or {}

        if not isinstance(relative, dict):
            return None

        values = []

        for timeframe in ("1H", "4H"):
            value = cls._safe_float(
                relative.get(timeframe)
            )

            if value is None:
                return None

            values.append(value)

        return round(sum(values) / len(values), 4)

    @staticmethod
    def _get_symbols_from_rows(market_rows):
        if not isinstance(market_rows, list):
            raise ValueError(
                "Market data must return a list"
            )

        symbols = []
        seen = set()

        for row in market_rows:
            if not isinstance(row, dict):
                continue

            inst_id = row.get("inst_id")

            if not isinstance(inst_id, str):
                continue

            inst_id = inst_id.strip().upper()

            if not inst_id.endswith("-USDT-SWAP"):
                continue

            if inst_id in seen:
                continue

            seen.add(inst_id)
            symbols.append(inst_id)

        return symbols

    def _get_symbols(self):
        market_rows = self.market_data.get_top_symbols(
            limit=self.max_symbols
        )

        symbols = self._get_symbols_from_rows(
            market_rows
        )

        return symbols[:self.max_symbols]

    @staticmethod
    def _timestamp():
        return datetime.now(
            timezone.utc
        ).isoformat()

    def _error_result(self, symbol, exc):
        return {
            "symbol": symbol,
            "status": "error",
            "error": str(exc),
            "trade_plan": None,
            "strategy_trade_plans": {},
            "trading_mode": "simulation_only",
            "auto_trading": False
        }

    @staticmethod
    def _empty_strategy_lists():
        return {
            "long_a_candidates": [],
            "long_b_candidates": [],
            "short_a_candidates": [],
            "short_b_candidates": []
        }

    @classmethod
    def _get_strategy_signals(cls, item):
        strategy = item.get("strategy") or {}

        if not isinstance(strategy, dict):
            return []

        signals = strategy.get("signals", [])

        if not isinstance(signals, list):
            return []

        return signals

    @classmethod
    def _build_strategy_candidate(cls, item, signal):
        """
        建立單一策略排行榜資料。

        每個訊號使用自己的分數及交易計畫。

        沒有成功建立交易計畫的訊號，
        不列入正式策略候選排行榜。
        """

        if not isinstance(signal, dict):
            return None

        name = str(
            signal.get("signal", "")
        ).upper()

        if name not in cls.STRATEGY_NAMES:
            return None

        expected_direction = (
            "LONG"
            if name.startswith("LONG")
            else "SHORT"
        )

        direction = str(
            signal.get("direction", "")
        ).upper()

        if direction != expected_direction:
            return None

        score = cls._safe_float(
            signal.get("score")
        )

        if score is None or not 0 <= score <= 100:
            return None

        symbol = item.get("symbol")

        if not isinstance(symbol, str) or not symbol.strip():
            return None

        symbol = symbol.strip().upper()

        if not symbol.endswith("-USDT-SWAP"):
            return None

        price = cls._safe_float(
            signal.get("price")
        )

        if price is not None and price <= 0:
            price = None

        strategy_plans = item.get(
            "strategy_trade_plans"
        ) or {}

        if not isinstance(strategy_plans, dict):
            strategy_plans = {}

        trade_plan = strategy_plans.get(name)

        if not isinstance(trade_plan, dict):
            trade_plan = signal.get("trade_plan")

        if not isinstance(trade_plan, dict):
            return None

        if trade_plan.get("status") == "error":
            return None

        # 防止交易計畫與策略方向不一致。
        plan_direction = trade_plan.get("direction")

        if (
            plan_direction is not None
            and str(plan_direction).upper() != direction
        ):
            return None

        reasons = signal.get("reasons", [])

        if not isinstance(reasons, list):
            reasons = []

        candidate = {
            "symbol": symbol,
            "strategy": name,
            "direction": direction,
            "score": score,
            "price": price,
            "reasons": reasons,
            "timeframes": signal.get("timeframes", {}),
            "fibonacci": signal.get("fibonacci"),
            "invalidation_price": signal.get(
                "invalidation_price"
            ),
            "trade_plan": trade_plan,
            "status": "simulation_only",
            "auto_trading": False
        }

        for key in (
            "entry_price",
            "stop_loss",
            "tp1",
            "tp2",
            "take_profit",
            "reward_risk_ratio",
            "tp1_reward_risk_ratio",
            "tp2_reward_risk_ratio",
            "position"
        ):
            if key in trade_plan:
                candidate[key] = trade_plan[key]

        return candidate

    @staticmethod
    def _sort_candidates(candidates):
        candidates.sort(
            key=lambda item: (
                item.get("score", 0),
                item.get("symbol", "")
            ),
            reverse=True
        )

        return candidates

    def scan(self, equity=None):
        """
        執行一輪市場掃描。

        每個幣種獨立處理。
        單一幣種失敗不會中斷整輪掃描。
        """

        started_at = self._timestamp()
        empty_lists = self._empty_strategy_lists()

        try:
            symbols = self._get_symbols()

        except Exception as exc:
            return {
                "application": Config.APP_NAME,
                "status": "error",
                "error": str(exc),
                "started_at": started_at,
                "finished_at": self._timestamp(),
                "total_symbols": 0,
                "total_scanned": 0,
                "successful": 0,
                "failed": 0,
                "results": [],
                "long_candidates": [],
                "short_candidates": [],
                "strong_coins": [],
                **empty_lists,
                "auto_trading": False,
                "trading_mode": "simulation_only"
            }

        results = []

        for symbol in symbols:
            try:
                result = self.signal_engine.analyze_symbol(
                    symbol,
                    equity=equity
                )

                if not isinstance(result, dict):
                    results.append(
                        self._error_result(
                            symbol,
                            "Signal engine returned invalid result"
                        )
                    )
                    continue

                result = dict(result)

                result["symbol"] = result.get(
                    "symbol",
                    symbol
                )

                result["scan_symbol"] = symbol

                if result.get("status") not in (
                    "analyzed",
                    "error"
                ):
                    result["status"] = "error"
                    result["error"] = result.get(
                        "error",
                        "Unknown analysis status"
                    )
                    result["trade_plan"] = None
                    result["strategy_trade_plans"] = {}

                if result.get("status") == "error":
                    result["trade_plan"] = None
                    result["strategy_trade_plans"] = {}

                result["trading_mode"] = "simulation_only"
                result["auto_trading"] = False

                results.append(result)

            except Exception as exc:
                results.append(
                    self._error_result(symbol, exc)
                )

        successful = [
            item for item in results
            if item.get("status") == "analyzed"
        ]

        failed = [
            item for item in results
            if item.get("status") != "analyzed"
        ]

        long_candidates = []
        short_candidates = []
        strong_coins = []

        long_a_candidates = []
        long_b_candidates = []
        short_a_candidates = []
        short_b_candidates = []

        strategy_lists = {
            "LONG-A": long_a_candidates,
            "LONG-B": long_b_candidates,
            "SHORT-A": short_a_candidates,
            "SHORT-B": short_b_candidates
        }

        for item in successful:
            direction = self._get_direction(item)
            candidate = self._get_candidate(item)
            score = self._get_score(item)

            relative_strength = (
                self._get_relative_strength(item)
            )

            item["direction"] = direction
            item["score"] = score
            item["average_relative_strength_pct"] = (
                relative_strength
            )

            if (
                relative_strength is not None
                and relative_strength
                >= self.min_relative_strength
            ):
                strong_coins.append(item)

            # 保留舊版 LONG / SHORT 總排行榜。
            if candidate:
                if direction == "LONG":
                    long_candidates.append(item)

                elif direction == "SHORT":
                    short_candidates.append(item)

            # 四種策略獨立排行榜。
            signals = self._get_strategy_signals(item)

            for signal in signals:
                strategy_candidate = (
                    self._build_strategy_candidate(
                        item,
                        signal
                    )
                )

                if strategy_candidate is None:
                    continue

                strategy_name = (
                    strategy_candidate["strategy"]
                )

                strategy_lists[strategy_name].append(
                    strategy_candidate
                )

        long_candidates.sort(
            key=lambda item: item.get("score", 0),
            reverse=True
        )

        short_candidates.sort(
            key=lambda item: item.get("score", 0),
            reverse=True
        )

        strong_coins.sort(
            key=lambda item: (
                item.get(
                    "average_relative_strength_pct"
                ) or 0
            ),
            reverse=True
        )

        for candidates in strategy_lists.values():
            self._sort_candidates(candidates)

        return {
            "application": Config.APP_NAME,
            "status": "completed",
            "started_at": started_at,
            "finished_at": self._timestamp(),

            "total_symbols": len(symbols),
            "total_scanned": len(results),
            "successful": len(successful),
            "failed": len(failed),

            "long_count": len(long_candidates),
            "short_count": len(short_candidates),
            "strong_coin_count": len(strong_coins),

            "long_a_count": len(long_a_candidates),
            "long_b_count": len(long_b_candidates),
            "short_a_count": len(short_a_candidates),
            "short_b_count": len(short_b_candidates),

            "long_candidates": long_candidates,
            "short_candidates": short_candidates,
            "strong_coins": strong_coins,

            "long_a_candidates": long_a_candidates,
            "long_b_candidates": long_b_candidates,
            "short_a_candidates": short_a_candidates,
            "short_b_candidates": short_b_candidates,

            "results": results,

            "trading_mode": "simulation_only",
            "auto_trading": False
        }
