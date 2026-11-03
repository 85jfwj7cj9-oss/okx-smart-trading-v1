
import pandas as pd

from config import Config


class StrategyEngine:
    """OKX SMART TRADING V1.0 多空策略訊號引擎。"""

    def __init__(self, min_score=None):
        self.min_score = (
            Config.MIN_SIGNAL_SCORE
            if min_score is None else min_score
        )

    @staticmethod
    def _number(value, default=None):
        try:
            result = float(value)
            if pd.isna(result):
                return default
            return result
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _latest(df, column, default=None):
        if df is None or column not in df.columns or df.empty:
            return default
        return StrategyEngine._number(
            df[column].iloc[-1], default
        )

    @staticmethod
    def _previous(df, column, default=None):
        if df is None or column not in df.columns or len(df) < 2:
            return default
        return StrategyEngine._number(
            df[column].iloc[-2], default
        )

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

        if not self._has_columns(df, required):
            return False

        if len(df) < 2:
            return False

        close = self._latest(df, "close")
        if close is None or close <= 0:
            return False

        return True

    def _common_features(self, df):
        close = self._latest(df, "close")
        previous_close = self._previous(df, "close")

        ema7 = self._latest(df, "ema_7")
        ema20 = self._latest(df, "ema_20")
        ema50 = self._latest(df, "ema_50")

        rsi = self._latest(df, "rsi_14")
        macd = self._latest(df, "macd")
        macd_signal = self._latest(df, "macd_signal")
        macd_hist = self._latest(df, "macd_hist")
        previous_hist = self._previous(df, "macd_hist")

        adx = self._latest(df, "adx")
        plus_di = self._latest(df, "plus_di")
        minus_di = self._latest(df, "minus_di")

        volume = self._latest(df, "volume")
        volume_ma = self._latest(df, "volume_ma_20")

        high = self._latest(df, "high")
        low = self._latest(df, "low")

        return {
            "close": close,
            "previous_close": previous_close,
            "ema7": ema7,
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "previous_hist": previous_hist,
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "volume": volume,
            "volume_ma": volume_ma,
            "high": high,
            "low": low
        }

    @staticmethod
    def _valid_features(features):
        required = [
            "close", "ema7", "ema20", "ema50",
            "rsi", "macd", "macd_signal", "macd_hist",
            "adx", "plus_di", "minus_di",
            "volume", "volume_ma", "high", "low"
        ]
        return all(features.get(key) is not None for key in required)

    def _score_long(self, f, relative_strength=None):
        score = 0
        reasons = []

        if f["close"] > f["ema20"]:
            score += 10
            reasons.append("價格站上 EMA20")

        if f["ema7"] > f["ema20"]:
            score += 10
            reasons.append("EMA7 高於 EMA20")

        if f["ema20"] > f["ema50"]:
            score += 10
            reasons.append("EMA20 高於 EMA50")

        if 45 <= f["rsi"] <= 70:
            score += 10
            reasons.append("RSI 多頭區間")

        if f["macd"] > f["macd_signal"]:
            score += 10
            reasons.append("MACD 多頭排列")

        if f["macd_hist"] > 0:
            score += 10
            reasons.append("MACD 柱體為正")

        if f["macd_hist"] > f["previous_hist"]:
            score += 5
            reasons.append("MACD 動能增強")

        if f["plus_di"] > f["minus_di"]:
            score += 10
            reasons.append("DMI 多方占優")

        if f["adx"] >= 20:
            score += 10
            reasons.append("ADX 趨勢強度足夠")

        if f["volume_ma"] > 0 and f["volume"] > f["volume_ma"]:
            score += 5
            reasons.append("成交量高於均量")

        if relative_strength is not None:
            if relative_strength > 0:
                score += 10
                reasons.append("強於 BTC")
            elif relative_strength < -2:
                score -= 5
                reasons.append("弱於 BTC")

        return max(0, min(100, score)), reasons

    def _score_short(self, f, relative_strength=None):
        score = 0
        reasons = []

        if f["close"] < f["ema20"]:
            score += 10
            reasons.append("價格跌破 EMA20")

        if f["ema7"] < f["ema20"]:
            score += 10
            reasons.append("EMA7 低於 EMA20")

        if f["ema20"] < f["ema50"]:
            score += 10
            reasons.append("EMA20 低於 EMA50")

        if 30 <= f["rsi"] <= 55:
            score += 10
            reasons.append("RSI 空頭區間")

        if f["macd"] < f["macd_signal"]:
            score += 10
            reasons.append("MACD 空頭排列")

        if f["macd_hist"] < 0:
            score += 10
            reasons.append("MACD 柱體為負")

        if f["macd_hist"] < f["previous_hist"]:
            score += 5
            reasons.append("MACD 空頭動能增強")

        if f["minus_di"] > f["plus_di"]:
            score += 10
            reasons.append("DMI 空方占優")

        if f["adx"] >= 20:
            score += 10
            reasons.append("ADX 趨勢強度足夠")

        if f["volume_ma"] > 0 and f["volume"] > f["volume_ma"]:
            score += 5
            reasons.append("成交量高於均量")

        if relative_strength is not None:
            if relative_strength < 0:
                score += 10
                reasons.append("弱於 BTC")
            elif relative_strength > 2:
                score -= 5
                reasons.append("強於 BTC")

        return max(0, min(100, score)), reasons

    def _early_long(self, f):
        return (
            f["close"] > f["ema50"]
            and f["close"] <= f["ema20"] * 1.025
            and f["ema7"] <= f["ema20"] * 1.015
            and f["rsi"] >= 40
            and f["rsi"] <= 65
            and f["macd_hist"] > f["previous_hist"]
        )

    def _breakout_long(self, f, df):
        previous_high = self._previous(df, "high")
        if previous_high is None:
            return False

        return (
            f["close"] > previous_high
            and f["close"] > f["ema20"]
            and f["ema7"] > f["ema20"]
            and f["macd_hist"] > 0
            and f["macd_hist"] > f["previous_hist"]
        )

    def _early_short(self, f):
        return (
            f["close"] < f["ema50"]
            and f["close"] >= f["ema20"] * 0.975
            and f["ema7"] >= f["ema20"] * 0.985
            and f["rsi"] >= 35
            and f["rsi"] <= 60
            and f["macd_hist"] < f["previous_hist"]
        )

    def _breakdown_short(self, f, df):
        previous_low = self._previous(df, "low")
        if previous_low is None:
            return False

        return (
            f["close"] < previous_low
            and f["close"] < f["ema20"]
            and f["ema7"] < f["ema20"]
            and f["macd_hist"] < 0
            and f["macd_hist"] < f["previous_hist"]
        )

    def analyze(
        self,
        inst_id,
        df_1h,
        df_4h,
        relative_strength_1h=None,
        relative_strength_4h=None
    ):
        """分析單一幣種，回傳多空候選訊號。"""

        if not self._validate(df_1h):
            return self._empty_result(inst_id, "1H資料不足或欄位不完整")

        if not self._validate(df_4h):
            return self._empty_result(inst_id, "4H資料不足或欄位不完整")

        f1 = self._common_features(df_1h)
        f4 = self._common_features(df_4h)

        if not self._valid_features(f1) or not self._valid_features(f4):
            return self._empty_result(inst_id, "技術指標尚未形成")

        long_score, long_reasons = self._score_long(
            f1, relative_strength_1h
        )
        short_score, short_reasons = self._score_short(
            f1, relative_strength_1h
        )

        long_4h_score, _ = self._score_long(
            f4, relative_strength_4h
        )
        short_4h_score, _ = self._score_short(
            f4, relative_strength_4h
        )

        long_score = round(long_score * 0.65 + long_4h_score * 0.35)
        short_score = round(short_score * 0.65 + short_4h_score * 0.35)

        long_candidates = []

        if self._early_long(f1):
            long_candidates.append("LONG-A")

        if self._breakout_long(f1, df_1h):
            long_candidates.append("LONG-B")

        short_candidates = []

        if self._early_short(f1):
            short_candidates.append("SHORT-A")

        if self._breakdown_short(f1, df_1h):
            short_candidates.append("SHORT-B")

        signals = []

        if Config.ENABLE_LONG and long_score >= self.min_score:
            for signal_type in long_candidates:
                signals.append({
                    "symbol": inst_id,
                    "signal": signal_type,
                    "direction": "LONG",
                    "score": long_score,
                    "price": f1["close"],
                    "reasons": long_reasons,
                    "timeframes": ["1H", "4H"],
                    "status": "simulation_only"
                })

        if Config.ENABLE_SHORT and short_score >= self.min_score:
            for signal_type in short_candidates:
                signals.append({
                    "symbol": inst_id,
                    "signal": signal_type,
                    "direction": "SHORT",
                    "score": short_score,
                    "price": f1["close"],
                    "reasons": short_reasons,
                    "timeframes": ["1H", "4H"],
                    "status": "simulation_only"
                })

        return {
            "symbol": inst_id,
            "long_score": long_score,
            "short_score": short_score,
            "signals": signals,
            "status": "simulation_only"
        }

    @staticmethod
    def _empty_result(inst_id, reason):
        return {
            "symbol": inst_id,
            "long_score": 0,
            "short_score": 0,
            "signals": [],
            "status": "insufficient_data",
            "reason": reason
        }
