
import threading
import time
from datetime import date
from unittest.mock import Mock

import pytest

from scheduler import TradingScheduler


@pytest.fixture
def completed_scan():
    return {
        "status": "completed",
        "total_scanned": 10,
        "successful": 9,
        "failed": 1,
        "long_count": 1,
        "short_count": 1,
        "long_candidates": [
            {
                "symbol": "BTC-USDT-SWAP",
                "direction": "LONG",
                "trade_plan": {
                    "status": "simulation_only"
                }
            }
        ],
        "short_candidates": [
            {
                "symbol": "ETH-USDT-SWAP",
                "direction": "SHORT",
                "trade_plan": {
                    "status": "simulation_only"
                }
            }
        ],
        "strong_coin_count": 2
    }


@pytest.fixture
def scheduler(completed_scan):
    scanner = Mock()
    scanner.scan.return_value = completed_scan

    notifier = Mock()
    notifier.send_signal.return_value = {
        "success": True
    }
    notifier.send_daily_summary.return_value = {
        "success": True
    }

    instance = TradingScheduler(
        scanner=scanner,
        notifier=notifier,
        interval_seconds=60,
        summary_hour=21
    )

    return instance, scanner, notifier


def test_scheduler_initial_status(scheduler):
    instance, _, _ = scheduler

    status = instance.get_status()

    assert status["running"] is False
    assert status["interval_seconds"] == 60
    assert status["auto_trading"] is False
    assert status["trading_mode"] == "simulation_only"


def test_run_once_success(scheduler):
    instance, scanner, _ = scheduler

    result = instance.run_once()

    assert result["status"] == "completed"
    scanner.scan.assert_called_once()


def test_candidate_notifications(scheduler):
    instance, _, notifier = scheduler

    instance._send_candidate_notifications(
        instance.scanner.scan.return_value
    )

    assert notifier.send_signal.call_count == 2


def test_invalid_trade_plan_not_notified(scheduler):
    instance, _, notifier = scheduler

    scan_result = {
        "long_candidates": [
            {
                "symbol": "TEST-USDT-SWAP",
                "direction": "LONG",
                "trade_plan": {
                    "status": "blocked"
                }
            }
        ],
        "short_candidates": []
    }

    instance._send_candidate_notifications(scan_result)

    notifier.send_signal.assert_not_called()


def test_daily_summary_only_once(scheduler):
    instance, _, notifier = scheduler

    instance._last_summary_date = date.today()

    instance._send_daily_summary_if_due(
        instance.scanner.scan.return_value
    )

    notifier.send_daily_summary.assert_not_called()


def test_scan_error_handling(scheduler):
    instance, scanner, _ = scheduler

    scanner.scan.side_effect = RuntimeError("Test failure")

    result = instance.run_once()

    assert result["status"] == "error"
    assert result["auto_trading"] is False


def test_prevent_overlapping_scans(scheduler):
    instance, scanner, _ = scheduler

    acquired = threading.Event()
    release = threading.Event()

    def slow_scan():
        acquired.set()
        release.wait(timeout=2)
        return scanner.scan.return_value

    scanner.scan.side_effect = slow_scan

    worker = threading.Thread(
        target=instance.run_once
    )
    worker.start()

    assert acquired.wait(timeout=1)

    second_result = instance.run_once()

    assert second_result["status"] == "skipped"

    release.set()
    worker.join(timeout=2)

    assert not worker.is_alive()


def test_start_and_stop(scheduler):
    instance, _, _ = scheduler

    result = instance.start()

    assert result["status"] == "started"

    # 等待背景執行緒開始第一次掃描。
    time.sleep(0.1)

    assert instance.is_running is True

    stopped = instance.stop()

    assert stopped["status"] == "stopped"
    assert instance.is_running is False


def test_start_twice_does_not_create_duplicate_thread(scheduler):
    instance, _, _ = scheduler

    first = instance.start()
    original_thread = instance._thread

    second = instance.start()

    assert first["status"] == "started"
    assert second["status"] == "already_running"
    assert instance._thread is original_thread

    instance.stop()


def test_scheduler_interval_minimum(scheduler):
    scanner = Mock()
    notifier = Mock()

    instance = TradingScheduler(
        scanner=scanner,
        notifier=notifier,
        interval_seconds=1
    )

    assert instance.interval_seconds == 15


def test_invalid_summary_hour():
    with pytest.raises(ValueError):
        TradingScheduler(
            scanner=Mock(),
            notifier=Mock(),
            summary_hour=24
        )
