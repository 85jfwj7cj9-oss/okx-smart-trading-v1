
import math
from datetime import datetime, timezone

from config import Config
from signal_engine import SignalEngine
from market_data import MarketData


class MarketScanner:
    """
    OKX SMART TRADING V1.0

    USDT 永續合約市場掃描器。
    僅分析行情與模擬交易訊號，不執行真實下單。
    """

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

        return bool(
            strategy.get(
                "candidate",
                strategy.get("is_candidate", False)
            )
        )

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

            inst_id = inst_id.strip()

            if not inst_id.endswith("-USDT-SWAP"):
                continue

            if inst_id in seen:
                continue

            seen.add(inst_id)
            symbols.append(inst_id)

        return symbols

    def _get_symbols(self):
        """
        依 24 小時估算成交額取得熱門 USDT 永續合約。
        """

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
            "trading_mode": "simulation_only",
            "auto_trading": False
        }

    def scan(self, equity=None):
        """
        執行一輪市場掃描。

        每個幣種獨立處理。
        單一幣種失敗不會中斷整輪掃描。
        """

        started_at = self._timestamp()

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

            if not candidate:
                continue

            if direction == "LONG":
                long_candidates.append(item)

            elif direction == "SHORT":
                short_candidates.append(item)

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
            "long_candidates": long_candidates,
            "short_candidates": short_candidates,
            "strong_coins": strong_coins,
            "results": results,
            "trading_mode": "simulation_only",
            "auto_trading": False
        }
