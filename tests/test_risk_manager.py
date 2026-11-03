
import pytest

from risk_manager import RiskManager


@pytest.fixture
def manager():
    return RiskManager()


def test_long_stop_loss(manager):
    stop = manager.calculate_stop_loss(
        entry_price=100,
        atr=2,
        side="LONG"
    )
    assert stop == pytest.approx(97)


def test_short_stop_loss(manager):
    stop = manager.calculate_stop_loss(
        entry_price=100,
        atr=2,
        side="SHORT"
    )
    assert stop == pytest.approx(103)


def test_long_take_profit(manager):
    target = manager.calculate_take_profit(
        entry_price=100,
        stop_loss=97,
        side="LONG"
    )
    assert target == pytest.approx(106)


def test_short_take_profit(manager):
    target = manager.calculate_take_profit(
        entry_price=100,
        stop_loss=103,
        side="SHORT"
    )
    assert target == pytest.approx(94)


def test_position_size_within_risk_budget(manager):
    result = manager.calculate_position_size(
        entry_price=100,
        stop_loss=97,
        equity=1000,
        risk_percent=1,
        leverage=5
    )

    assert result["quantity"] > 0
    assert result["estimated_total_risk_usdt"] <= 10
    assert result["status"] == "simulation_only"


def test_position_size_respects_leverage(manager):
    result = manager.calculate_position_size(
        entry_price=100,
        stop_loss=90,
        equity=1000,
        risk_percent=5,
        leverage=2
    )

    assert result["notional_usdt"] <= 2000
    assert result["margin_required_usdt"] <= 1000


def test_position_size_includes_fees_and_slippage(manager):
    result = manager.calculate_position_size(
        entry_price=100,
        stop_loss=97,
        equity=1000,
        risk_percent=1,
        leverage=5,
        fee_rate=0.001,
        slippage_rate=0.001
    )

    assert result["estimated_fee_slippage_usdt"] > 0
    assert result["estimated_total_risk_usdt"] <= 10


def test_daily_loss_allowed(manager):
    result = manager.check_daily_loss(
        equity=1000,
        daily_realized_pnl=-20
    )

    assert result["allowed"] is True
    assert result["remaining_loss_limit_usdt"] == pytest.approx(10)


def test_daily_loss_blocked(manager):
    result = manager.check_daily_loss(
        equity=1000,
        daily_realized_pnl=-30
    )

    assert result["allowed"] is False
    assert result["status"] == "daily_loss_limit_reached"


def test_trade_plan_long(manager):
    result = manager.create_trade_plan(
        symbol="BTC-USDT-SWAP",
        side="LONG",
        entry_price=100,
        atr=2,
        equity=1000
    )

    assert result["status"] == "simulation_only"
    assert result["auto_trading"] is False
    assert result["stop_loss"] < result["entry_price"]
    assert result["take_profit"] > result["entry_price"]


def test_trade_plan_blocked_by_daily_loss(manager):
    result = manager.create_trade_plan(
        symbol="BTC-USDT-SWAP",
        side="LONG",
        entry_price=100,
        atr=2,
        equity=1000,
        daily_realized_pnl=-30
    )

    assert result["status"] == "blocked"
    assert result["auto_trading"] is False


def test_invalid_side(manager):
    with pytest.raises(ValueError):
        manager.calculate_stop_loss(
            entry_price=100,
            atr=2,
            side="BUY"
        )


def test_invalid_long_stop(manager):
    with pytest.raises(ValueError):
        manager.calculate_take_profit(
            entry_price=100,
            stop_loss=105,
            side="LONG"
        )


def test_leverage_limit(manager):
    with pytest.raises(ValueError):
        manager.calculate_position_size(
            entry_price=100,
            stop_loss=90,
            leverage=25
        )


def test_invalid_daily_loss_input(manager):
    with pytest.raises(ValueError):
        manager.check_daily_loss(
            equity=1000,
            daily_realized_pnl="invalid"
        )
