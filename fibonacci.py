
import numpy as np
import pandas as pd


class FibonacciEngine:
    """自動 Swing 高低點與 Fibonacci 分析引擎。"""

    RETRACEMENT_LEVELS = (0.382, 0.5, 0.618, 0.786)
    EXTENSION_LEVELS = (1.272, 1.618)

    @staticmethod
    def _validate_period(value, name):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise ValueError(f"{name} must be a positive integer")

    @staticmethod
    def validate_data(df):
        required = ["high", "low", "close"]

        if not isinstance(df, pd.DataFrame):
            raise TypeError("Input must be a pandas DataFrame")

        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"Missing columns: {missing}")

        if len(df) < 3:
            raise ValueError("At least 3 candles are required")

        data = df.copy()

        for col in required:
            data[col] = pd.to_numeric(
                data[col], errors="coerce"
            )

        data = data.replace([np.inf, -np.inf], np.nan)

        if data[required].isna().any().any():
            raise ValueError("Price data contains invalid values")

        if (data[required] <= 0).any().any():
            raise ValueError("Prices must be positive")

        if (data["high"] < data["low"]).any():
            raise ValueError("High cannot be lower than low")

        if (data["high"] < data["close"]).any():
            raise ValueError("High cannot be lower than close")

        if (data["low"] > data["close"]).any():
            raise ValueError("Low cannot be higher than close")

        if isinstance(data.index, pd.DatetimeIndex):
            if not data.index.is_monotonic_increasing:
                raise ValueError("Data must be chronological")
            if data.index.has_duplicates:
                raise ValueError("Duplicate timestamps")

        if "timestamp" in data.columns:
            timestamps = pd.to_numeric(
                data["timestamp"], errors="coerce"
            )
            if timestamps.isna().any():
                raise ValueError("Invalid timestamps")
            if timestamps.duplicated().any():
                raise ValueError("Duplicate timestamps")
            if not timestamps.is_monotonic_increasing:
                raise ValueError("Data must be chronological")

        return data

    @staticmethod
    def find_swings(df, left=3, right=3):
        """
        使用左右 K 線確認 Swing High / Swing Low。

        right 根後續 K 線收盤後才確認轉折，
        避免把尚未確認的轉折當成即時訊號。
        """
        FibonacciEngine._validate_period(left, "left")
        FibonacciEngine._validate_period(right, "right")

        data = FibonacciEngine.validate_data(df)

        highs = data["high"].to_numpy(dtype=float)
        lows = data["low"].to_numpy(dtype=float)

        swing_highs = []
        swing_lows = []

        for i in range(left, len(data) - right):
            high_window = highs[i-left:i+right+1]
            low_window = lows[i-left:i+right+1]

            # 相同高低點只保留最早出現者。
            if (
                highs[i] == np.max(high_window)
                and np.argmax(high_window) == left
            ):
                swing_highs.append({
                    "index": data.index[i],
                    "position": i,
                    "price": float(highs[i]),
                    "confirmed_position": i + right
                })

            if (
                lows[i] == np.min(low_window)
                and np.argmin(low_window) == left
            ):
                swing_lows.append({
                    "index": data.index[i],
                    "position": i,
                    "price": float(lows[i]),
                    "confirmed_position": i + right
                })

        return {
            "swing_highs": swing_highs,
            "swing_lows": swing_lows
        }

    @staticmethod
    def calculate_retracement(swing_low, swing_high):
        """上升波段的 Fibonacci 回檔價位。"""
        if swing_low <= 0 or swing_high <= swing_low:
            raise ValueError("Invalid bullish swing prices")

        distance = swing_high - swing_low

        return {
            level: round(
                swing_high - distance * level, 10
            )
            for level in FibonacciEngine.RETRACEMENT_LEVELS
        }

    @staticmethod
    def calculate_bearish_retracement(swing_high, swing_low):
        """下降波段的 Fibonacci 反彈價位。"""
        if swing_low <= 0 or swing_high <= swing_low:
            raise ValueError("Invalid bearish swing prices")

        distance = swing_high - swing_low

        return {
            level: round(
                swing_low + distance * level, 10
            )
            for level in FibonacciEngine.RETRACEMENT_LEVELS
        }

    @staticmethod
    def calculate_extension(swing_low, swing_high):
        """上升波段的 Fibonacci 延伸目標。"""
        if swing_low <= 0 or swing_high <= swing_low:
            raise ValueError("Invalid bullish swing prices")

        distance = swing_high - swing_low

        return {
            level: round(
                swing_low + distance * level, 10
            )
            for level in FibonacciEngine.EXTENSION_LEVELS
        }

    @staticmethod
    def calculate_bearish_extension(swing_high, swing_low):
        """下降波段的 Fibonacci 向下延伸目標。"""
        if swing_low <= 0 or swing_high <= swing_low:
            raise ValueError("Invalid bearish swing prices")

        distance = swing_high - swing_low

        return {
            level: round(
                swing_high - distance * level, 10
            )
            for level in FibonacciEngine.EXTENSION_LEVELS
        }

    @staticmethod
    def analyze(df, left=3, right=3):
        """
        以最新已確認 Swing High / Swing Low
        分別建立多方及空方 Fibonacci 參考區。
        """
        data = FibonacciEngine.validate_data(df)

        swings = FibonacciEngine.find_swings(
            data, left=left, right=right
        )

        latest_position = len(data) - 1

        confirmed_highs = [
            item for item in swings["swing_highs"]
            if item["confirmed_position"] <= latest_position
        ]

        confirmed_lows = [
            item for item in swings["swing_lows"]
            if item["confirmed_position"] <= latest_position
        ]

        bullish = None
        bearish = None

        # 多方：最近低點之後出現高點。
        bullish_candidates = []

        for high in confirmed_highs:
            prior_lows = [
                low for low in confirmed_lows
                if low["position"] < high["position"]
            ]

            if prior_lows:
                low = prior_lows[-1]
                if high["price"] > low["price"]:
                    bullish_candidates.append((low, high))

        if bullish_candidates:
            low, high = bullish_candidates[-1]

            bullish = {
                "swing_low": low,
                "swing_high": high,
                "retracement": FibonacciEngine.calculate_retracement(
                    low["price"], high["price"]
                ),
                "extension": FibonacciEngine.calculate_extension(
                    low["price"], high["price"]
                )
            }

        # 空方：最近高點之後出現低點。
        bearish_candidates = []

        for low in confirmed_lows:
            prior_highs = [
                high for high in confirmed_highs
                if high["position"] < low["position"]
            ]

            if prior_highs:
                high = prior_highs[-1]
                if high["price"] > low["price"]:
                    bearish_candidates.append((high, low))

        if bearish_candidates:
            high, low = bearish_candidates[-1]

            bearish = {
                "swing_high": high,
                "swing_low": low,
                "retracement": (
                    FibonacciEngine.calculate_bearish_retracement(
                        high["price"], low["price"]
                    )
                ),
                "extension": (
                    FibonacciEngine.calculate_bearish_extension(
                        high["price"], low["price"]
                    )
                )
            }

        current_price = float(data["close"].iloc[-1])

        return {
            "current_price": current_price,
            "swings": swings,
            "bullish": bullish,
            "bearish": bearish
        }
