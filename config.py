
import os


def get_bool(name, default=False):
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1", "true", "yes", "on"
    }


def get_int(name, default, minimum=None, maximum=None):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default

    if minimum is not None:
        value = max(minimum, value)

    if maximum is not None:
        value = min(maximum, value)

    return value


def get_float(name, default, minimum=None, maximum=None):
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default

    if minimum is not None:
        value = max(minimum, value)

    if maximum is not None:
        value = min(maximum, value)

    return value


class Config:

    # Application
    APP_NAME = "OKX SMART TRADING V1.0"
    APP_ENV = os.getenv("APP_ENV", "development")
    TIMEZONE = os.getenv("TIMEZONE", "Asia/Taipei")

    SECRET_KEY = os.getenv(
        "APP_SECRET_KEY",
        "development-only-change-before-deployment"
    )

    ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

    # OKX public market data
    OKX_BASE_URL = os.getenv(
        "OKX_BASE_URL",
        "https://www.okx.com"
    ).rstrip("/")

    # Current version uses public market data only.
    OKX_DEMO_MODE = True

    # Scanner
    SCAN_INTERVAL_SECONDS = get_int(
        "SCAN_INTERVAL_SECONDS", 60, 15, 3600
    )

    TOP_N_SYMBOLS = get_int(
        "TOP_N_SYMBOLS",
        get_int("MAX_SCAN_SYMBOLS", 20, 1, 100),
        1,
        100
    )

    TIMEFRAMES = ("1H", "4H")
    ALLOWED_TIMEFRAMES = ("1H", "4H")

    BTC_BENCHMARK = os.getenv(
        "BTC_BENCHMARK",
        "BTC-USDT-SWAP"
    )

    # Strategy
    MIN_SIGNAL_SCORE = get_int(
        "MIN_SIGNAL_SCORE", 60, 0, 100
    )

    ENABLE_LONG = get_bool("ENABLE_LONG", True)
    ENABLE_SHORT = get_bool("ENABLE_SHORT", True)

    # Risk management - simulation only
    INITIAL_EQUITY_USDT = get_float(
        "INITIAL_EQUITY_USDT", 1000, 0.01
    )

    RISK_PER_TRADE_PERCENT = get_float(
        "RISK_PER_TRADE_PERCENT", 1, 0.01, 5
    )

    SIMULATED_LEVERAGE = get_float(
        "SIMULATED_LEVERAGE", 5, 1, 20
    )

    TAKER_FEE_RATE = get_float(
        "TAKER_FEE_RATE", 0.0005, 0, 0.1
    )

    SLIPPAGE_RATE = get_float(
        "SLIPPAGE_RATE", 0.0005, 0, 0.1
    )

    # LINE
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv(
        "LINE_CHANNEL_ACCESS_TOKEN", ""
    )

    LINE_CHANNEL_SECRET = os.getenv(
        "LINE_CHANNEL_SECRET", ""
    )

    LINE_TO_USER_ID = os.getenv(
        "LINE_TO_USER_ID", ""
    )

    LINE_ENABLED = get_bool(
        "LINE_ENABLED", False
    )

    # Database
    DATABASE_URL = os.getenv(
        "DATABASE_URL", ""
    )

    # Trading safety
    AUTO_TRADING_ENABLED = False
    LIVE_ORDER_ENABLED = False

    @classmethod
    def validate(cls):
        errors = []

        if not cls.TIMEFRAMES:
            errors.append("TIMEFRAMES cannot be empty")

        invalid = [
            item for item in cls.TIMEFRAMES
            if item not in cls.ALLOWED_TIMEFRAMES
        ]

        if invalid:
            errors.append(
                f"Invalid timeframes: {invalid}"
            )

        if not 0 < cls.RISK_PER_TRADE_PERCENT <= 5:
            errors.append("Invalid risk percentage")

        if cls.INITIAL_EQUITY_USDT <= 0:
            errors.append("Initial equity must be positive")

        if not 1 <= cls.SIMULATED_LEVERAGE <= 20:
            errors.append("Invalid simulated leverage")

        if not 0 <= cls.MIN_SIGNAL_SCORE <= 100:
            errors.append("Invalid minimum signal score")

        return errors


def get_config():
    return Config
