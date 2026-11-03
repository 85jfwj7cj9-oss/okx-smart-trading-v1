
from unittest.mock import Mock

import pytest

from scanner import MarketScanner


@pytest.fixture
def market_rows():
    return [
        {"inst_id": "BTC-USDT-SWAP"},
        {"inst_id": "ETH-USDT-SWAP"},
        {"inst_id": "SOL-USDT-SWAP"},
        {"inst_id": "XRP-USDT-SWAP"},
    ]


@pytest.fixture
def sample_results():
    return {
        "BTC-USDT-SWAP": {
            "symbol": "BTC-USDT-SWAP",
            "status": "analyzed",
            "direction": "LONG",
            "strategy": {
                "direction": "LONG",
                "candidate": True,
                "score": 85
            },
            "relative_strength": {
                "1H": 2.0,
                "4H": 4.0
            },
            "trade_plan": {
                "status": "simulation_only"
            }
        },
        "ETH-USDT-SWAP": {
            "symbol": "ETH-USDT-SWAP",
            "status": "analyzed",
            "direction": "SHORT",
            "strategy": {
                "direction": "SHORT",
                "candidate": True,
                "score": 75
            },
            "relative_strength": {
                "1H": -1.0,
                "4H": -2.0
            },
            "trade_plan": {
                "status": "simulation_only"
            }
        },
        "SOL-USDT-SWAP": {
            "symbol": "SOL-USDT-SWAP",
            "status": "analyzed",
            "direction": "LONG",
            "strategy": {
                "direction": "LONG",
                "candidate": False,
                "score": 65
            },
            "relative_strength": {
                "1H": 3.0,
                "4H": 5.0
            },
            "trade_plan": None
        },
        "XRP-USDT-SWAP": {
            "symbol": "XRP-USDT-SWAP",
            "status": "analyzed",
            "direction": "NEUTRAL",
            "strategy": {
                "direction": "NEUTRAL",
                "candidate": False,
                "score": 40
            },
            "relative_strength": {
                "1H": 0.5,
                "4H": 1.0
            },
            "trade_plan": None
        }
    }


@pytest.fixture
def scanner_setup(market_rows, sample_results):
    market_data = Mock()
    market_data.get_top_symbols.return_value = market_rows

    signal_engine = Mock()
    signal_engine.analyze_symbol.side_effect = (
        lambda symbol, equity=None:
        sample_results[symbol]
    )

    scanner = MarketScanner(
        market_data=market_data,
        signal_engine=signal_engine,
        max_symbols=4,
        min_relative_strength=0.0
    )

    return scanner, market_data, signal_engine


def test_get_symbols(scanner_setup):
    scanner, market_data, _ = scanner_setup

    symbols = scanner._get_symbols()

    assert len(symbols) == 4
    assert symbols[0] == "BTC-USDT-SWAP"
    market_data.get_top_symbols.assert_called_once_with(limit=4)


def test_scan_completed(scanner_setup):
    scanner, _, _ = scanner_setup

    result = scanner.scan()

    assert result["status"] == "completed"
    assert result["total_scanned"] == 4
    assert result["successful"] == 4
    assert result["failed"] == 0


def test_scan_long_candidates(scanner_setup):
    scanner, _, _ = scanner_setup

    result = scanner.scan()

    assert result["long_count"] == 1
    assert result["long_candidates"][0]["symbol"] == (
        "BTC-USDT-SWAP"
    )


def test_scan_short_candidates(scanner_setup):
    scanner, _, _ = scanner_setup

    result = scanner.scan()

    assert result["short_count"] == 1
    assert result["short_candidates"][0]["symbol"] == (
        "ETH-USDT-SWAP"
    )


def test_scan_strong_coins(scanner_setup):
    scanner, _, _ = scanner_setup

    result = scanner.scan()

    symbols = [
        item["symbol"]
        for item in result["strong_coins"]
    ]

    assert "BTC-USDT-SWAP" in symbols
    assert "SOL-USDT-SWAP" in symbols
    assert "ETH-USDT-SWAP" not in symbols


def test_strong_coins_sorted_by_relative_strength(
    scanner_setup
):
    scanner, _, _ = scanner_setup

    result = scanner.scan()

    strengths = [
        item["average_relative_strength_pct"]
        for item in result["strong_coins"]
    ]

    assert strengths == sorted(strengths, reverse=True)


def test_long_candidates_sorted_by_score(scanner_setup):
    scanner, _, signal_engine = scanner_setup

    signal_engine.analyze_symbol.side_effect = None
    signal_engine.analyze_symbol.side_effect = [
        {
            "symbol": "AAA-USDT-SWAP",
            "status": "analyzed",
            "strategy": {
                "direction": "LONG",
                "candidate": True,
                "score": 70
            },
            "relative_strength": {
                "1H": 1,
                "4H": 1
            }
        },
        {
            "symbol": "BBB-USDT-SWAP",
            "status": "analyzed",
            "strategy": {
                "direction": "LONG",
                "candidate": True,
                "score": 90
            },
            "relative_strength": {
                "1H": 2,
                "4H": 2
            }
        },
        {
            "symbol": "CCC-USDT-SWAP",
            "status": "analyzed",
            "strategy": {
                "direction": "NEUTRAL",
                "candidate": False,
                "score": 30
            },
            "relative_strength": {
                "1H": 0,
                "4H": 0
            }
        },
        {
            "symbol": "DDD-USDT-SWAP",
            "status": "analyzed",
            "strategy": {
                "direction": "NEUTRAL",
                "candidate": False,
                "score": 20
            },
            "relative_strength": {
                "1H": 0,
                "4H": 0
            }
        }
    ]

    result = scanner.scan()

    scores = [
        item["score"]
        for item in result["long_candidates"]
    ]

    assert scores == sorted(scores, reverse=True)


def test_single_symbol_failure_does_not_stop_scan(
    scanner_setup
):
    scanner, _, signal_engine = scanner_setup

    original_results = list(
        signal_engine.analyze_symbol.side_effect.__closure__
        or []
    )

    def analyze(symbol, equity=None):
        if symbol == "ETH-USDT-SWAP":
            raise RuntimeError("Test API failure")

        return {
            "symbol": symbol,
            "status": "analyzed",
            "strategy": {
                "direction": "NEUTRAL",
                "candidate": False,
                "score": 30
            },
            "relative_strength": {
                "1H": 1,
                "4H": 1
            }
        }

    signal_engine.analyze_symbol.side_effect = analyze

    result = scanner.scan()

    assert result["status"] == "completed"
    assert result["total_scanned"] == 4
    assert result["failed"] == 1
    assert result["successful"] == 3


def test_market_data_failure():
    market_data = Mock()
    market_data.get_top_symbols.side_effect = RuntimeError(
        "OKX connection failed"
    )

    scanner = MarketScanner(
        market_data=market_data,
        signal_engine=Mock()
    )

    result = scanner.scan()

    assert result["status"] == "error"
    assert result["total_scanned"] == 0
    assert result["auto_trading"] is False


def test_scan_does_not_enable_auto_trading(scanner_setup):
    scanner, _, _ = scanner_setup

    result = scanner.scan()

    assert result["auto_trading"] is False
    assert result["trading_mode"] == "simulation_only"


def test_max_symbols_is_limited(market_rows):
    market_data = Mock()
    market_data.get_top_symbols.return_value = market_rows

    scanner = MarketScanner(
        market_data=market_data,
        signal_engine=Mock(),
        max_symbols=500
    )

    assert scanner.max_symbols == 100
