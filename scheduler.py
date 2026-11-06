
import logging
import threading
from datetime import date, datetime, timezone

from scanner import MarketScanner
from line_notifier import LineNotifier

logger = logging.getLogger(__name__)


class TradingScheduler:
    """
    OKX SMART TRADING 排程器。

    支援四種獨立策略及舊版 LONG / SHORT 候選清單。
    只發送 simulation_only 訊號，不執行真實下單。
    """

    STRATEGY_LIST_KEYS = (
        "long_a_candidates",
        "long_b_candidates",
        "short_a_candidates",
        "short_b_candidates",
    )

    def __init__(
        self,
        scanner=None,
        notifier=None,
        interval_seconds=60,
        summary_hour=21,
        database=None,
    ):
        self.scanner = scanner or MarketScanner()
        self.notifier = notifier or LineNotifier()

        self.interval_seconds = max(15, int(interval_seconds))

        if not isinstance(summary_hour, int) or not 0 <= summary_hour <= 23:
            raise ValueError("summary_hour 必須介於 0 至 23")

        self.summary_hour = summary_hour

        # 重要：不自動建立資料庫。
        # 測試環境預設不使用資料庫；正式環境應明確傳入 Database()。
        self.database = database

        self._thread = None
        self._stop_event = threading.Event()
        self._scan_lock = threading.Lock()
        self._status_lock = threading.Lock()

        self._running = False
        self._last_scan_time = None
        self._last_scan_result = None
        self._last_error = None
        self._last_summary_date = None

        self.auto_trading = False
        self.trading_mode = "simulation_only"

    @property
    def is_running(self):
        with self._status_lock:
            return self._running

    def get_status(self):
        with self._status_lock:
            return {
                "running": self._running,
                "interval_seconds": self.interval_seconds,
                "auto_trading": False,
                "trading_mode": "simulation_only",
                "last_scan_time": self._last_scan_time,
                "last_error": self._last_error,
                "last_summary_date": (
                    self._last_summary_date.isoformat()
                    if self._last_summary_date
                    else None
                ),
            }

    @staticmethod
    def _is_simulation_candidate(candidate):
        if not isinstance(candidate, dict):
            return False

        plan = candidate.get("trade_plan")

        return (
            isinstance(plan, dict)
            and plan.get("status") == "simulation_only"
        )

    @staticmethod
    def _get_strategy_name(candidate, fallback=""):
        strategy = candidate.get("strategy")

        if isinstance(strategy, str) and strategy:
            return strategy

        if isinstance(strategy, dict):
            name = strategy.get("name") or strategy.get("strategy")
            if name:
                return str(name)

        return (
            candidate.get("strategy_name")
            or candidate.get("strategy_type")
            or fallback
        )

    @classmethod
    def _get_candidate_key(cls, candidate):
        plan = candidate.get("trade_plan") or {}

        strategy = cls._get_strategy_name(candidate)

        entry = (
            plan.get("entry_price")
            or plan.get("entry")
            or candidate.get("entry_price")
            or ""
        )

        stop = (
            plan.get("stop_loss")
            or plan.get("stop")
            or candidate.get("stop_loss")
            or ""
        )

        target = (
            plan.get("take_profit")
            or plan.get("tp1")
            or candidate.get("take_profit")
            or candidate.get("tp1")
            or ""
        )

        symbol = str(candidate.get("symbol", "")).upper()
        direction = str(candidate.get("direction", "")).upper()

        return (
            f"{symbol}:{direction}:{strategy}:"
            f"{entry}:{stop}:{target}"
        )

    def _collect_candidates(self, scan_result):
        """收集新版四策略及舊版 LONG / SHORT 候選清單。"""
        if isinstance(scan_result, list):
            return scan_result

        if not isinstance(scan_result, dict):
            return []

        candidates = []
        seen = set()

        keys = (
            "long_candidates",
            "short_candidates",
            *self.STRATEGY_LIST_KEYS,
        )

        for key in keys:
            items = scan_result.get(key, [])

            if not isinstance(items, list):
                continue

            for candidate in items:
                if not isinstance(candidate, dict):
                    continue

                candidate_copy = dict(candidate)

                if not candidate_copy.get("strategy"):
                    fallback = key.replace(
                        "_candidates", ""
                    ).upper()
                    candidate_copy["strategy"] = fallback

                candidate_key = self._get_candidate_key(
                    candidate_copy
                )

                if candidate_key in seen:
                    continue

                seen.add(candidate_key)
                candidates.append(candidate_copy)

        return candidates

    def _notification_key(self, candidate):
        return self._get_candidate_key(candidate)

    def _notification_exists(self, notification_key):
        if self.database is None:
            return False

        method = getattr(
            self.database,
            "notification_exists",
            None,
        )

        if not callable(method):
            return False

        try:
            return bool(method(notification_key))
        except Exception:
            logger.exception("查詢通知紀錄失敗")
            return False

    def _record_notification(
        self,
        notification_key,
        candidate,
        result,
    ):
        if self.database is None:
            return

        method = getattr(
            self.database,
            "save_notification",
            None,
        )

        if not callable(method):
            return

        success = (
            isinstance(result, dict)
            and result.get("success") is True
        )

        try:
            method(
                notification_key=notification_key,
                symbol=candidate.get("symbol", ""),
                direction=candidate.get("direction", ""),
                message=str(
                    result.get("message", "")
                    if isinstance(result, dict)
                    else result
                ),
                status="sent" if success else "failed",
                error_message=(
                    None
                    if success
                    else str(
                        result.get("error", "通知發送失敗")
                        if isinstance(result, dict)
                        else "通知發送失敗"
                    )
                ),
            )
        except Exception:
            logger.exception("保存通知紀錄失敗")

    def _save_scan_history(self, scan_result):
        if self.database is None:
            return

        method = getattr(self.database, "save_scan", None)

        if not callable(method):
            return

        try:
            method(scan_result)
        except Exception:
            logger.exception("保存掃描紀錄失敗")

    def _save_signal_history(self, candidates):
        if self.database is None:
            return

        method = getattr(self.database, "save_signal", None)

        if not callable(method):
            return

        for candidate in candidates:
            try:
                plan = candidate.get("trade_plan") or {}
                strategy_name = self._get_strategy_name(candidate)

                direction = str(
                    candidate.get("direction", "")
                ).upper()

                strategy_data = candidate.get("strategy")

                if isinstance(strategy_data, dict):
                    strategy_info = dict(strategy_data)
                else:
                    strategy_info = {
                        "name": strategy_name,
                        "direction": direction,
                        "score": candidate.get(
                            "score",
                            candidate.get("strategy_score", 0),
                        ),
                    }

                record = {
                    "symbol": candidate.get("symbol"),
                    "strategy": strategy_info,
                    "trade_plan": plan,
                    "relative_strength": (
                        candidate.get("relative_strength") or {}
                    ),
                    "direction": direction,
                }

                method(record)

            except Exception:
                logger.exception(
                    "保存訊號紀錄失敗：%s",
                    candidate.get("symbol", "UNKNOWN"),
                )

    def _send_candidate_notifications(self, scan_result):
        candidates = self._collect_candidates(scan_result)
        notified = 0

        for candidate in candidates:
            if not self._is_simulation_candidate(candidate):
                continue

            notification_key = self._notification_key(candidate)

            if self._notification_exists(notification_key):
                continue

            try:
                result = self.notifier.send_signal(candidate)

                self._record_notification(
                    notification_key,
                    candidate,
                    result,
                )

                if (
                    isinstance(result, dict)
                    and result.get("success") is True
                ):
                    notified += 1

            except Exception:
                logger.exception(
                    "訊號通知失敗：%s",
                    candidate.get("symbol", "UNKNOWN"),
                )

        return {
            "candidate_count": len(candidates),
            "notified_count": notified,
        }

    def _send_daily_summary_if_due(self, scan_result):
        today = date.today()

        if self._last_summary_date == today:
            return

        if datetime.now().hour < self.summary_hour:
            return

        notification_key = f"DAILY_SUMMARY:{today.isoformat()}"

        if self._notification_exists(notification_key):
            self._last_summary_date = today
            return

        try:
            result = self.notifier.send_daily_summary(scan_result)

            if (
                isinstance(result, dict)
                and result.get("success") is True
            ):
                self._last_summary_date = today

                if self.database is not None:
                    method = getattr(
                        self.database,
                        "save_notification",
                        None,
                    )

                    if callable(method):
                        try:
                            method(
                                notification_key=notification_key,
                                symbol="SYSTEM",
                                direction="SUMMARY",
                                message="每日掃描摘要",
                                status="sent",
                            )
                        except Exception:
                            logger.exception(
                                "保存每日摘要紀錄失敗"
                            )

        except Exception:
            logger.exception("發送每日掃描摘要失敗")

    def run_once(self):
        if not self._scan_lock.acquire(blocking=False):
            return {
                "status": "skipped",
                "reason": "scan_already_running",
                "auto_trading": False,
            }

        try:
            scan_result = self.scanner.scan()

            if not isinstance(scan_result, dict):
                raise ValueError("scanner.scan() 必須回傳 dict")

            self._last_scan_time = datetime.now(
                timezone.utc
            ).isoformat()

            self._last_scan_result = scan_result
            self._last_error = None

            self._save_scan_history(scan_result)

            if scan_result.get("status") == "completed":
                candidates = self._collect_candidates(scan_result)

                self._save_signal_history(candidates)
                self._send_candidate_notifications(scan_result)
                self._send_daily_summary_if_due(scan_result)

            return scan_result

        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("排程掃描發生錯誤")

            return {
                "status": "error",
                "error": str(exc),
                "auto_trading": False,
                "trading_mode": "simulation_only",
            }

        finally:
            self._scan_lock.release()

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("排程主迴圈發生錯誤")

            self._stop_event.wait(self.interval_seconds)

        with self._status_lock:
            self._running = False

    def start(self):
        with self._status_lock:
            if self._running:
                return {
                    "status": "already_running",
                    "auto_trading": False,
                }

            self._stop_event.clear()
            self._running = True

            self._thread = threading.Thread(
                target=self._loop,
                name="okx-trading-scheduler",
                daemon=True,
            )

            self._thread.start()

        return {
            "status": "started",
            "interval_seconds": self.interval_seconds,
            "auto_trading": False,
            "trading_mode": "simulation_only",
        }

    def stop(self):
        with self._status_lock:
            if not self._running:
                return {
                    "status": "stopped",
                    "auto_trading": False,
                }

            self._stop_event.set()
            thread = self._thread

        if thread and thread.is_alive():
            thread.join(timeout=5)

        with self._status_lock:
            self._running = False

        return {
            "status": "stopped",
            "auto_trading": False,
        }
