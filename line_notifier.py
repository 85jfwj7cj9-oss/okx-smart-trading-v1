
import requests

from config import Config


class LineNotifier:
    """
    OKX SMART TRADING V1.0
    LINE 訊息通知模組。

    僅發送通知，不執行任何交易。
    """

    API_URL = "https://api.line.me/v2/bot/message/push"
    MAX_MESSAGE_LENGTH = 4900

    def __init__(self):
        self.access_token = (
            Config.LINE_CHANNEL_ACCESS_TOKEN or ""
        ).strip()

        self.to_user_id = (
            Config.LINE_TO_USER_ID or ""
        ).strip()

        self.enabled = Config.LINE_ENABLED

        self.session = requests.Session()
        self.sent_keys = set()

    def is_configured(self):
        return bool(
            self.enabled
            and self.access_token
            and self.to_user_id
        )

    def send_text(self, message, dedup_key=None):
        """
        發送純文字訊息。

        dedup_key 相同時，在目前程式執行期間不重複發送。
        """

        if not self.enabled:
            return {
                "success": False,
                "status": "disabled",
                "message": "LINE notification is disabled"
            }

        if not self.access_token or not self.to_user_id:
            return {
                "success": False,
                "status": "not_configured",
                "message": "LINE credentials are missing"
            }

        message = str(message).strip()

        if not message:
            return {
                "success": False,
                "status": "empty_message"
            }

        if len(message) > self.MAX_MESSAGE_LENGTH:
            message = (
                message[:self.MAX_MESSAGE_LENGTH - 20]
                + "\n...(訊息內容過長，已截斷)"
            )

        if dedup_key:
            if dedup_key in self.sent_keys:
                return {
                    "success": False,
                    "status": "duplicate",
                    "message": "Duplicate notification skipped"
                }

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "to": self.to_user_id,
            "messages": [
                {
                    "type": "text",
                    "text": message
                }
            ]
        }

        try:
            response = self.session.post(
                self.API_URL,
                headers=headers,
                json=payload,
                timeout=15
            )

            if not response.ok:
                return {
                    "success": False,
                    "status": "api_error",
                    "http_status": response.status_code,
                    "message": "LINE API request failed"
                }

            if dedup_key:
                self.sent_keys.add(dedup_key)

            return {
                "success": True,
                "status": "sent",
                "message": "LINE notification sent"
            }

        except requests.RequestException:
            return {
                "success": False,
                "status": "network_error",
                "message": "Unable to connect to LINE API"
            }

    def send_signal(self, result):
        """
        發送單一交易訊號。
        """

        if not isinstance(result, dict):
            return {
                "success": False,
                "status": "invalid_input"
            }

        symbol = str(result.get("symbol", "UNKNOWN"))
        direction = str(
            result.get("direction", "NEUTRAL")
        ).upper()

        if direction not in ("LONG", "SHORT"):
            return {
                "success": False,
                "status": "no_trade_signal"
            }

        strategy = result.get("strategy") or {}
        trade_plan = result.get("trade_plan") or {}

        if trade_plan.get("status") != "simulation_only":
            return {
                "success": False,
                "status": "no_simulation_plan"
            }

        position = trade_plan.get("position") or {}

        entry = trade_plan.get("entry_price")
        stop = trade_plan.get("stop_loss")
        target = trade_plan.get("take_profit")

        if entry is None or stop is None or target is None:
            return {
                "success": False,
                "status": "incomplete_trade_plan"
            }

        score = strategy.get(
            "score",
            strategy.get("signal_score", 0)
        )

        relative = result.get("relative_strength") or {}

        rs_1h = relative.get("1H")
        rs_4h = relative.get("4H")

        direction_text = (
            "多頭觀察訊號"
            if direction == "LONG"
            else "空頭觀察訊號"
        )

        message = (
            "📊 OKX SMART TRADING V1.0\n"
            "━━━━━━━━━━━━━━\n"
            f"幣種：{symbol}\n"
            f"方向：{direction_text}\n"
            f"策略分數：{score}\n"
            "━━━━━━━━━━━━━━\n"
            f"參考進場：{entry}\n"
            f"停損價格：{stop}\n"
            f"停利價格：{target}\n"
            "━━━━━━━━━━━━━━\n"
            f"1H BTC 相對強度：{rs_1h}\n"
            f"4H BTC 相對強度：{rs_4h}\n"
            f"模擬倉位：{position.get('notional_usdt', 'N/A')} USDT\n"
            f"模擬槓桿：{position.get('leverage', 'N/A')}x\n"
            "━━━━━━━━━━━━━━\n"
            "⚠️ 僅供模擬交易觀察，並非下單指令。"
        )

        dedup_key = (
            f"{symbol}:{direction}:"
            f"{entry}:{stop}:{target}"
        )

        return self.send_text(
            message,
            dedup_key=dedup_key
        )

    def send_daily_summary(self, scan_result):
        """
        發送每日市場掃描摘要。
        """

        if not isinstance(scan_result, dict):
            return {
                "success": False,
                "status": "invalid_input"
            }

        if scan_result.get("status") != "completed":
            return {
                "success": False,
                "status": "scan_not_completed"
            }

        message = (
            "📈 OKX 每日市場掃描摘要\n"
            "━━━━━━━━━━━━━━\n"
            f"掃描幣種：{scan_result.get('total_scanned', 0)}\n"
            f"成功分析：{scan_result.get('successful', 0)}\n"
            f"分析失敗：{scan_result.get('failed', 0)}\n"
            "━━━━━━━━━━━━━━\n"
            f"多頭候選：{scan_result.get('long_count', 0)}\n"
            f"空頭候選：{scan_result.get('short_count', 0)}\n"
            f"BTC 相對強勢幣：{scan_result.get('strong_coin_count', 0)}\n"
            "━━━━━━━━━━━━━━\n"
            "交易模式：模擬觀察\n"
            "自動下單：關閉"
        )

        return self.send_text(message)

    def send_test_message(self):
        """
        傳送 LINE 測試訊息。
        """

        return self.send_text(
            "✅ OKX SMART TRADING V1.0\n"
            "LINE 通知測試成功！\n"
            "目前為模擬交易模式，不會自動下單。"
        )
