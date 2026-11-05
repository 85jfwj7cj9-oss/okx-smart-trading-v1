
import time

import pytest
import requests

from okx_client import OKXAPIError, OKXClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses=None, exceptions=None):
        self.responses = list(responses or [])
        self.exceptions = list(exceptions or [])
        self.headers = {}

    def get(self, *args, **kwargs):
        if self.exceptions:
            raise self.exceptions.pop(0)

        if self.responses:
            return self.responses.pop(0)

        raise RuntimeError("No fake response configured")


def make_client():
    return OKXClient()


def test_get_ticker():
    client = make_client()
    client.session = FakeSession([
        FakeResponse({
            "code": "0",
            "data": [{
                "instId": "BTC-USDT-SWAP",
                "last": "95000",
            }],
        })
    ])

    result = client.get_ticker("BTC-USDT-SWAP")

    assert result["last"] == "95000"
    assert result["instId"] == "BTC-USDT-SWAP"


def test_get_ticker_rejects_invalid_symbol():
    client = make_client()

    with pytest.raises(ValueError):
        client.get_ticker("BTC-USDT")


def test_okx_api_error():
    client = make_client()
    client.session = FakeSession([
        FakeResponse({
            "code": "50000",
            "msg": "API error",
            "data": [],
        })
    ])

    with pytest.raises(OKXAPIError):
        client.get_ticker("BTC-USDT-SWAP")


def test_get_swap_instruments_filters_linear_usdt():
    client = make_client()
    client.session = FakeSession([
        FakeResponse({
            "code": "0",
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "settleCcy": "USDT",
                    "state": "live",
                    "ctType": "linear",
                },
                {
                    "instId": "BTC-USD-SWAP",
                    "settleCcy": "USD",
                    "state": "live",
                    "ctType": "inverse",
                },
                {
                    "instId": "ETH-USDT-SWAP",
                    "settleCcy": "USDT",
                    "state": "suspend",
                    "ctType": "linear",
                },
            ],
        })
    ])

    result = client.get_swap_instruments()

    assert len(result) == 1
    assert result[0]["instId"] == "BTC-USDT-SWAP"


def test_get_candles_sorts_and_removes_duplicates():
    client = make_client()
    client.session = FakeSession([
        FakeResponse({
            "code": "0",
            "data": [
                [
                    "1791003600000", "101", "103", "100",
                    "102", "10", "1000", "1000", "1"
                ],
                [
                    "1791000000000", "99", "101", "98",
                    "100", "8", "800", "800", "1"
                ],
                [
                    "1791000000000", "99", "101", "98",
                    "100", "8", "800", "800", "1"
                ],
            ],
        })
    ])

    result = client.get_candles(
        "BTC-USDT-SWAP",
        bar="1H",
        limit=100,
        confirmed_only=True,
    )

    assert len(result) == 2
    assert result[0]["timestamp"] < result[1]["timestamp"]
    assert result[0]["close"] == 100
    assert result[1]["close"] == 102


def test_get_candles_rejects_invalid_timeframe():
    client = make_client()

    with pytest.raises(ValueError):
        client.get_candles(
            "BTC-USDT-SWAP",
            bar="5m"
        )


def test_get_candles_can_include_unclosed_candle():
    client = make_client()
    client.session = FakeSession([
        FakeResponse({
            "code": "0",
            "data": [
                [
                    "1791000000000", "99", "101", "98",
                    "100", "8", "800", "800", "0"
                ],
            ],
        })
    ])

    result = client.get_candles(
        "BTC-USDT-SWAP",
        bar="1H",
        limit=100,
        confirmed_only=False,
    )

    assert len(result) == 1
    assert result[0]["confirm"] == "0"


def test_get_candles_excludes_unclosed_candle():
    client = make_client()
    client.session = FakeSession([
        FakeResponse({
            "code": "0",
            "data": [
                [
                    "1791000000000", "99", "101", "98",
                    "100", "8", "800", "800", "0"
                ],
            ],
        })
    ])

    result = client.get_candles(
        "BTC-USDT-SWAP",
        bar="1H",
        limit=100,
        confirmed_only=True,
    )

    assert result == []


def test_api_retries_after_network_error():
    client = make_client()
    client.max_retries = 2
    client.retry_backoff = 0
    client.min_request_interval = 0

    client.session = FakeSession(
        responses=[
            FakeResponse({
                "code": "0",
                "data": [{
                    "instId": "BTC-USDT-SWAP",
                    "last": "95000",
                }],
            })
        ],
        exceptions=[
            requests.Timeout("temporary timeout")
        ],
    )

    result = client.get_ticker("BTC-USDT-SWAP")

    assert result["last"] == "95000"


def test_get_data_freshness():
    now_ms = int(time.time() * 1000)

    fresh_result = OKXClient.get_data_freshness(
        now_ms,
        max_age_seconds=120,
    )

    stale_result = OKXClient.get_data_freshness(
        now_ms - 600000,
        max_age_seconds=120,
    )

    assert fresh_result["valid"] is True
    assert fresh_result["reason"] == "fresh"

    assert stale_result["valid"] is False
    assert stale_result["reason"] == "stale_data"


def test_get_data_freshness_rejects_invalid_timestamp():
    result = OKXClient.get_data_freshness(
        "invalid",
        max_age_seconds=120,
    )

    assert result["valid"] is False
    assert result["reason"] == "invalid_timestamp"


def test_get_data_freshness_rejects_future_timestamp():
    future_ms = int(time.time() * 1000) + 600000

    result = OKXClient.get_data_freshness(
        future_ms,
        max_age_seconds=120,
    )

    assert result["valid"] is False
    assert result["reason"] == "future_timestamp"
