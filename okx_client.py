
import pytest

from okx_client import OKXClient, OKXAPIError


class FakeResponse:
    def __init__(self, data, status_code=200):
        self.data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP error")

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        return self.response


def make_client(data):
    client = OKXClient()
    response = FakeResponse(data)
    client.session = FakeSession(response)
    return client


def test_get_ticker():
    client = make_client({
        "code": "0",
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "last": "95000"
            }
        ]
    })

    result = client.get_ticker("BTC-USDT-SWAP")

    assert result["instId"] == "BTC-USDT-SWAP"
    assert float(result["last"]) == 95000


def test_get_ticker_empty():
    client = make_client({
        "code": "0",
        "data": []
    })

    with pytest.raises(OKXAPIError):
        client.get_ticker("BTC-USDT-SWAP")


def test_invalid_timeframe():
    client = OKXClient()

    with pytest.raises(ValueError):
        client.get_candles(
            "BTC-USDT-SWAP",
            bar="2H"
        )


def test_invalid_candle_limit():
    client = OKXClient()

    with pytest.raises(ValueError):
        client.get_candles(
            "BTC-USDT-SWAP",
            bar="1H",
            limit=500
        )


def test_okx_api_error():
    client = make_client({
        "code": "50000",
        "msg": "Test error",
        "data": []
    })

    with pytest.raises(OKXAPIError):
        client.get_tickers()


def test_get_candles_confirmed_only():
    client = make_client({
        "code": "0",
        "data": [
            [
                "1791000000000",
                "100",
                "110",
                "90",
                "105",
                "1000",
                "1000",
                "100000",
                "1"
            ],
            [
                "1791003600000",
                "105",
                "115",
                "100",
                "110",
                "1200",
                "1200",
                "130000",
                "0"
            ]
        ]
    })

    candles = client.get_candles(
        "BTC-USDT-SWAP",
        bar="1H",
        limit=100,
        confirmed_only=True
    )

    assert len(candles) == 1
    assert candles[0]["confirm"] == "1"
    assert candles[0]["close"] == 105.0


def test_get_candles_include_unconfirmed():
    client = make_client({
        "code": "0",
        "data": [
            [
                "1791000000000",
                "100",
                "110",
                "90",
                "105",
                "1000",
                "1000",
                "100000",
                "1"
            ],
            [
                "1791003600000",
                "105",
                "115",
                "100",
                "110",
                "1200",
                "1200",
                "130000",
                "0"
            ]
        ]
    })

    candles = client.get_candles(
        "BTC-USDT-SWAP",
        bar="1H",
        limit=100,
        confirmed_only=False
    )

    assert len(candles) == 2


                
