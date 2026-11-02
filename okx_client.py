
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify

app = Flask(__name__)

APP_NAME = "OKX SMART TRADING V1.0"
TIMEZONE = os.getenv("TIMEZONE", "Asia/Taipei")


def current_time():
    try:
        return datetime.now(ZoneInfo(TIMEZONE)).isoformat()
    except Exception:
        return datetime.now().astimezone().isoformat()


@app.route("/")
def home():
    return f"""
    <!DOCTYPE html>
    <html lang="zh-Hant">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>{APP_NAME}</title>
        <style>
            body {{
                margin: 0;
                padding: 24px;
                background: #101827;
                color: white;
                font-family: Arial, sans-serif;
            }}
            .panel {{
                max-width: 600px;
                margin: 50px auto;
                padding: 28px;
                background: #1e293b;
                border-radius: 16px;
            }}
            .status {{
                color: #4ade80;
                font-weight: bold;
            }}
            a {{ color: #60a5fa; }}
        </style>
    </head>
    <body>
        <div class="panel">
            <h1>{APP_NAME}</h1>
            <p class="status">● 網頁伺服器已啟動</p>
            <p>系統版本：V1.0</p>
            <p>交易模式：模擬觀察，不自動下單</p>
            <p>目前階段：基礎伺服器建立</p>
            <hr>
            <p><a href="/health">系統健康檢查</a></p>
            <p><a href="/api/status">系統 API 狀態</a></p>
        </div>
    </body>
    </html>
    """


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "application": APP_NAME,
        "time": current_time()
    })


@app.route("/api/status")
def api_status():
    return jsonify({
        "application": APP_NAME,
        "version": "1.0.0",
        "status": "running",
        "trading_mode": "simulation_only",
        "auto_trading": False,
        "okx_market_data": "not_connected",
        "line_notification": "not_configured",
        "timeframes": ["1H", "4H", "1D", "1W"],
        "time": current_time()
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
