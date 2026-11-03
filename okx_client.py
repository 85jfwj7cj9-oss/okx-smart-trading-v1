
import os
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

    def _request(self, endpoint, params=None):
        url = self.base_url + endpoint

        try:
            response = self.session.get(
                url,
                params=params or {},
                timeout=self.timeout
            )

            response.raise_for_status()
            result = response.json()

        except requests.RequestException as exc:
            raise OKXAPIError(
                f"OKX network error: {exc}"
            ) from exc

        except ValueError as exc:
            raise OKXAPIError(
                "OKX returned invalid JSON"
            ) from exc

        if result.get("code") != "0":
            raise OKXAPIError(
                f"OKX API error: {result.get('code')} "
                f"{result.get('msg')}"
            )

        return result.get("data", [])

    def get_swap_instruments(self):
        data = self._request(
            "/api/v5/public/instruments",
            {"instType": "SWAP"}
        )

        return [
            item for item in data
            if item.get("settleCcy") == "USDT"
            and item.get("state") == "live"
            and item.get("instId", "").endswith("-USDT-SWAP")
        ]

    def get_tickers(self):
        return self._request(
            "/api/v5/market/tickers",
            {"instType": "SWAP"}
        )

    def get_ticker(self, inst_id):
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
        allowed_bars = {"1H", "4H", "1D", "1W"}

        if bar not in allowed_bars:
            raise ValueError(
                f"Unsupported timeframe: {bar}"
            )

        if not isinstance(limit, int) or not 1 <= limit <= 300:
            raise ValueError(
                "limit must be between 1 and 300"
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
            if len(item) < 9:
                continue

            confirm = str(item[8])

            if confirmed_only and confirm != "1":
                continue

            try:
                timestamp = int(item[0])

                candle = {
                    "timestamp": timestamp,
                    "datetime": datetime.fromtimestamp(
                        timestamp / 1000,
                        tz=timezone.utc
                    ).isoformat(),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                    "volume_currency": float(item[6]),
                    "volume_quote": float(item[7]),
                    "confirm": confirm
                }

                candles.append(candle)

            except (ValueError, TypeError):
                continue

        candles.sort(
            key=lambda item: item["timestamp"]
        )

        return candles
