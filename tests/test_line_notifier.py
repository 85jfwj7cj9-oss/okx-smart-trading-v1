
import requests
import pytest

from line_notifier import LineNotifier
from config import Config


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.ok = 200 <= status_code < 400

    def json(self):
        return {"message": "success"}


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse()
        self.error = error
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append({
            "args": args,
            "kwargs": kwargs
        })

        if self.error:
            raise self.error

        return self.response


@pytest.fixture
def notifier(monkeypatch):
    monkeypatch.setattr(
        Config, "LINE_ENABLED", True
    )
    monkeypatch.setattr(
        Config, "LINE_CHANNEL_ACCESS_TOKEN", "test-token"
    )
    monkeypatch.setattr(
        Config, "LINE_TO_USER_ID", "test-user"
    )

    instance = LineNotifier()
    instance.session = FakeSession()

    return instance


def sample_signal():
    return {
        "symbol": "ETH-USDT-SWAP",
        "direction": "LONG",
        "strategy": {
            "score": 85
        },
        "relative_strength": {
            "1H": 2.5,
            "4H": 4.2
        },
        "trade_plan": {
            "status": "simulation_only",
            "entry_price": 3000,
            "stop_loss": 2950,
            "take_profit": 3100,
            "position": {
                "notional_usdt": 600,
                "leverage": 5
            }
        }
    }


def test_is_configured(notifier):
    assert notifier.is_configured() is True


def test_notification_disabled(monkeypatch):
    monkeypatch.setattr(
        Config, "LINE_ENABLED", False
    )

    notifier = LineNotifier()

    result = notifier.send_text("測試訊息")

    assert result["success"] is False
    assert result["status"] == "disabled"


def test_missing_credentials(monkeypatch):
    monkeypatch.setattr(
        Config, "LINE_ENABLED", True
    )
    monkeypatch.setattr(
        Config, "LINE_CHANNEL_ACCESS_TOKEN", ""
    )
    monkeypatch.setattr(
        Config, "LINE_TO_USER_ID", ""
    )

    notifier = LineNotifier()

    result = notifier.send_text("測試訊息")

    assert result["success"] is False
    assert result["status"] == "not_configured"


def test_send_text_success(notifier):
    result = notifier.send_text("測試訊息")

    assert result["success"] is True
    assert result["status"] == "sent"

    call = notifier.session.calls[0]

    assert call["args"][0] == notifier.API_URL
    assert call["kwargs"]["headers"]["Authorization"] == (
        "Bearer test-token"
    )

    payload = call["kwargs"]["json"]

    assert payload["to"] == "test-user"
    assert payload["messages"][0]["text"] == "測試訊息"


def test_empty_message(notifier):
    result = notifier.send_text("   ")

    assert result["success"] is False
    assert result["status"] == "empty_message"
    assert len(notifier.session.calls) == 0


def test_duplicate_notification(notifier):
    first = notifier.send_text(
        "測試訊息",
        dedup_key="ETH-LONG-001"
    )

    second = notifier.send_text(
        "測試訊息",
        dedup_key="ETH-LONG-001"
    )

    assert first["success"] is True
    assert second["success"] is False
    assert second["status"] == "duplicate"
    assert len(notifier.session.calls) == 1


def test_api_error(notifier):
    notifier.session = FakeSession(
        response=FakeResponse(status_code=400)
    )

    result = notifier.send_text("測試訊息")

    assert result["success"] is False
    assert result["status"] == "api_error"
    assert result["http_status"] == 400


def test_network_error(notifier):
    notifier.session = FakeSession(
        error=requests.ConnectionError("connection failed")
    )

    result = notifier.send_text("測試訊息")

    assert result["success"] is False
    assert result["status"] == "network_error"


def test_long_message_is_truncated(notifier):
    message = "A" * 6000

    result = notifier.send_text(message)

    assert result["success"] is True

    sent_message = (
        notifier.session.calls[0]["kwargs"]["json"]
        ["messages"][0]["text"]
    )

    assert len(sent_message) <= notifier.MAX_MESSAGE_LENGTH
    assert "訊息內容過長" in sent_message


def test_send_signal_success(notifier):
    result = notifier.send_signal(sample_signal())

    assert result["success"] is True
    assert result["status"] == "sent"

    message = (
        notifier.session.calls[0]["kwargs"]["json"]
        ["messages"][0]["text"]
    )

    assert "ETH-USDT-SWAP" in message
    assert "多頭觀察訊號" in message
    assert "3000" in message
    assert "2950" in message
    assert "3100" in message
    assert "模擬交易" in message


def test_send_signal_rejects_invalid_input(notifier):
    result = notifier.send_signal(None)

    assert result["success"] is False
    assert result["status"] == "invalid_input"


def test_send_signal_rejects_neutral_direction(notifier):
    signal = sample_signal()
    signal["direction"] = "NEUTRAL"

    result = notifier.send_signal(signal)

    assert result["success"] is False
    assert result["status"] == "no_trade_signal"


def test_send_signal_requires_simulation_plan(notifier):
    signal = sample_signal()
    signal["trade_plan"]["status"] = "live"

    result = notifier.send_signal(signal)

    assert result["success"] is False
    assert result["status"] == "no_simulation_plan"


def test_send_signal_requires_complete_prices(notifier):
    signal = sample_signal()
    signal["trade_plan"]["take_profit"] = None

    result = notifier.send_signal(signal)

    assert result["success"] is False
    assert result["status"] == "incomplete_trade_plan"


def test_daily_summary_success(notifier):
    scan_result = {
        "status": "completed",
        "total_scanned": 100,
        "successful": 95,
        "failed": 5,
        "long_count": 8,
        "short_count": 4,
        "strong_coin_count": 12
    }

    result = notifier.send_daily_summary(scan_result)

    assert result["success"] is True

    message = (
        notifier.session.calls[0]["kwargs"]["json"]
        ["messages"][0]["text"]
    )

    assert "掃描幣種：100" in message
    assert "多頭候選：8" in message
    assert "空頭候選：4" in message
    assert "自動下單：關閉" in message


def test_daily_summary_rejects_incomplete_scan(notifier):
    result = notifier.send_daily_summary({
        "status": "error"
    })

    assert result["success"] is False
    assert result["status"] == "scan_not_completed"


def test_send_test_message(notifier):
    result = notifier.send_test_message()

    assert result["success"] is True

    message = (
        notifier.session.calls[0]["kwargs"]["json"]
        ["messages"][0]["text"]
    )

    assert "LINE 通知測試成功" in message
    assert "不會自動下單" in message


def test_dedup_key_only_saved_after_success(notifier):
    notifier.session = FakeSession(
        response=FakeResponse(status_code=500)
    )

    first = notifier.send_text(
        "測試訊息",
        dedup_key="TEST-001"
    )

    assert first["success"] is False
    assert "TEST-001" not in notifier.sent_keys

    notifier.session = FakeSession()

    second = notifier.send_text(
        "測試訊息",
        dedup_key="TEST-001"
    )

    assert second["success"] is True
    assert "TEST-001" in notifier.sent_keys
