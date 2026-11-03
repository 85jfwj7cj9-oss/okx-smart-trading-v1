
import pytest

from database import Database


@pytest.fixture
def db(tmp_path):
    """每個測試使用獨立的臨時資料庫。"""
    database_path = tmp_path / "test_trading.db"
    return Database(str(database_path))


def sample_scan():
    return {
        "status": "completed",
        "total_scanned": 20,
        "successful": 18,
        "failed": 2,
        "long_count": 3,
        "short_count": 2,
        "strong_coin_count": 5,
        "finished_at": "2026-11-03T12:00:00+00:00"
    }


def sample_signal():
    return {
        "symbol": "ETH-USDT-SWAP",
        "strategy": {
            "direction": "LONG",
            "score": 85
        },
        "relative_strength": {
            "1H": 2.5,
            "4H": 4.2
        },
        "trade_plan": {
            "status": "simulation_only",
            "symbol": "ETH-USDT-SWAP",
            "direction": "LONG",
            "entry_price": 3000,
            "stop_loss": 2950,
            "take_profit": 3100,
            "position": {
                "quantity": 0.2,
                "notional_usdt": 600,
                "leverage": 5
            }
        }
    }


def sample_trade():
    return {
        "status": "simulation_only",
        "symbol": "ETH-USDT-SWAP",
        "direction": "LONG",
        "entry_price": 3000,
        "stop_loss": 2950,
        "take_profit": 3100,
        "position": {
            "quantity": 0.2,
            "notional_usdt": 600,
            "leverage": 5
        }
    }


def test_database_initialization(db):
    result = db.health_check()

    assert result["status"] == "ok"
    assert result["database"] == "sqlite"


def test_save_and_get_scan_history(db):
    scan_id = db.save_scan(sample_scan())

    history = db.get_scan_history()

    assert scan_id > 0
    assert len(history) == 1
    assert history[0]["total_scanned"] == 20
    assert history[0]["long_count"] == 3
    assert history[0]["status"] == "completed"


def test_save_and_get_signal_history(db):
    signal_id = db.save_signal(sample_signal())

    history = db.get_signal_history()

    assert signal_id > 0
    assert len(history) == 1
    assert history[0]["symbol"] == "ETH-USDT-SWAP"
    assert history[0]["direction"] == "LONG"
    assert history[0]["score"] == 85
    assert history[0]["entry_price"] == 3000


def test_save_signal_rejects_invalid_direction(db):
    signal = sample_signal()
    signal["strategy"]["direction"] = "NEUTRAL"

    with pytest.raises(ValueError):
        db.save_signal(signal)


def test_save_signal_rejects_incomplete_plan(db):
    signal = sample_signal()
    signal["trade_plan"]["status"] = "blocked"

    with pytest.raises(ValueError):
        db.save_signal(signal)


def test_save_notification(db):
    notification_id = db.save_notification(
        notification_key="ETH-LONG-001",
        symbol="ETH-USDT-SWAP",
        direction="LONG",
        message="測試通知"
    )

    assert notification_id > 0
    assert db.notification_exists("ETH-LONG-001")


def test_duplicate_notification_is_not_inserted(db):
    first = db.save_notification(
        "ETH-LONG-001",
        "ETH-USDT-SWAP",
        "LONG",
        "第一次通知"
    )

    second = db.save_notification(
        "ETH-LONG-001",
        "ETH-USDT-SWAP",
        "LONG",
        "重複通知"
    )

    assert first is not None
    assert second is None
    assert db.notification_exists("ETH-LONG-001")


def test_create_simulated_trade(db):
    trade_id = db.create_simulated_trade(sample_trade())

    trades = db.get_simulated_trades()

    assert trade_id > 0
    assert len(trades) == 1
    assert trades[0]["symbol"] == "ETH-USDT-SWAP"
    assert trades[0]["status"] == "open"


def test_real_trade_is_rejected(db):
    trade = sample_trade()
    trade["status"] = "live"

    with pytest.raises(ValueError):
        db.create_simulated_trade(trade)


def test_close_long_simulated_trade(db):
    trade_id = db.create_simulated_trade(sample_trade())

    result = db.close_simulated_trade(
        trade_id,
        exit_price=3100
    )

    trades = db.get_simulated_trades(
        status="closed"
    )

    assert result is True
    assert len(trades) == 1

    # (3100 - 3000) × 0.2 = 20 USDT
    assert trades[0]["pnl_usdt"] == pytest.approx(20)


def test_close_short_simulated_trade(db):
    trade = sample_trade()
    trade["direction"] = "SHORT"
    trade["stop_loss"] = 3050
    trade["take_profit"] = 2900

    trade_id = db.create_simulated_trade(trade)

    result = db.close_simulated_trade(
        trade_id,
        exit_price=2900
    )

    trades = db.get_simulated_trades(
        status="closed"
    )

    assert result is True

    # (3000 - 2900) × 0.2 = 20 USDT
    assert trades[0]["pnl_usdt"] == pytest.approx(20)


def test_cannot_close_trade_twice(db):
    trade_id = db.create_simulated_trade(sample_trade())

    first = db.close_simulated_trade(
        trade_id,
        exit_price=3100
    )

    second = db.close_simulated_trade(
        trade_id,
        exit_price=3200
    )

    assert first is True
    assert second is False


def test_trade_statistics(db):
    trade_id = db.create_simulated_trade(sample_trade())

    db.close_simulated_trade(
        trade_id,
        exit_price=3100
    )

    stats = db.get_trade_statistics()

    assert stats["total_trades"] == 1
    assert stats["closed_trades"] == 1
    assert stats["winning_trades"] == 1
    assert stats["losing_trades"] == 0
    assert stats["gross_pnl_usdt"] == pytest.approx(20)
    assert stats["win_rate_percent"] == 100


def test_invalid_exit_price(db):
    trade_id = db.create_simulated_trade(sample_trade())

    with pytest.raises(ValueError):
        db.close_simulated_trade(
            trade_id,
            exit_price=0
        )


def test_invalid_trade_price_order(db):
    trade = sample_trade()
    trade["stop_loss"] = 3050

    with pytest.raises(ValueError):
        db.create_simulated_trade(trade)


def test_empty_database_statistics(db):
    stats = db.get_trade_statistics()

    assert stats["total_trades"] == 0
    assert stats["closed_trades"] == 0
    assert stats["win_rate_percent"] == 0
    assert stats["gross_pnl_usdt"] == 0
