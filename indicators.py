
import numpy as np
import pandas as pd


class IndicatorEngine:
    """OKX SMART TRADING V1.0 技術指標引擎。"""

    REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]

    @staticmethod
    def _validate_period(period, minimum=1):
        if (
            isinstance(period, bool)
            or not isinstance(period, int)
            or period < minimum
        ):
            raise ValueError(
                f"Period must be an integer >= {minimum}"
            )

    @staticmethod
    def validate_data(df):
        if not isinstance(df, pd.DataFrame):
            raise TypeError("Input must be a pandas DataFrame")

        missing = [
            col for col in IndicatorEngine.REQUIRED_COLUMNS
            if col not in df.columns
        ]

        if missing:
            raise ValueError(f"Missing columns: {missing}")

        if len(df) < 2:
            raise ValueError("At least 2 candles are required")

        data = df.copy()

        # 時間索引必須依照舊到新排列。
        if isinstance(data.index, (pd.DatetimeIndex, pd.TimedeltaIndex)):
            if not data.index.is_monotonic_increasing:
                raise ValueError("Candle index must be chronological")

            if data.index.has_duplicates:
                raise ValueError("Duplicate candle timestamps")

        # 若有 timestamp 欄位，也必須依時間排序且不可重複。
        if "timestamp" in data.columns:
            timestamps = pd.to_numeric(
                data["timestamp"], errors="coerce"
            )

            if timestamps.isna().any():
                raise ValueError("Invalid candle timestamps")

            if timestamps.duplicated().any():
                raise ValueError("Duplicate candle timestamps")

            if not timestamps.is_monotonic_increasing:
                raise ValueError("Candles must be chronological")

        for col in IndicatorEngine.REQUIRED_COLUMNS:
            data[col] = pd.to_numeric(
                data[col], errors="coerce"
            )

        data = data.replace([np.inf, -np.inf], np.nan)

        if data[IndicatorEngine.REQUIRED_COLUMNS].isna().any().any():
            raise ValueError("OHLCV data contains invalid values")

        if (data[["open", "high", "low", "close"]] <= 0).any().any():
            raise ValueError("OHLC prices must be positive")

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
        IndicatorEngine._validate_period(period)

        return series.ewm(
            span=period,
            adjust=False,
            min_periods=period
        ).mean()

    @staticmethod
    def wilder_smoothing(series, period):
        """Wilder RMA：先使用 period 個有效值的 SMA 初始化。"""
        IndicatorEngine._validate_period(period)

        values = pd.to_numeric(
            series, errors="coerce"
        ).astype(float)

        result = pd.Series(
            np.nan, index=values.index, dtype=float
        )

        valid_positions = np.flatnonzero(
            values.notna().to_numpy()
        )

        if len(valid_positions) < period:
            return result

        # 僅允許連續有效值作為初始化區間。
        first_seed_end = None

        for start in range(len(valid_positions) - period + 1):
            window = valid_positions[start:start + period]

            if np.array_equal(
                window,
                np.arange(window[0], window[0] + period)
            ):
                first_seed_end = int(window[-1])
                seed_start = int(window[0])
                break

        if first_seed_end is None:
            return result

        seed = values.iloc[seed_start:first_seed_end + 1].mean()
        result.iloc[first_seed_end] = seed

        previous = float(seed)

        for i in range(first_seed_end + 1, len(values)):
            current = values.iloc[i]

            if pd.isna(current):
                previous = np.nan
                continue

            if np.isnan(previous):
                if i + period > len(values):
                    break

                window = values.iloc[i:i + period]

                if window.isna().any():
                    continue

                previous = float(window.mean())
                result.iloc[i + period - 1] = previous
                continue

            previous = (
                previous * (period - 1) + float(current)
            ) / period

            result.iloc[i] = previous

        return result

    @staticmethod
    def rsi(close, period=14):
        IndicatorEngine._validate_period(period, minimum=2)

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = IndicatorEngine.wilder_smoothing(
            gain, period
        )
        avg_loss = IndicatorEngine.wilder_smoothing(
            loss, period
        )

        denominator = avg_gain + avg_loss

        result = 100 * avg_gain / denominator.replace(0, np.nan)

        result = result.mask(
            (avg_loss == 0) & (avg_gain > 0), 100
        )
        result = result.mask(
            (avg_gain == 0) & (avg_loss > 0), 0
        )
        result = result.mask(
            (avg_gain == 0) & (avg_loss == 0), 50
        )

        return result

    @staticmethod
    def macd(close, fast=12, slow=26, signal=9):
        IndicatorEngine._validate_period(fast)
        IndicatorEngine._validate_period(slow)
        IndicatorEngine._validate_period(signal)

        if slow <= fast:
            raise ValueError("MACD slow period must exceed fast period")

        fast_ema = IndicatorEngine.ema(close, fast)
        slow_ema = IndicatorEngine.ema(close, slow)

        line = fast_ema - slow_ema

        signal_line = line.ewm(
            span=signal,
            adjust=False,
            min_periods=signal
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
        IndicatorEngine._validate_period(period)

        tr = IndicatorEngine.true_range(
            df["high"], df["low"], df["close"]
        )

        return IndicatorEngine.wilder_smoothing(
            tr, period
        )

    @staticmethod
    def dmi_adx(df, period=14):
        IndicatorEngine._validate_period(period, minimum=2)

        high = df["high"]
        low = df["low"]
        close = df["close"]

        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = pd.Series(
            np.where(
                (up_move > down_move) & (up_move > 0),
                up_move,
                0.0
            ),
            index=df.index,
            dtype=float
        )

        minus_dm = pd.Series(
            np.where(
                (down_move > up_move) & (down_move > 0),
                down_move,
                0.0
            ),
            index=df.index,
            dtype=float
        )

        # 第一根 K 線沒有前一根資料，不參與 DM/TR 平滑。
        plus_dm.iloc[0] = np.nan
        minus_dm.iloc[0] = np.nan

        tr = IndicatorEngine.true_range(
            high, low, close
        )
        tr.iloc[0] = np.nan

        smoothed_plus = IndicatorEngine.wilder_smoothing(
            plus_dm, period
        )
        smoothed_minus = IndicatorEngine.wilder_smoothing(
            minus_dm, period
        )
        smoothed_tr = IndicatorEngine.wilder_smoothing(
            tr, period
        )

        plus_di = 100 * smoothed_plus / smoothed_tr.replace(
            0, np.nan
        )
        minus_di = 100 * smoothed_minus / smoothed_tr.replace(
            0, np.nan
        )

        denominator = plus_di + minus_di

        dx = (
            100 * (plus_di - minus_di).abs()
            / denominator.replace(0, np.nan)
        )

        dx = dx.mask(denominator == 0, 0)

        adx = IndicatorEngine.wilder_smoothing(
            dx, period
        )

        return pd.DataFrame({
            "plus_di": plus_di,
            "minus_di": minus_di,
            "adx": adx
        }, index=df.index)

    @staticmethod
    def bollinger_bands(close, period=20, std_dev=2):
        IndicatorEngine._validate_period(period, minimum=2)

        if (
            isinstance(std_dev, bool)
            or not isinstance(std_dev, (int, float))
            or not np.isfinite(std_dev)
            or std_dev <= 0
        ):
            raise ValueError("Standard deviation multiplier must be positive")

        middle = close.rolling(
            period, min_periods=period
        ).mean()

        std = close.rolling(
            period, min_periods=period
        ).std(ddof=0)

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
        if not close.index.equals(volume.index):
            raise ValueError("Close and volume indexes must match")

        direction = np.sign(close.diff()).fillna(0)

        return (direction * volume).cumsum()

    @staticmethod
    def supertrend(df, period=10, multiplier=3.0):
        IndicatorEngine._validate_period(period)

        if (
            isinstance(multiplier, bool)
            or not isinstance(multiplier, (int, float))
            or not np.isfinite(multiplier)
            or multiplier <= 0
        ):
            raise ValueError("Supertrend multiplier must be positive")

        atr = IndicatorEngine.atr(df, period)

        hl2 = (df["high"] + df["low"]) / 2

        basic_upper = hl2 + multiplier * atr
        basic_lower = hl2 - multiplier * atr

        final_upper = pd.Series(
            np.nan, index=df.index, dtype=float
        )
        final_lower = pd.Series(
            np.nan, index=df.index, dtype=float
        )

        trend = pd.Series(
            np.nan, index=df.index, dtype=float
        )

        direction = pd.Series(
            0, index=df.index, dtype=int
        )

        for i in range(len(df)):
            if pd.isna(atr.iloc[i]):
                continue

            upper = basic_upper.iloc[i]
            lower = basic_lower.iloc[i]

            if i == 0 or pd.isna(atr.iloc[i - 1]):
                final_upper.iloc[i] = upper
                final_lower.iloc[i] = lower
                trend.iloc[i] = upper
                direction.iloc[i] = -1
                continue

            previous_upper = final_upper.iloc[i - 1]
            previous_lower = final_lower.iloc[i - 1]
            previous_close = df["close"].iloc[i - 1]

            if (
                upper < previous_upper
                or previous_close > previous_upper
            ):
                final_upper.iloc[i] = upper
            else:
                final_upper.iloc[i] = previous_upper

            if (
                lower > previous_lower
                or previous_close < previous_lower
            ):
                final_lower.iloc[i] = lower
            else:
                final_lower.iloc[i] = previous_lower

            previous_direction = direction.iloc[i - 1]

            if previous_direction == -1:
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

        result["rsi_14"] = IndicatorEngine.rsi(
            data["close"], 14
        )

        result = result.join(
            IndicatorEngine.macd(data["close"])
        )

        result["atr_14"] = IndicatorEngine.atr(data, 14)

        result = result.join(
            IndicatorEngine.dmi_adx(data, 14)
        )

        result = result.join(
            IndicatorEngine.bollinger_bands(
                data["close"], 20, 2
            )
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
