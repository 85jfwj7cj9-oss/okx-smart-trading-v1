
import hashlib
import logging
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config import Config
from scanner import MarketScanner
from line_notifier import LineNotifier
from database import Database


logger = logging.getLogger(__name__)


class TradingScheduler:
    """
    OKX SMART TRADING V1.1

    定時市場掃描、資料庫保存及 LINE 通知排程。

    支援：
    - LONG-A 提前埋伏做多
    - LONG-B 突破確認做多
    - SHORT-A 提前埋伏做空
    - SHORT-B 跌破確認做空
    - 掃描歷史保存
    - 策略訊號歷史保存
    - LINE 通知成功及失敗紀錄
    - 持久化通知防重複

    僅提供模擬交易訊號，不執行真實下單。
    """

    STRATEGY_LISTS = {
        "LONG-A": "long_a_candidates",
        "LONG-B": "long_b_candidates",
        "SHORT-A": "short_a_candidates",
        "SHORT-B": "short_b_candidates"
    }

    def __init__(
        self,
        scanner=None,
        notifier=None,
        database=None,
        interval_seconds=None,
        summary_hour=21
    ):
        self.scanner = scanner or MarketScanner()
        self.notifier = notifier or LineNotifier()
        self.database = database or Database()

        self.interval_seconds = max(
            15,
            int(
                interval_seconds
                if interval_seconds is not None
                else Config.SCAN_INTERVAL_SECONDS
            )
        )

        if not 0 <= summary_hour <= 23:
            raise ValueError(
                "summary_hour must be between 0 and 23"
            )

        self.summary_hour = summary_hour

        self._stop_event = threading.Event()
        self._scan_lock = threading.Lock()
        self._thread = None

        self._last_summary_date = None
        self._last_scan_result = None

    @property
    def is_running(self):
        return (
            self._thread is not None
            and self._thread.is_alive()
        )

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_float(value, default=None):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return default

        if number != number or number in (
            float("inf"),
            float("-inf")
        ):
            return default

        return number

    @staticmethod
    def _notification_key(candidate):
        """
        產生與 LineNotifier.send_signal 相同的訊號識別碼。
        """

        plan = candidate.get("trade_plan") or {}

        symbol = str(candidate.get("symbol", "UNKNOWN"))
        direction = str(
            candidate.get("direction", "NEUTRAL")
        ).upper()

        entry = plan.get("entry_price")
        stop = plan.get("stop_loss")
        target = plan.get(
            "take_profit",
            plan.get("tp1", plan.get("take_profit_1"))
        )

        return (
            f"{symbol}:{direction}:"
            f"{entry}:{stop}:{target}"
        )

    @classmethod
    def _get_strategy_candidates(cls, scan_result):
        """
        取得四種策略的獨立候選訊號。
        """

        candidates = []

        for strategy_name, list_name in (
            cls.STRATEGY_LISTS.items()
        ):
            items = scan_result.get(list_name, [])

            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue

                candidate = dict(item)

                candidate["strategy_name"] = strategy_name

                candidates.append(candidate)

        return candidates

    @staticmethod
    def _normalize_trade_plan(candidate):
        """
        將 scanner 的交易計畫轉換成
        LineNotifier 與 Database 可使用的格式。
        """

        plan = candidate.get("trade_plan")

        if not isinstance(plan, dict):
            return None

        plan = dict(plan)

        if plan.get("status") != "simulation_only":
            return None

        tp1 = plan.get(
            "take_profit_1",
            plan.get("tp1", plan.get("take_profit"))
        )

        if tp1 is None:
            return None

        entry = plan.get("entry_price")
        stop = plan.get("stop_loss")

        if entry is None or stop is None:
            return None

        plan["entry_price"] = entry
        plan["stop_loss"] = stop
        plan["take_profit"] = tp1
        plan["take_profit_1"] = tp1

        tp2 = plan.get(
            "take_profit_2",
            plan.get("tp2")
        )

        if tp2 is not None:
            plan["take_profit_2"] = tp2

        plan["direction"] = str(
            candidate.get("direction", "")
        ).upper()

        plan["symbol"] = candidate.get("symbol")

        return plan

    @classmethod
    def _normalize_candidate(cls, candidate):
        """
        將四策略排行榜格式轉成通知及資料庫格式。
        """

        if not isinstance(candidate, dict):
            return None

        strategy_name = str(
            candidate.get(
                "strategy_name",
                candidate.get("strategy", "")
            )
        ).upper()

        if strategy_name not in cls.STRATEGY_LISTS:
            return None

        direction = (
            "LONG"
            if strategy_name.startswith("LONG")
            else "SHORT"
        )

        if str(
            candidate.get("direction", "")
        ).upper() != direction:
            return None

        score = cls._safe_float(
            candidate.get("score")
        )

        if score is None or not 0 <= score <= 100:
            return None

        trade_plan = cls._normalize_trade_plan(
            candidate
        )

        if trade_plan is None:
            return None

        symbol = candidate.get("symbol")

        if not isinstance(symbol, str) or not symbol.strip():
            return None

        result = dict(candidate)

        result["symbol"] = symbol.strip()
        result["direction"] = direction
        result["strategy_name"] = strategy_name
        result["score"] = score
        result["trade_plan"] = trade_plan

        # Database.save_signal() 需要 strategy 字典。
        result["strategy"] = {
            "name": strategy_name,
            "direction": direction,
            "score": score,
            "candidate": True
        }

        # 保留原始策略理由及交易計畫。
        result["relative_strength"] = (
            candidate.get("relative_strength")
            if isinstance(
                candidate.get("relative_strength"),
                dict
            )
            else {}
        )

        return result

    def _save_scan_history(self, scan_result):
        """
        保存每輪完整掃描結果。
        """

        try:
            scan_id = self.database.save_scan(
                scan_result
            )

            logger.info(
                "Scan history saved: id=%s",
                scan_id
            )

            return scan_id

        except Exception:
            logger.exception(
                "Failed to save scan history"
            )

            return None

    def _save_signal_history(self, candidates):
        """
        保存四種策略的有效模擬交易訊號。
        """

        saved = 0
        failed = 0

        for candidate in candidates:
            try:
                normalized = self._normalize_candidate(
                    candidate
                )

                if normalized is None:
                    continue

                signal_id = self.database.save_signal(
                    normalized
                )

                if signal_id is not None:
                    saved += 1

            except Exception:
                failed += 1

                logger.exception(
                    "Failed to save signal history: %s",
                    candidate.get("symbol")
                )

        logger.info(
            "Signal history: saved=%s failed=%s",
            saved,
            failed
        )

        return {
            "saved": saved,
            "failed": failed
        }

    def _record_notification(
        self,
        notification_key,
        candidate,
        result
    ):
        """
        保存 LINE 通知紀錄。

        成功通知使用固定 key，供跨重啟防重複。
        失敗通知使用獨立 key，避免失敗紀錄阻止下次重試。
        """

        success = bool(
            isinstance(result, dict)
            and result.get("success")
        )

        status = (
            "sent"
            if success
            else str(
                result.get("status", "failed")
                if isinstance(result, dict)
                else "failed"
            )
        )

        if success:
            stored_key = notification_key
        else:
            stored_key = (
                notification_key
                + ":failed:"
                + datetime.now(timezone.utc).strftime(
                    "%Y%m%d%H%M%S%f"
                )
            )

        try:
            self.database.save_notification(
                notification_key=stored_key,
                symbol=candidate.get("symbol"),
                direction=candidate.get("direction"),
                message=(
                    result.get("message", "")
                    if isinstance(result, dict)
                    else ""
                ),
                status=status,
                error_message=(
                    None if success else status
                )
            )

        except Exception:
            logger.exception(
                "Failed to save notification history"
            )

    def _send_candidate_notifications(self, candidates):
        """
        發送四種策略的獨立 LINE 訊號。
        """

        sent = 0
        skipped = 0
        failed = 0

        for candidate in candidates:
            normalized = self._normalize_candidate(
                candidate
            )

            if normalized is None:
                skipped += 1
                continue

            notification_key = self._notification_key(
                normalized
            )

            try:
                # 使用資料庫檢查跨重啟重複訊號。
                if self.database.notification_exists(
                    notification_key
                ):
                    skipped += 1
                    continue

                result = self.notifier.send_signal(
                    normalized
                )

                self._record_notification(
                    notification_key,
                    normalized,
                    result
                )

                if (
                    isinstance(result, dict)
                    and result.get("success")
                ):
                    sent += 1
                else:
                    failed += 1

                    logger.warning(
                        "LINE notification failed: %s %s",
                        normalized.get("symbol"),
                        (
                            result.get("status")
                            if isinstance(result, dict)
                            else "unknown"
                        )
                    )

            except Exception:
                failed += 1

                logger.exception(
                    "Failed to process LINE notification: %s",
                    normalized.get("symbol")
                )

        summary = {
            "sent": sent,
            "skipped": skipped,
            "failed": failed
        }

        logger.info(
            "LINE signal notifications: %s",
            summary
        )

        return summary

    def _daily_summary_key(self, today):
        return f"DAILY_SUMMARY:{today.isoformat()}"

    def _send_daily_summary_if_due(self, scan_result):
        """
        每天指定台灣時間發送一次摘要。
        """

        try:
            now = datetime.now(
                ZoneInfo(Config.TIMEZONE)
            )

            today = now.date()

            if now.hour < self.summary_hour:
                return {
                    "success": False,
                    "status": "not_due"
                }

            if self._last_summary_date == today:
                return {
                    "success": False,
                    "status": "already_sent"
                }

            notification_key = self._daily_summary_key(
                today
            )

            if self.database.notification_exists(
                notification_key
            ):
                self._last_summary_date = today

                return {
                    "success": False,
                    "status": "already_sent"
                }

            result = self.notifier.send_daily_summary(
                scan_result
            )

            if not isinstance(result, dict):
                result = {
                    "success": False,
                    "status": "invalid_response"
                }

            if result.get("success"):
                self._last_summary_date = today

                self.database.save_notification(
                    notification_key=notification_key,
                    symbol="MARKET",
                    direction="SUMMARY",
                    message="Daily market summary",
                    status="sent"
                )

            else:
                failed_key = (
                    notification_key
                    + ":failed:"
                    + datetime.now(timezone.utc).strftime(
                        "%Y%m%d%H%M%S%f"
                    )
                )

                self.database.save_notification(
                    notification_key=failed_key,
                    symbol="MARKET",
                    direction="SUMMARY",
                    message="Daily market summary",
                    status=str(
                        result.get("status", "failed")
                    ),
                    error_message=str(
                        result.get("message", "Unknown error")
                    )
                )

            return result

        except Exception:
            logger.exception(
                "Failed to send daily summary"
            )

            return {
                "success": False,
                "status": "error"
            }

    def run_once(self):
        """
        執行一次市場掃描。

        如果上一輪掃描尚未完成，就不重複啟動。
        """

        if not self._scan_lock.acquire(blocking=False):
            return {
                "status": "skipped",
                "reason": "Previous scan is still running",
                "auto_trading": False
            }

        try:
            logger.info("Starting market scan")

            result = self.scanner.scan()

            if not isinstance(result, dict):
                raise TypeError(
                    "Scanner must return a dictionary"
                )

            self._last_scan_result = result

            # 不論掃描成功或失敗，都保存可追溯結果。
            self._save_scan_history(result)

            if result.get("status") != "completed":
                logger.warning(
                    "Market scan did not complete: %s",
                    result.get("error")
                )

                return result

            candidates = self._get_strategy_candidates(
                result
            )

            signal_history = self._save_signal_history(
                candidates
            )

            notification_result = (
                self._send_candidate_notifications(
                    candidates
                )
            )

            summary_result = (
                self._send_daily_summary_if_due(
                    result
                )
            )

            result["signal_history"] = signal_history
            result["notification_result"] = (
                notification_result
            )
            result["daily_summary_result"] = (
                summary_result
            )

            logger.info(
                "Market scan completed: scanned=%s "
                "successful=%s failed=%s",
                result.get("total_scanned", 0),
                result.get("successful", 0),
                result.get("failed", 0)
            )

            return result

        except Exception:
            logger.exception("Market scan failed")

            return {
                "status": "error",
                "reason": "Market scan execution failed",
                "auto_trading": False,
                "trading_mode": "simulation_only"
            }

        finally:
            self._scan_lock.release()

    def start(self):
        """
        啟動背景排程執行緒。
        """

        if self.is_running:
            return {
                "status": "already_running",
                "interval_seconds": self.interval_seconds
            }

        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run_loop,
            name="OKX-Market-Scheduler",
            daemon=True
        )

        self._thread.start()

        return {
            "status": "started",
            "interval_seconds": self.interval_seconds,
            "auto_trading": False
        }

    def _run_loop(self):
        """
        背景排程主迴圈。
        """

        while not self._stop_event.is_set():
            self.run_once()

            self._stop_event.wait(
                self.interval_seconds
            )

    def stop(self, timeout=10):
        """
        停止背景排程。
        """

        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        return {
            "status": (
                "stopped"
                if not self.is_running
                else "stopping"
            ),
            "auto_trading": False
        }

    def get_status(self):
        """
        取得排程及資料庫狀態。
        """

        try:
            database_status = self.database.health_check()
        except Exception:
            database_status = {
                "status": "error"
            }

        return {
            "running": self.is_running,
            "interval_seconds": self.interval_seconds,
            "summary_hour": self.summary_hour,
            "last_summary_date": (
                self._last_summary_date.isoformat()
                if self._last_summary_date
                else None
            ),
            "last_scan_status": (
                self._last_scan_result.get("status")
                if self._last_scan_result
                else None
            ),
            "database": database_status,
            "auto_trading": False,
            "trading_mode": "simulation_only"
        }
