
import os
import math
from datetime import datetime, timezone

import requests


class OKXAPIError(Exception):
    """OKX API request or response error."""
    pass


class OKXClient:
    def __init__(self):
        self.base_url = os.getenv(
            "OKX_BASE_URL",
            "https://www.okx.com"
        ).rstrip("/")

        self.timeout = 15
        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": "OKX-SMART-TRADING-V1.0"
        })

    @staticmethod
    def _is_valid_swap_id(inst_id):
        return (
            isinstance(inst_id, str)
            and inst_id.endswith("-USDT-SWAP")
        )

    @staticmethod
    def _safe_float(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        if not math.isfinite(number):
            return None

        return number

    def _request(self, endpoint, params=None):
        url = self.base_url + endpoint

        try:
            response = self.session.get(
                url,
                params=params or {},
                timeout=self.timeout
            )

            response.raise_for_status()

        except requests.RequestException as exc:
            raise OKXAPIError(
                f"OKX network error: {exc}"
            ) from exc

        try:
            result = response.json()

        except ValueError as exc:
            raise OKXAPIError(
                "OKX returned invalid JSON"
            ) from exc

        if not isinstance(result, dict):
            raise OKXAPIError(
                "OKX returned an invalid response format"
            )

        code = str(result.get("code", ""))

        if code != "0":
            raise OKXAPIError(
                f"OKX API error: {code} "
                f"{result.get('msg', 'Unknown error')}"
            )

        data = result.get("data", [])

        if not isinstance(data, list):
            raise OKXAPIError(
                "OKX response data is not a list"
            )

        return data

    def get_swap_instruments(self):
        data = self._request(
            "/api/v5/public/instruments",
            {"instType": "SWAP"}
        )

        return [
            item for item in data
            if isinstance(item, dict)
            and item.get("settleCcy") == "USDT"
            and item.get("state") == "live"
            and self._is_valid_swap_id(
                item.get("instId", "")
            )
        ]

    def get_tickers(self):
        return self._request(
            "/api/v5/market/tickers",
            {"instType": "SWAP"}
        )

    def get_ticker(self, inst_id):
        if not self._is_valid_swap_id(inst_id):
            raise ValueError(
                "Only USDT perpetual contracts are supported"
            )

        data = self._request(
            "/api/v5/market/ticker",
            {"instId": inst_id}
        )

        if not data:
            raise OKXAPIError(
                f"No ticker data for {inst_id}"
            )

        return data[0]

    def get_candles(
        self,
        inst_id,
        bar="1H",
        limit=100,
        confirmed_only=True
    ):
        if not self._is_valid_swap_id(inst_id):
            raise ValueError(
                "Only USDT perpetual contracts are supported"
            )

        allowed_bars = {
            "1H", "4H", "1D", "1W"
        }

        if bar not in allowed_bars:
            raise ValueError(
                f"Unsupported timeframe: {bar}"
            )

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 300
        ):
            raise ValueError(
                "limit must be an integer between 1 and 300"
            )

        data = self._request(
            "/api/v5/market/candles",
            {
                "instId": inst_id,
                "bar": bar,
                "limit": str(limit)
            }
        )

        candles = []

        for item in data:
            if not isinstance(item, (list, tuple)):
                continue

            if len(item) < 9:
                continue

            confirm = str(item[8])

            if confirmed_only and confirm != "1":
                continue

            try:
                timestamp = int(item[0])

                open_price = self._safe_float(item[1])
                high_price = self._safe_float(item[2])
                low_price = self._safe_float(item[3])
                close_price = self._safe_float(item[4])
                volume = self._safe_float(item[5])
                volume_currency = self._safe_float(item[6])
                volume_quote = self._safe_float(item[7])

                values = [
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume,
                    volume_currency,
                    volume_quote
                ]

                if any(value is None for value in values):
                    continue

                if min(
                    open_price,
                    high_price,
                    low_price,
                    close_price
                ) <= 0:
                    continue

                if high_price < max(open_price, close_price):
                    continue

                if low_price > min(open_price, close_price):
                    continue

                if low_price > high_price:
                    continue

                if min(
                    volume,
                    volume_currency,
                    volume_quote
                ) < 0:
                    continue

                candles.append({
                    "timestamp": timestamp,
                    "datetime": datetime.fromtimestamp(
                        timestamp / 1000,
                        tz=timezone.utc
                    ).isoformat(),
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                    "volume": volume,
                    "volume_currency": volume_currency,
                    "volume_quote": volume_quote,
                    "confirm": confirm
                })

            except (ValueError, TypeError, OverflowError):
                continue

        # OKX 原始 K 線通常由新到舊排列，
        # 統一整理成舊到新。
        candles.sort(
            key=lambda item: item["timestamp"]
        )

        return candles
