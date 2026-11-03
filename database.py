
import json
import os
import sqlite3
import threading

from datetime import datetime, timezone


class Database:
    """
    OKX SMART TRADING V1.0
    SQLite 資料庫管理模組。

    僅保存行情分析及模擬交易資料。
    不執行真實交易。
    """

    def __init__(self, database_path=None):
        self.database_path = (
            database_path
            or os.getenv("DATABASE_PATH", "data/okx_trading.db")
        )

        self._lock = threading.RLock()

        if self.database_path != ":memory:":
            directory = os.path.dirname(
                os.path.abspath(self.database_path)
            )
            os.makedirs(directory, exist_ok=True)

        self.initialize()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path,
            timeout=15
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def initialize(self):
        """建立資料表及索引。"""

        statements = [
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
                result_json TEXT
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
                result_json TEXT
            )
            """
        ]

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
            """
        ]

        with self._lock:
            connection = self._connect()
            try:
                with connection:
                    for statement in statements:
                        connection.execute(statement)

                    for statement in indexes:
                        connection.execute(statement)
            finally:
                connection.close()

    def _execute_insert(self, sql, values):
        with self._lock:
            connection = self._connect()
            try:
                with connection:
                    cursor = connection.execute(sql, values)
                    return cursor.lastrowid
            finally:
                connection.close()

    def _fetch_all(self, sql, values=()):
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    sql, values
                ).fetchall()
                return [dict(row) for row in rows]
            finally:
                connection.close()

    def _fetch_one(self, sql, values=()):
        rows = self._fetch_all(sql, values)
        return rows[0] if rows else None

    def save_scan(self, result):
        """保存一輪掃描結果。"""

        if not isinstance(result, dict):
            raise ValueError("result must be a dictionary")

        result_json = json.dumps(
            result,
            ensure_ascii=False,
            default=str
        )

        return self._execute_insert(
            """
            INSERT INTO scan_history (
                scan_time,
                total_scanned,
                successful,
                failed,
                long_count,
                short_count,
                strong_coin_count,
                status,
                result_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.get("finished_at", self._now()),
                result.get("total_scanned", 0),
                result.get("successful", 0),
                result.get("failed", 0),
                result.get("long_count", 0),
                result.get("short_count", 0),
                result.get("strong_coin_count", 0),
                result.get("status", "unknown"),
                result_json
            )
        )

    def save_signal(self, result):
        """保存具有完整模擬交易計畫的訊號。"""

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

        prices = [
            plan.get("entry_price"),
            plan.get("stop_loss"),
            plan.get("take_profit")
        ]

        if any(value is None for value in prices):
            raise ValueError("Trade plan prices are incomplete")

        return self._execute_insert(
            """
            INSERT INTO signal_history (
                symbol, direction, score,
                entry_price, stop_loss, take_profit,
                relative_strength_1h, relative_strength_4h,
                signal_time, status, result_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.get("symbol", "UNKNOWN"),
                direction,
                strategy.get(
                    "score",
                    strategy.get("signal_score", 0)
                ),
                *prices,
                relative.get("1H"),
                relative.get("4H"),
                self._now(),
                "observing",
                json.dumps(
                    result,
                    ensure_ascii=False,
                    default=str
                )
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
        """保存通知紀錄；相同 key 不會重複新增。"""

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

    def notification_exists(self, notification_key):
        """檢查通知紀錄是否存在。"""

        row = self._fetch_one(
            """
            SELECT id FROM notification_history
            WHERE notification_key = ?
            """,
            (notification_key,)
        )
        return row is not None

    def create_simulated_trade(self, trade_plan):
        """建立模擬交易紀錄，不會送出真實訂單。"""

        if not isinstance(trade_plan, dict):
            raise ValueError("trade_plan must be a dictionary")

        if trade_plan.get("status") != "simulation_only":
            raise ValueError("Only simulation trades are supported")

        position = trade_plan.get("position") or {}

        if not isinstance(position, dict):
            raise ValueError("Invalid position data")

        symbol = trade_plan.get("symbol")
        direction = trade_plan.get("direction")

        if not symbol:
            raise ValueError("symbol is required")

        if direction not in ("LONG", "SHORT"):
            raise ValueError("Invalid trade direction")

        try:
            entry = float(trade_plan["entry_price"])
            stop = float(trade_plan["stop_loss"])
            target = float(trade_plan["take_profit"])
            quantity = float(position["quantity"])
            notional = float(position["notional_usdt"])
            leverage = float(position["leverage"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Invalid trade plan values")

        values = [
            entry, stop, target,
            quantity, notional, leverage
        ]

        if any(value <= 0 for value in values):
            raise ValueError("Trade values must be positive")

        if direction == "LONG" and not stop < entry < target:
            raise ValueError("Invalid LONG price levels")

        if direction == "SHORT" and not target < entry < stop:
            raise ValueError("Invalid SHORT price levels")

        return self._execute_insert(
            """
            INSERT INTO simulated_trades (
                symbol, direction, entry_price,
                stop_loss, take_profit, quantity,
                notional_usdt, leverage, entry_time,
                status, result_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                direction,
                entry,
                stop,
                target,
                quantity,
                notional,
                leverage,
                self._now(),
                "open",
                json.dumps(
                    trade_plan,
                    ensure_ascii=False,
                    default=str
                )
            )
        )

    def close_simulated_trade(self, trade_id, exit_price):
        """結束模擬交易，計算未扣手續費及滑價的毛損益。"""

        try:
            exit_price = float(exit_price)
        except (TypeError, ValueError):
            raise ValueError("exit_price must be numeric")

        if exit_price <= 0:
            raise ValueError("exit_price must be positive")

        with self._lock:
            connection = self._connect()
            try:
                with connection:
                    row = connection.execute(
                        """
                        SELECT * FROM simulated_trades
                        WHERE id = ?
                        """,
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
                        raise ValueError("Invalid stored direction")

                    connection.execute(
                        """
                        UPDATE simulated_trades
                        SET exit_price = ?,
                            exit_time = ?,
                            pnl_usdt = ?,
                            status = 'closed'
                        WHERE id = ?
                        """,
                        (
                            exit_price,
                            self._now(),
                            pnl,
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
        """取得模擬交易統計。"""

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
                COALESCE(SUM(pnl_usdt), 0) AS gross_pnl_usdt
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
            "win_rate_percent": round(
                wins / closed * 100, 2
            ) if closed else 0,
            "trading_mode": "simulation_only"
        }

    def health_check(self):
        """檢查資料庫是否可以正常讀取。"""

        try:
            row = self._fetch_one("SELECT 1 AS result")

            return {
                "status": (
                    "ok"
                    if row and row["result"] == 1
                    else "error"
                ),
                "database": "sqlite"
            }
        except sqlite3.Error:
            return {
                "status": "error",
                "database": "sqlite"
            }
