
import os
import math
import time
from datetime import datetime, timezone

import requests


class OKXAPIError(Exception):
    """OKX API request or response error."""
    pass


class OKXClient:
    ALLOWED_BARS = {"1H", "4H", "1D", "1W"}

    def __init__(self):
        self.base_url = os.getenv(
            "OKX_BASE_URL",
            "https://www.okx.com"
        ).rstrip("/")

        self.timeout = float(os.getenv("OKX_TIMEOUT", "15"))
        self.max_retries = max(
            0, int(os.getenv("OKX_MAX_RETRIES", "2"))
        )
        self.retry_backoff = max(
            0.0, float(os.getenv("OKX_RETRY_BACKOFF", "0.5"))
        )
        self.min_request_interval = max(
            0.0, float(os.getenv("OKX_MIN_REQUEST_INTERVAL", "0.1"))
        )

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OKX-SMART-TRADING-V1.0"
        })

        self._last_request_time = 0.0

    @staticmethod
    def _is_valid_swap_id(inst_id):
        return (
            isinstance(inst_id, str)
            and inst_id.endswith("-USDT-SWAP")
            and len(inst_id) > len("-USDT-SWAP")
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

    def _wait_for_rate_limit(self):
        now = time.monotonic()
        elapsed = now - self._last_request_time
        wait_time = self.min_request_interval - elapsed

        if wait_time > 0:
            time.sleep(wait_time)

        self._last_request_time = time.monotonic()

    def _request(self, endpoint, params=None):
        url = self.base_url + endpoint
        last_error = None

        for attempt in range(self.max_retries + 1):
            self._wait_for_rate_limit()

            try:
                response = self.session.get(
                    url,
                    params=params or {},
                    timeout=self.timeout
                )

                response.raise_for_status()

                result = response.json()

            except requests.RequestException as exc:
                last_error = exc

                if attempt >= self.max_retries:
                    break

                time.sleep(self.retry_backoff * (2 ** attempt))
                continue

            except ValueError as exc:
                raise OKXAPIError(
                    "OKX returned invalid JSON"
                ) from exc

            except Exception as exc:
                raise OKXAPIError(
                    f"OKX request failed: {exc}"
                ) from exc

            if not isinstance(result, dict):
                raise OKXAPIError(
                    "OKX returned an invalid response format"
                )

            code = str(result.get("code", ""))

            if code != "0":
                message = (
                    f"OKX API error: {code} "
                    f"{result.get('msg', 'Unknown error')}"
                )

                # OKX 常見限流錯誤碼。
                if code in {"50011", "50040"} and attempt < self.max_retries:
                    time.sleep(
                        self.retry_backoff * (2 ** attempt)
                    )
                    continue

                raise OKXAPIError(message)

            data = result.get("data", [])

            if not isinstance(data, list):
                raise OKXAPIError(
                    "OKX response data is not a list"
                )

            return data

        raise OKXAPIError(
            f"OKX network error after retries: {last_error}"
        ) from last_error

    def get_swap_instruments(self):
        data = self._request(
            "/api/v5/public/instruments",
            {"instType": "SWAP"}
        )

        instruments = []

        for item in data:
            if not isinstance(item, dict):
                continue

            inst_id = item.get("instId", "")

            if item.get("settleCcy") != "USDT":
                continue

            if item.get("state") != "live":
                continue

            if item.get("ctType") != "linear":
                continue

            if not self._is_valid_swap_id(inst_id):
                continue

            instruments.append(item)

        return instruments

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

        if not data or not isinstance(data[0], dict):
            raise OKXAPIError(
                f"No ticker data for {inst_id}"
            )

        ticker = data[0]

        if ticker.get("instId") != inst_id:
            raise OKXAPIError(
                f"Ticker instrument mismatch for {inst_id}"
            )

        last = self._safe_float(ticker.get("last"))

        if last is None or last <= 0:
            raise OKXAPIError(
                f"Invalid ticker price for {inst_id}"
            )

        return ticker

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

        if bar not in self.ALLOWED_BARS:
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

        candles_by_timestamp = {}

        now_ms = int(time.time() * 1000)
        max_future_ms = now_ms + 5 * 60 * 1000

        for item in data:
            if not isinstance(item, (list, tuple)):
                continue

            if len(item) < 9:
                continue

            confirm = str(item[8])

            if confirm not in {"0", "1"}:
                continue

            if confirmed_only and confirm != "1":
                continue

            try:
                timestamp = int(item[0])

                if timestamp <= 0 or timestamp > max_future_ms:
                    continue

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

                candles_by_timestamp[timestamp] = {
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
                }

            except (ValueError, TypeError, OverflowError, OSError):
                continue

        candles = sorted(
            candles_by_timestamp.values(),
            key=lambda item: item["timestamp"]
        )

        return candles

    @staticmethod
    def get_data_freshness(timestamp_ms, max_age_seconds=120):
        """
        檢查行情時間戳記是否過期。
        timestamp_ms 使用毫秒。
        """
        try:
            timestamp_ms = int(timestamp_ms)
        except (TypeError, ValueError):
            return {
                "valid": False,
                "age_seconds": None,
                "reason": "invalid_timestamp"
            }

        if timestamp_ms <= 0:
            return {
                "valid": False,
                "age_seconds": None,
                "reason": "invalid_timestamp"
            }

        age_seconds = time.time() - timestamp_ms / 1000

        if age_seconds < -300:
            return {
                "valid": False,
                "age_seconds": round(age_seconds, 2),
                "reason": "future_timestamp"
            }

        if age_seconds > max_age_seconds:
            return {
                "valid": False,
                "age_seconds": round(age_seconds, 2),
                "reason": "stale_data"
            }

        return {
            "valid": True,
            "age_seconds": round(max(0, age_seconds), 2),
            "reason": "fresh"
        }
