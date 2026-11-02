
from okx_client import OKXClient
from config import Config


class MarketData:
    def __init__(self, client=None):
        self.client = client or OKXClient()
        self.btc_symbol = Config.BTC_BENCHMARK

    def get_usdt_swap_universe(self):
        """取得可交易的 USDT 永續合約。"""
        instruments = self.client.get_swap_instruments()

        return [
            item for item in instruments
            if item.get("instId", "").endswith("-USDT-SWAP")
            and item.get("settleCcy") == "USDT"
            and item.get("state") == "live"
        ]

    def get_market_overview(self):
        """整理行情，依估算 USDT 成交額排序。"""
        instruments = self.get_usdt_swap_universe()
        tickers = self.client.get_tickers()

        allowed = {
            item["instId"] for item in instruments
        }

        rows = []

        for ticker in tickers:
            inst_id = ticker.get("instId")

            if inst_id not in allowed:
                continue

            try:
                last = float(ticker.get("last", 0))
                open_24h = float(ticker.get("open24h", 0))
                volume_base = float(
                    ticker.get("volCcy24h", 0)
                )

                if last <= 0:
                    continue

                change_pct = None
                if open_24h > 0:
                    change_pct = (
                        last / open_24h - 1
                    ) * 100

                # 暫用基礎幣數量 × 最新價格估算 USDT 成交額。
                # 這是估算值，不是交易所提供的精確成交額。
                turnover_estimated = volume_base * last

                rows.append({
                    "inst_id": inst_id,
                    "last": last,
                    "volume_base_24h": volume_base,
                    "turnover_estimated_usdt_24h":
                        turnover_estimated,
                    "change_24h_pct": (
                        round(change_pct, 4)
                        if change_pct is not None
                        else None
                    ),
                    "high_24h": float(
                        ticker.get("high24h", 0)
                    ),
                    "low_24h": float(
                        ticker.get("low24h", 0)
                    ),
                })

            except (TypeError, ValueError):
                continue

        rows.sort(
            key=lambda row:
                row["turnover_estimated_usdt_24h"],
            reverse=True
        )

        return rows

    def get_top_symbols(self, limit=None):
        if limit is None:
            limit = Config.TOP_N_SYMBOLS

        if limit <= 0:
            raise ValueError("limit must be positive")

        return self.get_market_overview()[:limit]

    @staticmethod
    def calculate_return(candles, lookback=20):
        """計算已收盤 K 線區間報酬率。"""
        if lookback < 1 or len(candles) <= lookback:
            return None

        start_price = candles[-lookback - 1]["close"]
        end_price = candles[-1]["close"]

        if start_price <= 0:
            return None

        return (end_price / start_price - 1) * 100

    @staticmethod
    def align_candles(asset_candles, btc_candles):
        """只比較相同時間戳的 K 線。"""
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

        if lookback < 1 or len(aligned) <= lookback:
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

        result = {}

        for timeframe in timeframes:
            asset_candles = self.client.get_candles(
                inst_id,
                bar=timeframe,
                limit=limit,
                confirmed_only=True
            )

            btc_candles = self.client.get_candles(
                self.btc_symbol,
                bar=timeframe,
                limit=limit,
                confirmed_only=True
            )

            result[timeframe] = (
                self.calculate_relative_strength(
                    asset_candles,
                    btc_candles,
                    lookback=20
                )
            )

        return result

    def get_market_snapshot(self):
        """取得市場摘要。"""
        rows = self.get_top_symbols()
        btc = self.client.get_ticker(self.btc_symbol)

        return {
            "symbol_count": len(rows),
            "btc": {
                "inst_id": self.btc_symbol,
                "last": float(btc["last"])
            },
            "top_symbols": rows,
            "turnover_note":
                "24h USDT turnover is estimated, not exact"
        }
