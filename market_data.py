
import math

from okx_client import OKXClient
from config import Config


class MarketData:
    def __init__(self, client=None):
        self.client = client or OKXClient()
        self.btc_symbol = Config.BTC_BENCHMARK

    @staticmethod
    def _valid_number(value, default=None):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default

        if not math.isfinite(number):
            return default

        return number

    @staticmethod
    def _valid_candles(candles):
        """整理有效 K 線，依時間由舊到新排列。"""
        if not isinstance(candles, list):
            return []

        result = []

        for item in candles:
            if not isinstance(item, dict):
                continue

            try:
                timestamp = int(item["timestamp"])
                close_price = float(item["close"])

                if not math.isfinite(close_price):
                    continue

                if close_price <= 0:
                    continue

                # 完整 OHLC 資料才執行完整價格驗證。
                # 測試或簡化資料允許只有 timestamp、close。
                ohlc_keys = ("open", "high", "low", "close")

                if all(key in item for key in ohlc_keys):
                    open_price = float(item["open"])
                    high_price = float(item["high"])
                    low_price = float(item["low"])

                    values = [
                        open_price,
                        high_price,
                        low_price,
                        close_price
                    ]

                    if not all(math.isfinite(v) for v in values):
                        continue

                    if min(values) <= 0:
                        continue

                    if high_price < max(open_price, close_price):
                        continue

                    if low_price > min(open_price, close_price):
                        continue

                    if low_price > high_price:
                        continue

                result.append({
                    **item,
                    "timestamp": timestamp,
                    "close": close_price
                })

            except (KeyError, TypeError, ValueError, OverflowError):
                continue

        result.sort(key=lambda item: item["timestamp"])

        # 相同時間戳只保留最後一筆。
        unique = {}

        for item in result:
            unique[item["timestamp"]] = item

        return list(unique.values())

    def get_usdt_swap_universe(self):
        """取得可交易的 USDT 永續合約。"""
        instruments = self.client.get_swap_instruments()

        if not isinstance(instruments, list):
            return []

        return [
            item for item in instruments
            if isinstance(item, dict)
            and item.get("instId", "").endswith("-USDT-SWAP")
            and item.get("settleCcy") == "USDT"
            and item.get("state") == "live"
        ]

    def get_market_overview(self):
        """整理行情，依 USDT 成交額排序。"""
        instruments = self.get_usdt_swap_universe()
        tickers = self.client.get_tickers()

        allowed = {
            item["instId"]
            for item in instruments
            if item.get("instId")
        }

        rows = []

        for ticker in tickers:
            if not isinstance(ticker, dict):
                continue

            inst_id = ticker.get("instId")

            if inst_id not in allowed:
                continue

            last = self._valid_number(ticker.get("last"))
            open_24h = self._valid_number(
                ticker.get("open24h"), 0
            )
            volume_base = self._valid_number(
                ticker.get("volCcy24h"), 0
            )

            if last is None or last <= 0:
                continue

            if volume_base < 0:
                continue

            change_pct = None

            if open_24h is not None and open_24h > 0:
                change_pct = (
                    last / open_24h - 1
                ) * 100

            quote_volume = self._valid_number(
                ticker.get("volCcyQuote24h")
            )

            if quote_volume is not None and quote_volume >= 0:
                turnover = quote_volume
                turnover_source = "exchange_quote_volume"
            else:
                turnover = volume_base * last
                turnover_source = "estimated"

            high_24h = self._valid_number(
                ticker.get("high24h"), 0
            )
            low_24h = self._valid_number(
                ticker.get("low24h"), 0
            )

            rows.append({
                "inst_id": inst_id,
                "last": last,
                "volume_base_24h": volume_base,
                "turnover_estimated_usdt_24h": turnover,
                "turnover_source": turnover_source,
                "change_24h_pct": (
                    round(change_pct, 4)
                    if change_pct is not None
                    else None
                ),
                "high_24h": high_24h,
                "low_24h": low_24h
            })

        rows.sort(
            key=lambda row: row[
                "turnover_estimated_usdt_24h"
            ],
            reverse=True
        )

        return rows

    def get_top_symbols(self, limit=None):
        if limit is None:
            limit = Config.TOP_N_SYMBOLS

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
        ):
            raise ValueError("limit must be a positive integer")

        return self.get_market_overview()[:limit]

    @staticmethod
    def calculate_return(candles, lookback=20):
        """計算已收盤 K 線區間報酬率。"""
        candles = MarketData._valid_candles(candles)

        if (
            isinstance(lookback, bool)
            or not isinstance(lookback, int)
            or lookback < 1
            or len(candles) <= lookback
        ):
            return None

        start_price = candles[-lookback - 1]["close"]
        end_price = candles[-1]["close"]

        if start_price <= 0:
            return None

        return (end_price / start_price - 1) * 100

    @staticmethod
    def align_candles(asset_candles, btc_candles):
        """只比較相同時間戳的 K 線。"""
        asset_candles = MarketData._valid_candles(
            asset_candles
        )

        btc_candles = MarketData._valid_candles(
            btc_candles
        )

        asset_map = {
            item["timestamp"]: item
            for item in asset_candles
        }

        btc_map = {
            item["timestamp"]: item
            for item in btc_candles
        }

        common = sorted(
            set(asset_map) & set(btc_map)
        )

        return [
            (asset_map[t], btc_map[t])
            for t in common
        ]

    def calculate_relative_strength(
        self,
        asset_candles,
        btc_candles,
        lookback=20
    ):
        """相對強度 = 幣種報酬率 - BTC 報酬率。"""
        aligned = self.align_candles(
            asset_candles,
            btc_candles
        )

        if (
            isinstance(lookback, bool)
            or not isinstance(lookback, int)
            or lookback < 1
            or len(aligned) <= lookback
        ):
            return None

        asset_start = aligned[-lookback - 1][0]["close"]
        asset_end = aligned[-1][0]["close"]

        btc_start = aligned[-lookback - 1][1]["close"]
        btc_end = aligned[-1][1]["close"]

        if min(
            asset_start,
            asset_end,
            btc_start,
            btc_end
        ) <= 0:
            return None

        asset_return = (
            asset_end / asset_start - 1
        ) * 100

        btc_return = (
            btc_end / btc_start - 1
        ) * 100

        return {
            "asset_return_pct": round(asset_return, 4),
            "btc_return_pct": round(btc_return, 4),
            "relative_strength_pct": round(
                asset_return - btc_return, 4
            ),
            "matched_candles": len(aligned),
            "lookback": lookback
        }

    def get_multi_timeframe_relative_strength(
        self,
        inst_id,
        timeframes=("1H", "4H"),
        limit=100
    ):
        """取得不同週期的 BTC 相對強度。"""
        if inst_id == self.btc_symbol:
            return {}

        if not isinstance(timeframes, (list, tuple)):
            raise ValueError(
                "timeframes must be a list or tuple"
            )

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 300
        ):
            raise ValueError(
                "limit must be between 1 and 300"
            )

        result = {}
        btc_cache = {}

        for timeframe in timeframes:
            if timeframe not in ("1H", "4H"):
                raise ValueError(
                    f"Unsupported timeframe: {timeframe}"
                )

            asset_candles = self.client.get_candles(
                inst_id,
                bar=timeframe,
                limit=limit,
                confirmed_only=True
            )

            if timeframe not in btc_cache:
                btc_cache[timeframe] = (
                    self.client.get_candles(
                        self.btc_symbol,
                        bar=timeframe,
                        limit=limit,
                        confirmed_only=True
                    )
                )

            result[timeframe] = (
                self.calculate_relative_strength(
                    asset_candles,
                    btc_cache[timeframe],
                    lookback=20
                )
            )

        return result

    def get_market_snapshot(self):
        """取得市場摘要。"""
        rows = self.get_top_symbols()
        btc = self.client.get_ticker(self.btc_symbol)

        btc_last = self._valid_number(
            btc.get("last")
        )

        if btc_last is None or btc_last <= 0:
            raise ValueError("Invalid BTC ticker price")

        return {
            "symbol_count": len(rows),
            "btc": {
                "inst_id": self.btc_symbol,
                "last": btc_last
            },
            "top_symbols": rows,
            "turnover_note":
                "Turnover uses exchange quote volume when available; otherwise estimated"
        }
