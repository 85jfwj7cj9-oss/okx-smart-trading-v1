
import json
import math
import os
import sqlite3
import threading

from datetime import datetime, timezone

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None


class Database:
    """
    OKX SMART TRADING V1.2

    支援：
    - SQLite：本機及 GitHub Actions 測試
    - PostgreSQL：Render 正式部署

    僅保存行情分析及模擬交易資料。
    不執行真實交易。
    """

    def __init__(self, database_path=None):
        self._lock = threading.RLock()

        self.database_url = ""
        self.database_path = None

        if database_path is not None:
            self.database_path = str(database_path)
            self.backend = "sqlite"
        else:
            self.database_url = os.getenv(
                "DATABASE_URL", ""
            ).strip()

            if self.database_url.startswith("postgres://"):
                self.database_url = (
                    "postgresql://"
                    + self.database_url[len("postgres://"):]
                )

            if self.database_url:
                self.backend = "postgresql"
            else:
                self.backend = "sqlite"
                self.database_path = os.getenv(
                    "DATABASE_PATH",
                    "data/okx_trading.db"
                )

        self.connect_timeout = self._safe_int(
            os.getenv("DATABASE_CONNECT_TIMEOUT", "15"),
            15,
            1,
            120
        )

        if self.backend == "sqlite":
            if self.database_path != ":memory:":
                directory = os.path.dirname(
                    os.path.abspath(self.database_path)
                )
                os.makedirs(directory, exist_ok=True)

        self.initialize()

    @staticmethod
    def _safe_int(value, default, minimum, maximum):
        try:
            result = int(value)
        except (TypeError, ValueError):
            result = default

        return max(minimum, min(result, maximum))

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json(data):
        return json.dumps(
            data,
            ensure_ascii=False,
            default=str,
            allow_nan=False
        )

    @staticmethod
    def _number(value, name, positive=False):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be numeric")

        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite")

        if positive and number <= 0:
            raise ValueError(f"{name} must be positive")

        return number

    def _connect(self):
        if self.backend == "postgresql":
            if psycopg is None:
                raise RuntimeError(
                    "PostgreSQL driver is not installed"
                )

            return psycopg.connect(
                self.database_url,
                connect_timeout=self.connect_timeout,
                row_factory=dict_row
            )

        connection = sqlite3.connect(
            self.database_path,
            timeout=15
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")

        return connection

    def _sql(self, statement):
        if self.backend == "postgresql":
            return statement.replace("?", "%s")
        return statement

    def _table_statements(self):
        if self.backend == "postgresql":
            return [
                """
                CREATE TABLE IF NOT EXISTS scan_history (
                    id BIGSERIAL PRIMARY KEY,
                    scan_time TEXT NOT NULL,
                    total_scanned INTEGER DEFAULT 0,
                    successful INTEGER DEFAULT 0,
                    failed INTEGER DEFAULT 0,
                    long_count INTEGER DEFAULT 0,
                    short_count INTEGER DEFAULT 0,
                    strong_coin_count INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    result_json TEXT
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS signal_history (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    score DOUBLE PRECISION DEFAULT 0,
                    entry_price DOUBLE PRECISION,
                    stop_loss DOUBLE PRECISION,
                    take_profit DOUBLE PRECISION,
                    relative_strength_1h DOUBLE PRECISION,
                    relative_strength_4h DOUBLE PRECISION,
                    signal_time TEXT NOT NULL,
                    status TEXT DEFAULT 'observing',
                    result_json TEXT,
                    take_profit_1 DOUBLE PRECISION,
                    take_profit_2 DOUBLE PRECISION
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS notification_history (
                    id BIGSERIAL PRIMARY KEY,
                    notification_key TEXT NOT NULL UNIQUE,
                    symbol TEXT,
                    direction TEXT,
                    message TEXT,
                    sent_time TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS simulated_trades (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price DOUBLE PRECISION NOT NULL,
                    stop_loss DOUBLE PRECISION NOT NULL,
                    take_profit DOUBLE PRECISION NOT NULL,
                    quantity DOUBLE PRECISION NOT NULL,
                    notional_usdt DOUBLE PRECISION NOT NULL,
                    leverage DOUBLE PRECISION NOT NULL,
                    entry_time TEXT NOT NULL,
                    exit_price DOUBLE PRECISION,
                    exit_time TEXT,
                    pnl_usdt DOUBLE PRECISION,
                    status TEXT DEFAULT 'open',
                    result_json TEXT,
                    take_profit_1 DOUBLE PRECISION,
                    take_profit_2 DOUBLE PRECISION,
                    fees_usdt DOUBLE PRECISION DEFAULT 0,
                    slippage_usdt DOUBLE PRECISION DEFAULT 0,
                    net_pnl_usdt DOUBLE PRECISION
                )
                """
            ]

        return [
            """
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_time TEXT NOT NULL,
                total_scanned INTEGER DEFAULT 0,
                successful INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                long_count INTEGER DEFAULT 0,
                short_count INTEGER DEFAULT 0,
                strong_coin_count INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                result_json TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                score REAL DEFAULT 0,
                entry_price REAL,
                stop_loss REAL,
                take_profit REAL,
                relative_strength_1h REAL,
                relative_strength_4h REAL,
                signal_time TEXT NOT NULL,
                status TEXT DEFAULT 'observing',
                result_json TEXT,
                take_profit_1 REAL,
                take_profit_2 REAL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS notification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_key TEXT NOT NULL UNIQUE,
                symbol TEXT,
                direction TEXT,
                message TEXT,
                sent_time TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS simulated_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                quantity REAL NOT NULL,
                notional_usdt REAL NOT NULL,
                leverage REAL NOT NULL,
                entry_time TEXT NOT NULL,
                exit_price REAL,
                exit_time TEXT,
                pnl_usdt REAL,
                status TEXT DEFAULT 'open',
                result_json TEXT,
                take_profit_1 REAL,
                take_profit_2 REAL,
                fees_usdt REAL DEFAULT 0,
                slippage_usdt REAL DEFAULT 0,
                net_pnl_usdt REAL
            )
            """
        ]

    def _ensure_columns(self, connection, table, columns):
        if self.backend == "postgresql":
            for name, definition in columns.items():
                connection.execute(
                    f"ALTER TABLE {table} "
                    f"ADD COLUMN IF NOT EXISTS {name} {definition}"
                )
            return

        existing = {
            row["name"]
            for row in connection.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        }

        for name, definition in columns.items():
            if name not in existing:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN "
                    f"{name} {definition}"
                )

    def initialize(self):
        """建立資料表、索引及安全升級舊版欄位。"""

        indexes = [
            """
            CREATE INDEX IF NOT EXISTS idx_scan_time
            ON scan_history(scan_time)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_signal_symbol
            ON signal_history(symbol)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_signal_time
            ON signal_history(signal_time)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trade_status
            ON simulated_trades(status)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trade_symbol
            ON simulated_trades(symbol)
            """
        ]

        with self._lock:
            connection = self._connect()

            try:
                with connection:
                    for statement in self._table_statements():
                        connection.execute(statement)

                    self._ensure_columns(
                        connection,
                        "signal_history",
                        {
                            "take_profit_1": (
                                "DOUBLE PRECISION"
                                if self.backend == "postgresql"
                                else "REAL"
                            ),
                            "take_profit_2": (
                                "DOUBLE PRECISION"
                                if self.backend == "postgresql"
                                else "REAL"
                            )
                        }
                    )

                    numeric_type = (
                        "DOUBLE PRECISION"
                        if self.backend == "postgresql"
                        else "REAL"
                    )

                    self._ensure_columns(
                        connection,
                        "simulated_trades",
                        {
                            "take_profit_1": numeric_type,
                            "take_profit_2": numeric_type,
                            "fees_usdt": (
                                f"{numeric_type} DEFAULT 0"
                            ),
                            "slippage_usdt": (
                                f"{numeric_type} DEFAULT 0"
                            ),
                            "net_pnl_usdt": numeric_type
                        }
                    )

                    for statement in indexes:
                        connection.execute(statement)

            finally:
                connection.close()

    def _execute_insert(self, sql, values):
        with self._lock:
            connection = self._connect()

            try:
                with connection:
                    if self.backend == "postgresql":
                        cursor = connection.execute(
                            self._sql(sql) + " RETURNING id",
                            values
                        )
                        row = cursor.fetchone()
                        return row["id"]

                    cursor = connection.execute(sql, values)
                    return cursor.lastrowid

            finally:
                connection.close()

    def _fetch_all(self, sql, values=()):
        with self._lock:
            connection = self._connect()

            try:
                rows = connection.execute(
                    self._sql(sql), values
                ).fetchall()

                return [dict(row) for row in rows]

            finally:
                connection.close()

    def _fetch_one(self, sql, values=()):
        rows = self._fetch_all(sql, values)
        return rows[0] if rows else None

    def save_scan(self, result):
        if not isinstance(result, dict):
            raise ValueError("result must be a dictionary")

        result_json = self._json(result)

        return self._execute_insert(
            """
            INSERT INTO scan_history (
                scan_time, total_scanned, successful,
                failed, long_count, short_count,
                strong_coin_count, status, result_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.get("finished_at", self._now()),
                int(result.get("total_scanned", 0)),
                int(result.get("successful", 0)),
                int(result.get("failed", 0)),
                int(result.get("long_count", 0)),
                int(result.get("short_count", 0)),
                int(result.get("strong_coin_count", 0)),
                str(result.get("status", "unknown")),
                result_json
            )
        )

    def save_signal(self, result):
        if not isinstance(result, dict):
            raise ValueError("result must be a dictionary")

        strategy = result.get("strategy") or {}
        plan = result.get("trade_plan") or {}
        relative = result.get("relative_strength") or {}

        if not all(isinstance(item, dict) for item in (
            strategy, plan, relative
        )):
            raise ValueError("Invalid signal data")

        direction = str(
            strategy.get(
                "direction",
                result.get("direction", "NEUTRAL")
            )
        ).upper()

        if direction not in ("LONG", "SHORT"):
            raise ValueError("Invalid signal direction")

        if plan.get("status") != "simulation_only":
            raise ValueError("Only simulation plans can be saved")

        entry = self._number(
            plan.get("entry_price"), "entry_price", True
        )
        stop = self._number(
            plan.get("stop_loss"), "stop_loss", True
        )

        tp1_value = plan.get(
            "take_profit_1",
            plan.get("tp1", plan.get("take_profit"))
        )
        tp2_value = plan.get(
            "take_profit_2",
            plan.get("tp2")
        )

        tp1 = self._number(
            tp1_value, "take_profit_1", True
        )

        tp2 = (
            self._number(tp2_value, "take_profit_2", True)
            if tp2_value is not None else None
        )

        if direction == "LONG":
            if not stop < entry < tp1:
                raise ValueError("Invalid LONG price levels")
            if tp2 is not None and tp2 <= tp1:
                raise ValueError("Invalid LONG TP2")
        else:
            if not tp1 < entry < stop:
                raise ValueError("Invalid SHORT price levels")
            if tp2 is not None and tp2 >= tp1:
                raise ValueError("Invalid SHORT TP2")

        score = self._number(
            strategy.get(
                "score",
                strategy.get("signal_score", 0)
            ),
            "score"
        )

        return self._execute_insert(
            """
            INSERT INTO signal_history (
                symbol, direction, score,
                entry_price, stop_loss, take_profit,
                take_profit_1, take_profit_2,
                relative_strength_1h, relative_strength_4h,
                signal_time, status, result_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.get("symbol", "UNKNOWN"),
                direction,
                score,
                entry,
                stop,
                tp1,
                tp1,
                tp2,
                relative.get("1H"),
                relative.get("4H"),
                self._now(),
                "observing",
                self._json(result)
            )
        )

    def save_notification(
        self,
        notification_key,
        symbol,
        direction,
        message,
        status="sent",
        error_message=None
    ):
        if not notification_key:
            raise ValueError("notification_key is required")

        try:
            return self._execute_insert(
                """
                INSERT INTO notification_history (
                    notification_key, symbol, direction,
                    message, sent_time, status, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notification_key,
                    symbol,
                    direction,
                    message,
                    self._now(),
                    status,
                    error_message
                )
            )

        except sqlite3.IntegrityError:
            return None

        except Exception as exc:
            if (
                psycopg is not None
                and isinstance(exc, psycopg.IntegrityError)
            ):
                return None
            raise

    def notification_exists(self, notification_key):
        row = self._fetch_one(
            """
            SELECT id FROM notification_history
            WHERE notification_key = ?
            """,
            (notification_key,)
        )
        return row is not None

    def create_simulated_trade(self, trade_plan):
        if not isinstance(trade_plan, dict):
            raise ValueError("trade_plan must be a dictionary")

        if trade_plan.get("status") != "simulation_only":
            raise ValueError("Only simulation trades are supported")

        position = trade_plan.get("position") or {}

        if not isinstance(position, dict):
            raise ValueError("Invalid position data")

        symbol = trade_plan.get("symbol")
        direction = str(
            trade_plan.get("direction", "")
        ).upper()

        if not symbol:
            raise ValueError("symbol is required")

        if direction not in ("LONG", "SHORT"):
            raise ValueError("Invalid trade direction")

        try:
            entry = self._number(
                trade_plan["entry_price"], "entry_price", True
            )
            stop = self._number(
                trade_plan["stop_loss"], "stop_loss", True
            )

            target = self._number(
                trade_plan.get(
                    "take_profit_1",
                    trade_plan.get(
                        "tp1",
                        trade_plan.get("take_profit")
                    )
                ),
                "take_profit_1",
                True
            )

            tp2_value = trade_plan.get(
                "take_profit_2",
                trade_plan.get("tp2")
            )

            tp2 = (
                self._number(
                    tp2_value, "take_profit_2", True
                )
                if tp2_value is not None else None
            )

            quantity = self._number(
                position["quantity"], "quantity", True
            )
            notional = self._number(
                position["notional_usdt"], "notional_usdt", True
            )
            leverage = self._number(
                position["leverage"], "leverage", True
            )

        except (KeyError, TypeError):
            raise ValueError("Invalid trade plan values")

        if direction == "LONG":
            if not stop < entry < target:
                raise ValueError("Invalid LONG price levels")
            if tp2 is not None and tp2 <= target:
                raise ValueError("Invalid LONG TP2")
        else:
            if not target < entry < stop:
                raise ValueError("Invalid SHORT price levels")
            if tp2 is not None and tp2 >= target:
                raise ValueError("Invalid SHORT TP2")

        fees = self._number(
            trade_plan.get("fees_usdt", 0), "fees_usdt"
        )
        slippage = self._number(
            trade_plan.get("slippage_usdt", 0),
            "slippage_usdt"
        )

        if fees < 0 or slippage < 0:
            raise ValueError(
                "Fees and slippage cannot be negative"
            )

        return self._execute_insert(
            """
            INSERT INTO simulated_trades (
                symbol, direction, entry_price,
                stop_loss, take_profit,
                take_profit_1, take_profit_2,
                quantity, notional_usdt, leverage,
                entry_time, status, result_json,
                fees_usdt, slippage_usdt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                direction,
                entry,
                stop,
                target,
                target,
                tp2,
                quantity,
                notional,
                leverage,
                self._now(),
                "open",
                self._json(trade_plan),
                fees,
                slippage
            )
        )

    def close_simulated_trade(self, trade_id, exit_price):
        exit_price = self._number(
            exit_price, "exit_price", True
        )

        with self._lock:
            connection = self._connect()

            try:
                with connection:
                    row = connection.execute(
                        self._sql(
                            """
                            SELECT * FROM simulated_trades
                            WHERE id = ?
                            """
                        ),
                        (trade_id,)
                    ).fetchone()

                    if row is None or row["status"] != "open":
                        return False

                    if row["direction"] == "LONG":
                        pnl = (
                            exit_price - row["entry_price"]
                        ) * row["quantity"]

                    elif row["direction"] == "SHORT":
                        pnl = (
                            row["entry_price"] - exit_price
                        ) * row["quantity"]

                    else:
                        raise ValueError(
                            "Invalid stored direction"
                        )

                    fees = row.get("fees_usdt", 0) or 0
                    slippage = row.get("slippage_usdt", 0) or 0
                    net_pnl = pnl - fees - slippage

                    connection.execute(
                        self._sql(
                            """
                            UPDATE simulated_trades
                            SET exit_price = ?,
                                exit_time = ?,
                                pnl_usdt = ?,
                                net_pnl_usdt = ?,
                                status = 'closed'
                            WHERE id = ?
                            """
                        ),
                        (
                            exit_price,
                            self._now(),
                            pnl,
                            net_pnl,
                            trade_id
                        )
                    )

                    return True

            finally:
                connection.close()

    def get_scan_history(self, limit=50):
        limit = max(1, min(int(limit), 500))

        return self._fetch_all(
            """
            SELECT * FROM scan_history
            ORDER BY id DESC LIMIT ?
            """,
            (limit,)
        )

    def get_signal_history(self, limit=50):
        limit = max(1, min(int(limit), 500))

        return self._fetch_all(
            """
            SELECT * FROM signal_history
            ORDER BY id DESC LIMIT ?
            """,
            (limit,)
        )

    def get_simulated_trades(self, status=None, limit=100):
        limit = max(1, min(int(limit), 500))

        if status is None:
            return self._fetch_all(
                """
                SELECT * FROM simulated_trades
                ORDER BY id DESC LIMIT ?
                """,
                (limit,)
            )

        return self._fetch_all(
            """
            SELECT * FROM simulated_trades
            WHERE status = ?
            ORDER BY id DESC LIMIT ?
            """,
            (status, limit)
        )

    def get_trade_statistics(self):
        row = self._fetch_one(
            """
            SELECT
                COUNT(*) AS total_trades,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END)
                    AS open_trades,
                SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END)
                    AS closed_trades,
                SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END)
                    AS winning_trades,
                SUM(CASE WHEN pnl_usdt < 0 THEN 1 ELSE 0 END)
                    AS losing_trades,
                COALESCE(SUM(pnl_usdt), 0) AS gross_pnl_usdt,
                COALESCE(SUM(net_pnl_usdt), 0) AS net_pnl_usdt
            FROM simulated_trades
            """
        ) or {}

        closed = row.get("closed_trades") or 0
        wins = row.get("winning_trades") or 0

        return {
            "total_trades": row.get("total_trades") or 0,
            "open_trades": row.get("open_trades") or 0,
            "closed_trades": closed,
            "winning_trades": wins,
            "losing_trades": row.get("losing_trades") or 0,
            "gross_pnl_usdt": round(
                row.get("gross_pnl_usdt") or 0, 4
            ),
            "net_pnl_usdt": round(
                row.get("net_pnl_usdt") or 0, 4
            ),
            "win_rate_percent": round(
                wins / closed * 100, 2
            ) if closed else 0,
            "trading_mode": "simulation_only"
        }

    def health_check(self):
        try:
            row = self._fetch_one(
                "SELECT 1 AS result"
            )

            return {
                "status": (
                    "ok"
                    if row and row["result"] == 1
                    else "error"
                ),
                "database": self.backend
            }

        except Exception:
            return {
                "status": "error",
                "database": self.backend
            }
