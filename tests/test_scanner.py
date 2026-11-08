
import pytest

from scanner import MarketScanner


class FakeMarketData:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.requested_limit = None

    def get_top_symbols(self, limit=20):
        self.requested_limit = limit
        if self.error:
            raise RuntimeError(self.error)
        return self.rows


class FakeSignalEngine:
    def __init__(self, results=None, errors=None):
        self.results = results or {}
        self.errors = errors or {}

    def analyze_symbol(self, symbol, equity=None):
        if symbol in self.errors:
            raise RuntimeError(self.errors[symbol])
        return self.results.get(symbol, {
            "status": "analyzed",
            "strategy": {},
            "relative_strength": {}
        })


def make_result(
    symbol="BTC-USDT-SWAP",
    score=85,
    direction="LONG",
    candidate=True,
    relative_1h=2.0,
    relative_4h=4.0,
    signals=None
):
    return {
        "symbol": symbol,
        "status": "analyzed",
        "strategy": {
            "score": score,
            "direction": direction,
            "candidate": candidate,
            "signals": signals or []
        },
        "relative_strength": {
            "1H": {
                "relative_strength_pct": relative_1h
            },
            "4H": {
                "relative_strength_pct": relative_4h
            }
        },
        "trade_plan": None,
        "strategy_trade_plans": {}
    }


def make_signal(name="LONG-A", direction="LONG", score=85):
    return {
        "signal": name,
        "direction": direction,
        "score": score,
        "price": 100,
        "reasons": ["test reason"],
        "timeframes": {"1H": "bullish", "4H": "bullish"},
        "trade_plan": {
            "direction": direction,
            "entry_price": 100,
            "stop_loss": 95,
            "tp1": 110,
            "tp2": 120,
            "reward_risk_ratio": 2.0
        }
    }


def test_constructor_caps_max_symbols_at_100():
    scanner = MarketScanner(
        market_data=FakeMarketData(),
        signal_engine=FakeSignalEngine(),
        max_symbols=200
    )
    assert scanner.max_symbols == 100


def test_constructor_minimum_max_symbols_is_one():
    scanner = MarketScanner(
        market_data=FakeMarketData(),
        signal_engine=FakeSignalEngine(),
        max_symbols=0
    )
    assert scanner.max_symbols == 1


def test_constructor_rejects_non_finite_relative_strength():
    with pytest.raises(ValueError):
        MarketScanner(
            market_data=FakeMarketData(),
            signal_engine=FakeSignalEngine(),
            min_relative_strength=float("nan")
        )


def test_symbols_filter_only_usdt_swaps_and_remove_duplicates():
    rows = [
        {"inst_id": "BTC-USDT-SWAP"},
        {"inst_id": "ETH-USDT-SWAP"},
        {"inst_id": "BTC-USDT-SWAP"},
        {"inst_id": "BTC-USDC-SWAP"},
        {"inst_id": "BTC-USDT"},
        {"inst_id": None},
        "invalid"
    ]

    symbols = MarketScanner._get_symbols_from_rows(rows)

    assert symbols == [
        "BTC-USDT-SWAP",
        "ETH-USDT-SWAP"
    ]


def test_symbols_reject_non_list_market_data():
    with pytest.raises(ValueError):
        MarketScanner._get_symbols_from_rows(None)


def test_relative_strength_supports_nested_format():
    result = {
        "relative_strength": {
            "1H": {"relative_strength_pct": 2.5},
            "4H": {"relative_strength_pct": 4.5}
        }
    }

    assert MarketScanner._get_relative_strength(result) == 3.5


def test_relative_strength_supports_legacy_numeric_format():
    result = {
        "relative_strength": {
            "1H": 2.0,
            "4H": 4.0
        }
    }

    assert MarketScanner._get_relative_strength(result) == 3.0


def test_relative_strength_missing_timeframe_returns_none():
    result = {
        "relative_strength": {
            "1H": 2.0
        }
    }

    assert MarketScanner._get_relative_strength(result) is None


def test_score_rejects_invalid_result():
    assert MarketScanner._get_score(None) == 0.0


def test_direction_normalizes_to_uppercase():
    result = {
        "strategy": {
            "direction": "long"
        }
    }

    assert MarketScanner._get_direction(result) == "LONG"


def test_strategy_candidate_requires_valid_strategy():
    item = {"symbol": "BTC-USDT-SWAP"}

    assert MarketScanner._build_strategy_candidate(
        item,
        {"signal": "UNKNOWN", "direction": "LONG", "score": 80}
    ) is None


def test_strategy_candidate_rejects_wrong_direction():
    item = {"symbol": "BTC-USDT-SWAP"}

    assert MarketScanner._build_strategy_candidate(
        item,
        make_signal("LONG-A", "SHORT")
    ) is None


def test_strategy_candidate_rejects_invalid_score():
    item = {"symbol": "BTC-USDT-SWAP"}

    assert MarketScanner._build_strategy_candidate(
        item,
        make_signal(score=150)
    ) is None


def test_strategy_candidate_copies_trade_plan():
    item = {"symbol": "BTC-USDT-SWAP"}
    signal = make_signal()

    candidate = MarketScanner._build_strategy_candidate(
        item,
        signal
    )

    assert candidate is not None
    assert candidate["strategy"] == "LONG-A"
    assert candidate["direction"] == "LONG"
    assert candidate["score"] == 85
    assert candidate["entry_price"] == 100
    assert candidate["stop_loss"] == 95
    assert candidate["tp1"] == 110
    assert candidate["tp2"] == 120
    assert candidate["auto_trading"] is False
    assert candidate["status"] == "simulation_only"


def test_strategy_candidate_without_trade_plan_is_allowed():
    item = {"symbol": "BTC-USDT-SWAP"}
    signal = make_signal()
    signal.pop("trade_plan")

    candidate = MarketScanner._build_strategy_candidate(
        item,
        signal
    )

    assert candidate is not None
    assert candidate["trade_plan"] is None


def test_strategy_candidate_rejects_invalid_symbol():
    item = {"symbol": "BTC-USDC-SWAP"}

    assert MarketScanner._build_strategy_candidate(
        item,
        make_signal()
    ) is None


def test_scanner_returns_completed_result():
    market = FakeMarketData([
        {"inst_id": "BTC-USDT-SWAP"}
    ])

    engine = FakeSignalEngine({
        "BTC-USDT-SWAP": make_result()
    })

    scanner = MarketScanner(
        market_data=market,
        signal_engine=engine
    )

    result = scanner.scan()

    assert result["status"] == "completed"
    assert result["total_symbols"] == 1
    assert result["total_scanned"] == 1
    assert result["successful"] == 1
    assert result["failed"] == 0
    assert result["trading_mode"] == "simulation_only"
    assert result["auto_trading"] is False


def test_scanner_keeps_scanning_after_one_symbol_fails():
    market = FakeMarketData([
        {"inst_id": "BTC-USDT-SWAP"},
        {"inst_id": "ETH-USDT-SWAP"}
    ])

    engine = FakeSignalEngine(
        results={
            "ETH-USDT-SWAP": make_result(
                symbol="ETH-USDT-SWAP"
            )
        },
        errors={
            "BTC-USDT-SWAP": "temporary API error"
        }
    )

    scanner = MarketScanner(
        market_data=market,
        signal_engine=engine
    )

    result = scanner.scan()

    assert result["total_scanned"] == 2
    assert result["successful"] == 1
    assert result["failed"] == 1


def test_scanner_handles_market_api_failure():
    market = FakeMarketData(error="API unavailable")

    scanner = MarketScanner(
        market_data=market,
        signal_engine=FakeSignalEngine()
    )

    result = scanner.scan()

    assert result["status"] == "error"
    assert "API unavailable" in result["error"]
    assert result["total_scanned"] == 0


def test_scanner_builds_four_independent_strategy_lists():
    signals = [
        make_signal("LONG-A", "LONG", 91),
        make_signal("LONG-B", "LONG", 88),
        make_signal("SHORT-A", "SHORT", 86),
        make_signal("SHORT-B", "SHORT", 83)
    ]

    market = FakeMarketData([
        {"inst_id": "BTC-USDT-SWAP"}
    ])

    engine = FakeSignalEngine({
        "BTC-USDT-SWAP": make_result(signals=signals)
    })

    scanner = MarketScanner(
        market_data=market,
        signal_engine=engine
    )

    result = scanner.scan()

    assert result["long_a_count"] == 1
    assert result["long_b_count"] == 1
    assert result["short_a_count"] == 1
    assert result["short_b_count"] == 1


def test_scanner_excludes_coin_without_relative_strength_from_strong_list():
    result_data = make_result()
    result_data["relative_strength"] = {
        "1H": 2.0
    }

    market = FakeMarketData([
        {"inst_id": "BTC-USDT-SWAP"}
    ])

    engine = FakeSignalEngine({
        "BTC-USDT-SWAP": result_data
    })

    scanner = MarketScanner(
        market_data=market,
        signal_engine=engine
    )

    result = scanner.scan()

    assert result["strong_coin_count"] == 0


def test_scanner_respects_minimum_relative_strength():
    market = FakeMarketData([
        {"inst_id": "BTC-USDT-SWAP"}
    ])

    engine = FakeSignalEngine({
        "BTC-USDT-SWAP": make_result(
            relative_1h=1.0,
            relative_4h=2.0
        )
    })

    scanner = MarketScanner(
        market_data=market,
        signal_engine=engine,
        min_relative_strength=2.0
    )

    result = scanner.scan()

    assert result["strong_coin_count"] == 0


def test_candidate_lists_are_sorted_by_score():
    candidates = [
        {"symbol": "AAA", "score": 70},
        {"symbol": "BBB", "score": 90},
        {"symbol": "CCC", "score": 80}
    ]

    sorted_items = MarketScanner._sort_candidates(candidates)

    assert [item["score"] for item in sorted_items] == [
        90, 80, 70
    ]
