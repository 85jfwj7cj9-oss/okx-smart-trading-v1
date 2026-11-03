import numpy as np
import pandas as pd


class IndicatorEngine:
    """OKX SMART TRADING V1.0 技術指標引擎。"""

    @staticmethod
    def validate_data(df):
        required = ["open", "high", "low", "close", "volume"]

        if not isinstance(df, pd.DataFrame):
            raise TypeError("Input must be a pandas DataFrame")

        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing columns: {missing}")

        if len(df) < 2:
            raise ValueError("At least 2 candles are required")

        data = df.copy()

        for col in required:
            data[col] = pd.to_numeric(data[col], errors="coerce")

        data = data.replace([np.inf, -np.inf], np.nan)

        if data[required].isna().any().any():
            raise ValueError("OHLCV data contains invalid values")

        if (data["close"] <= 0).any():
            raise ValueError("Close prices must be positive")
        if (data["volume"] < 0).any():
            raise ValueError("Volume cannot be negative")
        if (data["high"] < data["low"]).any():
            raise ValueError("High cannot be lower than low")
        if (data["high"] < data["open"]).any():
            raise ValueError("High cannot be lower than open")
        if (data["high"] < data["close"]).any():
            raise ValueError("High cannot be lower than close")
        if (data["low"] > data["open"]).any():
            raise ValueError("Low cannot be higher than open")
        if (data["low"] > data["close"]).any():
            raise ValueError("Low cannot be higher than close")

        return data

    @staticmethod
    def ema(series, period):
        if period < 1:
            raise ValueError("Period must be positive")
        return series.ewm(
            span=period, adjust=False, min_periods=period
        ).mean()

    @staticmethod
    def rsi(close, period=14):
        if period < 2:
            raise ValueError("RSI period must be at least 2")

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(
            alpha=1 / period, adjust=False, min_periods=period
        ).mean()
        avg_loss = loss.ewm(
            alpha=1 / period, adjust=False, min_periods=period
        ).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        result = 100 - 100 / (1 + rs)
        result = result.mask((avg_loss == 0) & (avg_gain > 0), 100)
        result = result.mask((avg_gain == 0) & (avg_loss > 0), 0)
        result = result.mask((avg_gain == 0) & (avg_loss == 0), 50)
        return result

    @staticmethod
    def macd(close, fast=12, slow=26, signal=9):
        if fast < 1 or slow <= fast or signal < 1:
            raise ValueError("Invalid MACD periods")

        fast_ema = IndicatorEngine.ema(close, fast)
        slow_ema = IndicatorEngine.ema(close, slow)
        line = fast_ema - slow_ema
        signal_line = line.ewm(
            span=signal, adjust=False, min_periods=signal
        ).mean()

        return pd.DataFrame({
            "macd": line,
            "macd_signal": signal_line,
            "macd_hist": line - signal_line
        }, index=close.index)

    @staticmethod
    def true_range(high, low, close):
        previous = close.shift(1)
        ranges = pd.concat([
            high - low,
            (high - previous).abs(),
            (low - previous).abs()
        ], axis=1)
        return ranges.max(axis=1)

    @staticmethod
    def atr(df, period=14):
        if period < 1:
            raise ValueError("ATR period must be positive")

        tr = IndicatorEngine.true_range(
            df["high"], df["low"], df["close"]
        )
        return tr.ewm(
            alpha=1 / period, adjust=False, min_periods=period
        ).mean()

    @staticmethod
    def dmi_adx(df, period=14):
        if period < 2:
            raise ValueError("ADX period must be at least 2")

        up = df["high"].diff()
        down = -df["low"].diff()

        plus_dm = pd.Series(
            np.where((up > down) & (up > 0), up, 0.0),
            index=df.index
        )
        minus_dm = pd.Series(
            np.where((down > up) & (down > 0), down, 0.0),
            index=df.index
        )

        atr = IndicatorEngine.atr(df, period)

        plus_di = 100 * plus_dm.ewm(
            alpha=1 / period, adjust=False, min_periods=period
        ).mean() / atr.replace(0, np.nan)

        minus_di = 100 * minus_dm.ewm(
            alpha=1 / period, adjust=False, min_periods=period
        ).mean() / atr.replace(0, np.nan)

        denominator = (plus_di + minus_di).replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / denominator

        adx = dx.ewm(
            alpha=1 / period, adjust=False, min_periods=period
        ).mean()

        return pd.DataFrame({
            "plus_di": plus_di,
            "minus_di": minus_di,
            "adx": adx
        }, index=df.index)

    @staticmethod
    def bollinger_bands(close, period=20, std_dev=2):
        if period < 2 or std_dev <= 0:
            raise ValueError("Invalid Bollinger parameters")

        middle = close.rolling(period, min_periods=period).mean()
        std = close.rolling(period, min_periods=period).std(ddof=0)
        upper = middle + std_dev * std
        lower = middle - std_dev * std

        bandwidth = (
            (upper - lower) / middle.replace(0, np.nan)
        ) * 100
        percent_b = (
            (close - lower) / (upper - lower).replace(0, np.nan)
        )

        return pd.DataFrame({
            "bb_upper": upper,
            "bb_middle": middle,
            "bb_lower": lower,
            "bb_bandwidth": bandwidth,
            "bb_percent_b": percent_b
        }, index=close.index)

    @staticmethod
    def obv(close, volume):
        direction = np.sign(close.diff()).fillna(0)
        return (direction * volume).cumsum()

    @staticmethod
    def supertrend(df, period=10, multiplier=3.0):
        if period < 1 or multiplier <= 0:
            raise ValueError("Invalid Supertrend parameters")

        atr = IndicatorEngine.atr(df, period)
        hl2 = (df["high"] + df["low"]) / 2
        upper = hl2 + multiplier * atr
        lower = hl2 - multiplier * atr

        final_upper = upper.copy()
        final_lower = lower.copy()

        trend = pd.Series(np.nan, index=df.index, dtype=float)
        direction = pd.Series(0, index=df.index, dtype=int)

        for i in range(len(df)):
            if pd.isna(atr.iloc[i]):
                continue

            if i == 0 or pd.isna(atr.iloc[i - 1]):
                trend.iloc[i] = upper.iloc[i]
                direction.iloc[i] = -1
                continue

            prev_close = df["close"].iloc[i - 1]

            if (
                upper.iloc[i] < final_upper.iloc[i - 1]
                or prev_close > final_upper.iloc[i - 1]
            ):
                final_upper.iloc[i] = upper.iloc[i]
            else:
                final_upper.iloc[i] = final_upper.iloc[i - 1]

            if (
                lower.iloc[i] > final_lower.iloc[i - 1]
                or prev_close < final_lower.iloc[i - 1]
            ):
                final_lower.iloc[i] = lower.iloc[i]
            else:
                final_lower.iloc[i] = final_lower.iloc[i - 1]

            if direction.iloc[i - 1] == -1:
                if df["close"].iloc[i] > final_upper.iloc[i]:
                    direction.iloc[i] = 1
                    trend.iloc[i] = final_lower.iloc[i]
                else:
                    direction.iloc[i] = -1
                    trend.iloc[i] = final_upper.iloc[i]
            else:
                if df["close"].iloc[i] < final_lower.iloc[i]:
                    direction.iloc[i] = -1
                    trend.iloc[i] = final_upper.iloc[i]
                else:
                    direction.iloc[i] = 1
                    trend.iloc[i] = final_lower.iloc[i]

        return pd.DataFrame({
            "supertrend": trend,
            "supertrend_direction": direction
        }, index=df.index)

    @staticmethod
    def calculate_all(df):
        data = IndicatorEngine.validate_data(df)
        result = data.copy()

        for period in (7, 20, 50, 100, 200):
            result[f"ema_{period}"] = IndicatorEngine.ema(
                data["close"], period
            )

        result["rsi_14"] = IndicatorEngine.rsi(data["close"], 14)
        result = result.join(IndicatorEngine.macd(data["close"]))
        result["atr_14"] = IndicatorEngine.atr(data, 14)
        result = result.join(IndicatorEngine.dmi_adx(data, 14))
        result = result.join(
            IndicatorEngine.bollinger_bands(data["close"], 20, 2)
        )
        result["obv"] = IndicatorEngine.obv(
            data["close"], data["volume"]
        )
        result["volume_ma_20"] = data["volume"].rolling(
            20, min_periods=20
        ).mean()
        result = result.join(
            IndicatorEngine.supertrend(data, 10, 3.0)
        )

        return result
