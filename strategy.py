
import math
import pandas as pd

from config import Config

try:
    from fibonacci import FibonacciEngine
except Exception:
    FibonacciEngine = None


class StrategyEngine:
    """OKX SMART TRADING V1.2 多空四策略訊號引擎。"""

    TIMEFRAME_WEIGHTS = {"1H": 0.65, "4H": 0.35}

    TIMEFRAME_CONFLICT_PENALTY = {
        "LONG-A": 10,
        "LONG-B": 20,
        "SHORT-A": 10,
        "SHORT-B": 20,
    }

    MAX_EXTENSION_ATR = {
        "LONG": 2.5,
        "SHORT": 2.5,
    }

    MISSING_RS_SCORE_CAP = 69

    def __init__(self, min_score=None, breakout_lookback=20):
        self.min_score = (
            getattr(Config, "MIN_SIGNAL_SCORE", 70)
            if min_score is None else min_score
        )
        self.breakout_lookback = max(2, int(breakout_lookback))

    @staticmethod
    def _number(value, default=None):
        try:
            result = float(value)
            return result if math.isfinite(result) else default
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def _latest(df, column, default=None):
        if not isinstance(df, pd.DataFrame) or df.empty or column not in df:
            return default
        return StrategyEngine._number(df[column].iloc[-1], default)

    @staticmethod
    def _previous(df, column, default=None):
        if not isinstance(df, pd.DataFrame) or len(df) < 2 or column not in df:
            return default
        return StrategyEngine._number(df[column].iloc[-2], default)

    @staticmethod
    def _has_columns(df, columns):
        return (
            isinstance(df, pd.DataFrame)
            and not df.empty
            and all(col in df.columns for col in columns)
        )

    def _validate(self, df):
        required = [
            "close", "high", "low", "volume",
            "ema_7", "ema_20", "ema_50",
            "rsi_14", "macd", "macd_signal",
            "macd_hist", "adx", "plus_di", "minus_di",
            "volume_ma_20"
        ]

        if not self._has_columns(df, required) or len(df) < 2:
            return False

        for column in required:
            values = pd.to_numeric(df[column], errors="coerce")
            if values.iloc[-2:].isna().any():
                return False
            if not all(math.isfinite(float(v)) for v in values.iloc[-2:]):
                return False

        close = self._latest(df, "close")
        high = self._latest(df, "high")
        low = self._latest(df, "low")
        volume = self._latest(df, "volume")

        if None in (close, high, low, volume):
            return False

        if close <= 0 or high <= 0 or low <= 0 or volume < 0:
            return False

        return high >= low and low <= close <= high

    def _common_features(self, df):
        values = {
            "close": self._latest(df, "close"),
            "previous_close": self._previous(df, "close"),
            "ema7": self._latest(df, "ema_7"),
            "ema20": self._latest(df, "ema_20"),
            "ema50": self._latest(df, "ema_50"),
            "ema100": self._latest(df, "ema_100"),
            "ema200": self._latest(df, "ema_200"),
            "rsi": self._latest(df, "rsi_14"),
            "macd": self._latest(df, "macd"),
            "macd_signal": self._latest(df, "macd_signal"),
            "macd_hist": self._latest(df, "macd_hist"),
            "previous_hist": self._previous(df, "macd_hist"),
            "adx": self._latest(df, "adx"),
            "plus_di": self._latest(df, "plus_di"),
            "minus_di": self._latest(df, "minus_di"),
            "volume": self._latest(df, "volume"),
            "volume_ma": self._latest(df, "volume_ma_20"),
            "high": self._latest(df, "high"),
            "low": self._latest(df, "low"),
            "atr": self._latest(df, "atr_14", self._latest(df, "atr")),
            "supertrend_direction": self._latest(df, "supertrend_direction"),
            "obv": self._latest(df, "obv"),
            "bb_upper": self._latest(df, "bb_upper"),
            "bb_middle": self._latest(df, "bb_middle"),
            "bb_lower": self._latest(df, "bb_lower"),
            "bb_bandwidth": self._latest(df, "bb_bandwidth"),
        }

        values["previous_obv"] = self._previous(df, "obv")
        values["previous_bb_bandwidth"] = self._previous(df, "bb_bandwidth")
        return values

    @staticmethod
    def _valid_features(features):
        required = [
            "close", "ema7", "ema20", "ema50",
            "rsi", "macd", "macd_signal", "macd_hist",
            "previous_hist", "adx", "plus_di", "minus_di",
            "volume", "volume_ma", "high", "low"
        ]
        return all(features.get(key) is not None for key in required)

    @staticmethod
    def _relative_strength_adjustment(relative_strength, direction):
        if relative_strength is None:
            return 0, "BTC 相對強弱資料缺失"

        rs = StrategyEngine._number(relative_strength)

        if rs is None:
            return 0, "BTC 相對強弱資料無效"

        if direction == "LONG":
            if rs >= 1.0:
                return 10, "相對 BTC 明顯強勢"
            if rs > 0:
                return 5, "相對 BTC 小幅強勢"
            if rs <= -2:
                return -10, "相對 BTC 明顯弱勢"
            if rs < 0:
                return -5, "相對 BTC 弱勢"

        else:
            if rs <= -1.0:
                return 10, "相對 BTC 明顯弱勢"
            if rs < 0:
                return 5, "相對 BTC 小幅弱勢"
            if rs >= 2:
                return -10, "相對 BTC 明顯強勢，不利做空"
            if rs > 0:
                return -5, "相對 BTC 強勢，不利做空"

        return 0, "相對 BTC 表現中性"

    def _score_long(self, f, relative_strength=None):
        score = 0
        reasons = []

        checks = [
            (f["close"] > f["ema20"], 10, "價格站上 EMA20"),
            (f["ema7"] > f["ema20"], 10, "EMA7 高於 EMA20"),
            (f["ema20"] > f["ema50"], 10, "EMA20 高於 EMA50"),
            (45 <= f["rsi"] <= 70, 10, "RSI 多頭區間"),
            (f["macd"] > f["macd_signal"], 10, "MACD 多頭排列"),
            (f["macd_hist"] > 0, 10, "MACD 柱體為正"),
            (f["plus_di"] > f["minus_di"], 10, "DMI 多方占優"),
            (f["adx"] >= 20, 10, "ADX 趨勢強度足夠"),
            (
                f["volume_ma"] > 0 and f["volume"] > f["volume_ma"],
                10,
                "成交量高於均量"
            ),
        ]

        for passed, points, reason in checks:
            if passed:
                score += points
                reasons.append(reason)

        adjustment, rs_reason = self._relative_strength_adjustment(
            relative_strength, "LONG"
        )
        score += adjustment
        reasons.append(rs_reason)

        return max(0, min(100, score)), reasons

    def _score_short(self, f, relative_strength=None):
        score = 0
        reasons = []

        checks = [
            (f["close"] < f["ema20"], 10, "價格跌破 EMA20"),
            (f["ema7"] < f["ema20"], 10, "EMA7 低於 EMA20"),
            (f["ema20"] < f["ema50"], 10, "EMA20 低於 EMA50"),
            (30 <= f["rsi"] <= 55, 10, "RSI 空頭區間"),
            (f["macd"] < f["macd_signal"], 10, "MACD 空頭排列"),
            (f["macd_hist"] < 0, 10, "MACD 柱體為負"),
            (f["minus_di"] > f["plus_di"], 10, "DMI 空方占優"),
            (f["adx"] >= 20, 10, "ADX 趨勢強度足夠"),
            (
                f["volume_ma"] > 0 and f["volume"] > f["volume_ma"],
                10,
                "成交量高於均量"
            ),
        ]

        for passed, points, reason in checks:
            if passed:
                score += points
                reasons.append(reason)

        adjustment, rs_reason = self._relative_strength_adjustment(
            relative_strength, "SHORT"
        )
        score += adjustment
        reasons.append(rs_reason)

        return max(0, min(100, score)), reasons

    @staticmethod
    def _ema_convergence(f):
        values = [f.get("ema7"), f.get("ema20"), f.get("ema50")]

        if any(v is None or v <= 0 for v in values):
            return None

        return (max(values) - min(values)) / f["close"] * 100

    def _early_long(self, f):
        convergence = self._ema_convergence(f)

        return (
            f["close"] > f["ema50"]
            and f["close"] <= f["ema20"] * 1.025
            and f["ema7"] <= f["ema20"] * 1.015
            and 40 <= f["rsi"] <= 65
            and f["macd_hist"] > f["previous_hist"]
            and (convergence is None or convergence <= 3.0)
        )

    def _breakout_long(self, f, df):
        lookback = min(self.breakout_lookback, len(df) - 1)

        if lookback < 1:
            return False

        prior_high = pd.to_numeric(
            df["high"].iloc[-lookback-1:-1],
            errors="coerce"
        ).max()

        if pd.isna(prior_high):
            return False

        volume_confirmed = (
            f["volume_ma"] is not None
            and f["volume_ma"] > 0
            and f["volume"] > f["volume_ma"]
        )

        if not volume_confirmed or f["close"] <= float(prior_high):
            return False

        atr = f.get("atr")
        if atr is not None and atr > 0:
            if (f["close"] - f["ema20"]) / atr > self.MAX_EXTENSION_ATR["LONG"]:
                return False

        return (
            f["close"] > f["ema20"]
            and f["ema7"] > f["ema20"]
            and f["macd_hist"] > 0
            and f["macd_hist"] > f["previous_hist"]
        )

    def _early_short(self, f):
        convergence = self._ema_convergence(f)

        return (
            f["close"] < f["ema50"]
            and f["close"] >= f["ema20"] * 0.975
            and f["ema7"] >= f["ema20"] * 0.985
            and 35 <= f["rsi"] <= 60
            and f["macd_hist"] < f["previous_hist"]
            and (convergence is None or convergence <= 3.0)
        )

    def _breakdown_short(self, f, df):
        lookback = min(self.breakout_lookback, len(df) - 1)

        if lookback < 1:
            return False

        prior_low = pd.to_numeric(
            df["low"].iloc[-lookback-1:-1],
            errors="coerce"
        ).min()

        if pd.isna(prior_low):
            return False

        volume_confirmed = (
            f["volume_ma"] is not None
            and f["volume_ma"] > 0
            and f["volume"] > f["volume_ma"]
        )

        if not volume_confirmed or f["close"] >= float(prior_low):
            return False

        atr = f.get("atr")
        if atr is not None and atr > 0:
            if (f["ema20"] - f["close"]) / atr > self.MAX_EXTENSION_ATR["SHORT"]:
                return False

        return (
            f["close"] < f["ema20"]
            and f["ema7"] < f["ema20"]
            and f["macd_hist"] < 0
            and f["macd_hist"] < f["previous_hist"]
        )

    @staticmethod
    def _optional_confirmation(f, direction):
        points = 0
        reasons = []

        st = f.get("supertrend_direction")

        if st in (1, -1):
            if (
                (direction == "LONG" and st == 1)
                or (direction == "SHORT" and st == -1)
            ):
                points += 5
                reasons.append("Supertrend 方向確認")
            else:
                points -= 10
                reasons.append("Supertrend 與訊號方向衝突，扣分")

        obv = f.get("obv")
        prev_obv = f.get("previous_obv")

        if obv is not None and prev_obv is not None:
            if (
                (direction == "LONG" and obv > prev_obv)
                or (direction == "SHORT" and obv < prev_obv)
            ):
                points += 3
                reasons.append("OBV 方向配合")
            else:
                points -= 3
                reasons.append("OBV 未配合訊號方向")

        if all(
            f.get(key) is not None
            for key in ("bb_upper", "bb_lower", "bb_middle")
        ):
            if f["bb_upper"] > f["bb_lower"]:
                if direction == "LONG" and f["close"] > f["bb_middle"]:
                    points += 2
                    reasons.append("布林中軌偏多")
                elif direction == "SHORT" and f["close"] < f["bb_middle"]:
                    points += 2
                    reasons.append("布林中軌偏空")

        return points, reasons

    @staticmethod
    def _timeframe_state(f):
        bullish = (
            f["ema7"] > f["ema20"]
            and f["plus_di"] > f["minus_di"]
        )
        bearish = (
            f["ema7"] < f["ema20"]
            and f["minus_di"] > f["plus_di"]
        )

        if bullish:
            return "LONG"
        if bearish:
            return "SHORT"
        return "NEUTRAL"

    def _timeframe_conflict(self, f1, f4, direction, strategy):
        state_1h = self._timeframe_state(f1)
        state_4h = self._timeframe_state(f4)

        penalty = self.TIMEFRAME_CONFLICT_PENALTY.get(strategy, 10)

        if state_1h == direction and state_4h == direction:
            return 0, ["1H／4H 方向一致"]

        if state_1h == "NEUTRAL" or state_4h == "NEUTRAL":
            return 0, [
                f"週期確認不足（1H={state_1h}、4H={state_4h}）"
            ]

        if state_1h == state_4h and state_1h != direction:
            return -penalty, [
                f"1H／4H 均與策略方向相反，扣 {penalty} 分"
            ]

        return -penalty, [
            f"1H／4H 趨勢衝突（1H={state_1h}、4H={state_4h}），扣 {penalty} 分"
        ]

    def _fibonacci_context(self, df, direction):
        if FibonacciEngine is None or len(df) < 10:
            return None

        try:
            result = FibonacciEngine.analyze(
                df,
                left=3,
                right=3
            )

            context = result.get(
                "bullish" if direction == "LONG" else "bearish"
            )

            if not context:
                return None

            current = result["current_price"]
            levels = context.get("retracement", {})

            distances = [
                (level, price, abs(current - price) / current * 100)
                for level, price in levels.items()
                if current > 0 and price > 0
            ]

            if not distances:
                return None

            level, price, distance = min(
                distances,
                key=lambda item: item[2]
            )

            if distance <= 1.5:
                return {
                    "level": level,
                    "price": price,
                    "distance_pct": distance
                }

        except (ValueError, TypeError, KeyError, IndexError):
            return None

        return None

    def _strategy_score(
        self,
        base_score,
        f,
        direction,
        strategy,
        fib_context,
        timeframe_penalty=0,
        timeframe_reasons=None,
        relative_strength_missing=False
    ):
        # 基礎分數縮放，保留額外確認項目的空間。
        score = base_score * 0.80
        reasons = []

        optional_points, optional_reasons = (
            self._optional_confirmation(f, direction)
        )
        score += optional_points
        reasons.extend(optional_reasons)

        if strategy.endswith("-A"):
            convergence = self._ema_convergence(f)

            if convergence is not None and convergence <= 1.5:
                score += 5
                reasons.append("EMA 均線高度收斂")

            elif convergence is not None and convergence > 3:
                score -= 5
                reasons.append("均線未收斂，提前埋伏條件較弱")

            # MACD 動能已在基礎評分，不再重複加分。

        else:
            volume_ok = (
                f["volume_ma"] is not None
                and f["volume_ma"] > 0
                and f["volume"] > f["volume_ma"]
            )

            if volume_ok:
                score += 3
                reasons.append("突破／跌破成交量確認")

        if fib_context:
            score += 3
            reasons.append(
                f"接近 Fibonacci {fib_context['level']} "
                f"（距離 {fib_context['distance_pct']:.2f}%）"
            )

        score += timeframe_penalty

        if timeframe_reasons:
            reasons.extend(timeframe_reasons)

        if relative_strength_missing:
            score = min(score, self.MISSING_RS_SCORE_CAP)
            reasons.append(
                "BTC 相對強弱資料不完整，分數上限 69"
            )

        return max(0, min(100, round(score))), reasons

    @staticmethod
    def _weighted_score(score_1h, score_4h):
        return round(
            score_1h * StrategyEngine.TIMEFRAME_WEIGHTS["1H"]
            + score_4h * StrategyEngine.TIMEFRAME_WEIGHTS["4H"]
        )

    def analyze(
        self,
        inst_id,
        df_1h,
        df_4h,
        relative_strength_1h=None,
        relative_strength_4h=None
    ):
        if not self._validate(df_1h):
            return self._empty_result(inst_id, "1H資料不足或欄位不完整")

        if not self._validate(df_4h):
            return self._empty_result(inst_id, "4H資料不足或欄位不完整")

        f1 = self._common_features(df_1h)
        f4 = self._common_features(df_4h)

        if not self._valid_features(f1) or not self._valid_features(f4):
            return self._empty_result(inst_id, "技術指標尚未形成")

        long_1h, long_reasons = self._score_long(f1, relative_strength_1h)
        short_1h, short_reasons = self._score_short(f1, relative_strength_1h)
        long_4h, long_4h_reasons = self._score_long(f4, relative_strength_4h)
        short_4h, short_4h_reasons = self._score_short(f4, relative_strength_4h)

        long_score = self._weighted_score(long_1h, long_4h)
        short_score = self._weighted_score(short_1h, short_4h)

        fib_long = self._fibonacci_context(df_4h, "LONG")
        fib_short = self._fibonacci_context(df_4h, "SHORT")

        long_a_penalty, long_a_conflict = self._timeframe_conflict(
            f1, f4, "LONG", "LONG-A"
        )
        long_b_penalty, long_b_conflict = self._timeframe_conflict(
            f1, f4, "LONG", "LONG-B"
        )
        short_a_penalty, short_a_conflict = self._timeframe_conflict(
            f1, f4, "SHORT", "SHORT-A"
        )
        short_b_penalty, short_b_conflict = self._timeframe_conflict(
            f1, f4, "SHORT", "SHORT-B"
        )

        rs_long_missing = (
            relative_strength_1h is None
            or relative_strength_4h is None
        )
        rs_short_missing = rs_long_missing

        long_a_score, long_a_extra = self._strategy_score(
            long_score, f1, "LONG", "LONG-A", fib_long,
            long_a_penalty, long_a_conflict, rs_long_missing
        )
        long_b_score, long_b_extra = self._strategy_score(
            long_score, f1, "LONG", "LONG-B", fib_long,
            long_b_penalty, long_b_conflict, rs_long_missing
        )
        short_a_score, short_a_extra = self._strategy_score(
            short_score, f1, "SHORT", "SHORT-A", fib_short,
            short_a_penalty, short_a_conflict, rs_short_missing
        )
        short_b_score, short_b_extra = self._strategy_score(
            short_score, f1, "SHORT", "SHORT-B", fib_short,
            short_b_penalty, short_b_conflict, rs_short_missing
        )

        candidates = []

        if self._early_long(f1):
            candidates.append((
                "LONG-A", "LONG", long_a_score,
                long_reasons + long_4h_reasons + long_a_extra,
                fib_long
            ))

        if self._breakout_long(f1, df_1h):
            candidates.append((
                "LONG-B", "LONG", long_b_score,
                long_reasons + long_4h_reasons + long_b_extra,
                fib_long
            ))

        if self._early_short(f1):
            candidates.append((
                "SHORT-A", "SHORT", short_a_score,
                short_reasons + short_4h_reasons + short_a_extra,
                fib_short
            ))

        if self._breakdown_short(f1, df_1h):
            candidates.append((
                "SHORT-B", "SHORT", short_b_score,
                short_reasons + short_4h_reasons + short_b_extra,
                fib_short
            ))

        signals = []

        for signal_type, direction, score, reasons, fib in candidates:
            enabled = (
                getattr(Config, "ENABLE_LONG", True)
                if direction == "LONG"
                else getattr(Config, "ENABLE_SHORT", True)
            )

            if not enabled or score < self.min_score:
                continue

            invalidation = (
                f1["low"] if direction == "LONG" else f1["high"]
            )

            signals.append({
                "symbol": inst_id,
                "signal": signal_type,
                "direction": direction,
                "score": score,
                "price": f1["close"],
                "reasons": list(dict.fromkeys(reasons)),
                "timeframes": ["1H", "4H"],
                "fibonacci": fib,
                "invalidation_price": invalidation,
                "status": "simulation_only"
            })

        return {
            "symbol": inst_id,
            "long_score": long_score,
            "short_score": short_score,
            "strategy_scores": {
                "LONG-A": long_a_score,
                "LONG-B": long_b_score,
                "SHORT-A": short_a_score,
                "SHORT-B": short_b_score
            },
            "signals": signals,
            "status": "simulation_only"
        }

    @staticmethod
    def _empty_result(inst_id, reason):
        return {
            "symbol": inst_id,
            "long_score": 0,
            "short_score": 0,
            "strategy_scores": {
                "LONG-A": 0,
                "LONG-B": 0,
                "SHORT-A": 0,
                "SHORT-B": 0
            },
            "signals": [],
            "status": "insufficient_data",
            "reason": reason
        }
