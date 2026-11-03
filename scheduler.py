
import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from config import Config
from scanner import MarketScanner
from line_notifier import LineNotifier


logger = logging.getLogger(__name__)


class TradingScheduler:
    """
    OKX SMART TRADING V1.0

    定時市場掃描與 LINE 通知排程。
    僅提供模擬交易訊號，不執行真實下單。
    """

    def __init__(
        self,
        scanner=None,
        notifier=None,
        interval_seconds=None,
        summary_hour=21
    ):
        self.scanner = scanner or MarketScanner()
        self.notifier = notifier or LineNotifier()

        self.interval_seconds = max(
            15,
            int(
                interval_seconds
                if interval_seconds is not None
                else Config.SCAN_INTERVAL_SECONDS
            )
        )

        if not 0 <= summary_hour <= 23:
            raise ValueError("summary_hour must be between 0 and 23")

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

            if result.get("status") != "completed":
                logger.warning(
                    "Market scan did not complete: %s",
                    result.get("error")
                )
                return result

            self._send_candidate_notifications(result)
            self._send_daily_summary_if_due(result)

            logger.info(
                "Market scan completed: scanned=%s, "
                "long=%s, short=%s",
                result.get("total_scanned", 0),
                result.get("long_count", 0),
                result.get("short_count", 0)
            )

            return result

        except Exception:
            logger.exception("Market scan failed")

            return {
                "status": "error",
                "reason": "Market scan execution failed",
                "auto_trading": False
            }

        finally:
            self._scan_lock.release()

    def _send_candidate_notifications(self, scan_result):
        """
        發送多頭及空頭候選訊號。
        """

        candidates = (
            scan_result.get("long_candidates", [])
            + scan_result.get("short_candidates", [])
        )

        for candidate in candidates:
            try:
                trade_plan = candidate.get("trade_plan") or {}

                # 只通知有完整模擬交易計畫的訊號。
                if trade_plan.get("status") != "simulation_only":
                    continue

                self.notifier.send_signal(candidate)

            except Exception:
                logger.exception(
                    "Failed to send signal notification"
                )

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
                return

            if self._last_summary_date == today:
                return

            result = self.notifier.send_daily_summary(
                scan_result
            )

            if result.get("success"):
                self._last_summary_date = today

        except Exception:
            logger.exception(
                "Failed to send daily summary"
            )

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
        取得排程狀態。
        """

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
            "auto_trading": False,
            "trading_mode": "simulation_only"
        }
