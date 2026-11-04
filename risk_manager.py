
import math

from config import Config


class RiskManager:
    """OKX SMART TRADING V1.0 風險管理模組。

    僅計算模擬交易計畫，不執行真實下單。
    """

    def __init__(
        self,
        daily_loss_limit_percent=3.0,
        atr_multiplier=1.5,
        reward_risk_ratio=2.0
    ):
        self.daily_loss_limit_percent = self._positive_number(
            daily_loss_limit_percent,
            "daily_loss_limit_percent"
        )
        self.atr_multiplier = self._positive_number(
            atr_multiplier, "atr_multiplier"
        )
        self.reward_risk_ratio = self._positive_number(
            reward_risk_ratio, "reward_risk_ratio"
        )

        if self.daily_loss_limit_percent > 10:
            raise ValueError("Daily loss limit cannot exceed 10%")

    @staticmethod
    def _number(value, name):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number")

        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite")

        return number

    @classmethod
    def _positive_number(cls, value, name):
        number = cls._number(value, name)

        if number <= 0:
            raise ValueError(f"{name} must be positive")

        return number

    @classmethod
    def _non_negative_number(cls, value, name):
        number = cls._number(value, name)

        if number < 0:
            raise ValueError(f"{name} cannot be negative")

        return number

    @staticmethod
    def _validate_side(side):
        side = str(side).upper()

        if side not in ("LONG", "SHORT"):
            raise ValueError("side must be LONG or SHORT")

        return side

    def calculate_stop_loss(
        self,
        entry_price,
        atr,
        side,
        atr_multiplier=None
    ):
        entry = self._positive_number(entry_price, "entry_price")
        atr_value = self._positive_number(atr, "atr")
        side = self._validate_side(side)

        multiplier = (
            self.atr_multiplier
            if atr_multiplier is None
            else self._positive_number(
                atr_multiplier, "atr_multiplier"
            )
        )

        distance = atr_value * multiplier

        if side == "LONG":
            stop = entry - distance
        else:
            stop = entry + distance

        if not math.isfinite(stop) or stop <= 0:
            raise ValueError("Calculated stop loss is invalid")

        return stop

    def calculate_take_profit(
        self,
        entry_price,
        stop_loss,
        side,
        reward_risk_ratio=None
    ):
        entry = self._positive_number(entry_price, "entry_price")
        stop = self._positive_number(stop_loss, "stop_loss")
        side = self._validate_side(side)

        ratio = (
            self.reward_risk_ratio
            if reward_risk_ratio is None
            else self._positive_number(
                reward_risk_ratio, "reward_risk_ratio"
            )
        )

        if side == "LONG":
            if stop >= entry:
                raise ValueError("LONG stop loss must be below entry")

            target = entry + (entry - stop) * ratio

        else:
            if stop <= entry:
                raise ValueError("SHORT stop loss must be above entry")

            target = entry - (stop - entry) * ratio

        if not math.isfinite(target) or target <= 0:
            raise ValueError("Calculated take profit is invalid")

        return target

    def calculate_position_size(
        self,
        entry_price,
        stop_loss,
        equity=None,
        risk_percent=None,
        leverage=None,
        fee_rate=None,
        slippage_rate=None,
        side=None
    ):
        entry = self._positive_number(entry_price, "entry_price")
        stop = self._positive_number(stop_loss, "stop_loss")

        if side is not None:
            side = self._validate_side(side)

            if side == "LONG" and stop >= entry:
                raise ValueError("LONG stop loss must be below entry")

            if side == "SHORT" and stop <= entry:
                raise ValueError("SHORT stop loss must be above entry")

        account_equity = self._positive_number(
            Config.INITIAL_EQUITY_USDT if equity is None else equity,
            "equity"
        )

        risk_pct = (
            Config.RISK_PER_TRADE_PERCENT
            if risk_percent is None
            else self._positive_number(risk_percent, "risk_percent")
        )

        max_leverage = (
            Config.SIMULATED_LEVERAGE
            if leverage is None
            else self._positive_number(leverage, "leverage")
        )

        fee = (
            Config.TAKER_FEE_RATE
            if fee_rate is None
            else self._non_negative_number(fee_rate, "fee_rate")
        )

        slippage = (
            Config.SLIPPAGE_RATE
            if slippage_rate is None
            else self._non_negative_number(
                slippage_rate, "slippage_rate"
            )
        )

        if risk_pct > 5:
            raise ValueError("Risk per trade cannot exceed 5%")

        if max_leverage > 20:
            raise ValueError("Leverage cannot exceed 20x")

        stop_distance = abs(entry - stop)

        if stop_distance <= 0:
            raise ValueError("Entry and stop loss cannot be equal")

        risk_budget = account_equity * risk_pct / 100

        # 預估進場及出場的手續費、滑價成本。
        round_trip_cost_rate = 2 * (fee + slippage)

        risk_per_unit = (
            stop_distance + entry * round_trip_cost_rate
        )

        if risk_per_unit <= 0:
            raise ValueError("Risk per unit is invalid")

        quantity_by_risk = risk_budget / risk_per_unit

        # 名目倉位不得超過本金 × 模擬槓桿。
        max_notional = account_equity * max_leverage
        quantity_by_leverage = max_notional / entry

        raw_quantity = min(
            quantity_by_risk,
            quantity_by_leverage
        )

        quantity = round(raw_quantity, 8)

        if quantity <= 0:
            raise ValueError("Calculated position size is too small")

        notional = quantity * entry
        margin_required = notional / max_leverage

        price_risk = quantity * stop_distance
        estimated_cost = notional * round_trip_cost_rate
        estimated_total_risk = price_risk + estimated_cost

        return {
            "equity_usdt": round(account_equity, 4),
            "risk_budget_usdt": round(risk_budget, 4),
            "risk_percent": risk_pct,
            "entry_price": entry,
            "stop_loss": stop,
            "stop_distance": round(stop_distance, 8),
            "quantity": quantity,
            "notional_usdt": round(notional, 4),
            "margin_required_usdt": round(margin_required, 4),
            "leverage": max_leverage,
            "estimated_price_loss_usdt": round(price_risk, 4),
            "estimated_fee_slippage_usdt": round(estimated_cost, 4),
            "estimated_total_risk_usdt": round(
                estimated_total_risk, 4
            ),
            "leverage_limited": (
                quantity_by_leverage < quantity_by_risk
            ),
            "status": "simulation_only"
        }

    def check_daily_loss(
        self,
        equity,
        daily_realized_pnl
    ):
        # equity 在此代表當日開始時的權益基準。
        account_equity = self._positive_number(equity, "equity")
        daily_pnl = self._number(
            daily_realized_pnl, "daily_realized_pnl"
        )

        loss_limit = (
            account_equity
            * self.daily_loss_limit_percent
            / 100
        )

        loss_used = max(0.0, -daily_pnl)
        remaining = max(0.0, loss_limit - loss_used)

        allowed = loss_used < loss_limit

        return {
            "allowed": allowed,
            "daily_realized_pnl_usdt": round(daily_pnl, 4),
            "daily_loss_limit_usdt": round(loss_limit, 4),
            "daily_loss_used_usdt": round(loss_used, 4),
            "remaining_loss_limit_usdt": round(remaining, 4),
            "status": (
                "allowed"
                if allowed
                else "daily_loss_limit_reached"
            )
        }

    def create_trade_plan(
        self,
        symbol,
        side,
        entry_price,
        atr,
        equity=None,
        daily_realized_pnl=0
    ):
        side = self._validate_side(side)

        account_equity = (
            Config.INITIAL_EQUITY_USDT
            if equity is None
            else equity
        )

        daily_check = self.check_daily_loss(
            account_equity,
            daily_realized_pnl
        )

        if not daily_check["allowed"]:
            return {
                "symbol": symbol,
                "direction": side,
                "status": "blocked",
                "reason": "Daily loss limit reached",
                "daily_risk": daily_check,
                "auto_trading": False
            }

        stop = self.calculate_stop_loss(
            entry_price,
            atr,
            side
        )

        target = self.calculate_take_profit(
            entry_price,
            stop,
            side
        )

        position = self.calculate_position_size(
            entry_price,
            stop,
            equity=account_equity,
            side=side
        )

        return {
            "symbol": symbol,
            "direction": side,
            "entry_price": float(entry_price),
            "stop_loss": round(stop, 8),
            "take_profit": round(target, 8),
            "reward_risk_ratio": self.reward_risk_ratio,
            "position": position,
            "daily_risk": daily_check,
            "status": "simulation_only",
            "auto_trading": False
        }
