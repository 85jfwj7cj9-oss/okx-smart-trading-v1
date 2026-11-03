
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

    @staticmethod
    def _get_score(result):
        strategy = result.get("strategy") or {}

        for key in ("score", "signal_score", "total_score"):
            value = strategy.get(key)

            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                continue

        return 0.0

    @staticmethod
    def _get_direction(result):
        strategy = result.get("strategy") or {}

        direction = str(
            strategy.get("direction", "")
        ).upper()

        if direction in ("LONG", "SHORT"):
            return direction

        return "NEUTRAL"

    @staticmethod
    def _get_candidate(result):
        strategy = result.get("strategy") or {}

        return bool(
            strategy.get(
                "candidate",
                strategy.get("is_candidate", False)
            )
        )

    @staticmethod
    def _get_relative_strength(result):
        relative = result.get("relative_strength") or {}

        values = []

        for timeframe in ("1H", "4H"):
            try:
                value = relative.get(timeframe)

                if value is not None:
                    values.append(float(value))

            except (TypeError, ValueError):
                continue

        if len(values) != 2:
            return None

        return round(sum(values) / len(values), 4)

    def _get_symbols(self):
        """
        依 24 小時估算成交額取得熱門 USDT 永續合約。
        """
        market_rows = self.market_data.get_top_symbols(
            limit=self.max_symbols
        )

        return [
            row["inst_id"]
            for row in market_rows
            if row.get("inst_id")
        ]

    def scan(self, equity=None):
        """
        執行一輪市場掃描。

        每個幣種獨立處理。
        單一幣種失敗不會中斷整輪掃描。
        """

        started_at = datetime.now(
            timezone.utc
        ).isoformat()

        try:
            symbols = self._get_symbols()

        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
                "started_at": started_at,
                "finished_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "total_scanned": 0,
                "results": [],
                "long_candidates": [],
                "short_candidates": [],
                "strong_coins": [],
                "auto_trading": False
            }

        results = []

        for symbol in symbols:
            try:
                result = self.signal_engine.analyze_symbol(
                    symbol,
                    equity=equity
                )

                if not isinstance(result, dict):
                    continue

                result["scan_symbol"] = symbol
                results.append(result)

            except Exception as exc:
                results.append({
                    "symbol": symbol,
                    "status": "error",
                    "error": str(exc),
                    "trade_plan": None,
                    "trading_mode": "simulation_only",
                    "auto_trading": False
                })

        successful = [
            item for item in results
            if item.get("status") == "analyzed"
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

            # 強勢幣名單：1H 與 4H 相對強度均有資料，
            # 且平均相對強度達到設定門檻。
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

        # 多空訊號優先依策略分數排序。
        long_candidates.sort(
            key=lambda item: item.get("score", 0),
            reverse=True
        )

        short_candidates.sort(
            key=lambda item: item.get("score", 0),
            reverse=True
        )

        # 強勢幣優先依 BTC 相對強度排序。
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
            "finished_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "total_symbols": len(symbols),
            "total_scanned": len(results),
            "successful": len(successful),
            "failed": len(results) - len(successful),
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
