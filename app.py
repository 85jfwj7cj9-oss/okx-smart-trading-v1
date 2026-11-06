
import os
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, render_template_string

from config import Config
from scanner import MarketScanner
from scheduler import TradingScheduler
from line_notifier import LineNotifier
from database import Database


app = Flask(__name__)

_scheduler = None
_scheduler_lock = threading.RLock()
_scheduler_scanner_class = None


def get_scanner():
    """建立 OKX 市場掃描器。"""
    max_symbols = int(os.getenv("MAX_SYMBOLS", "100"))
    min_relative_strength = float(
        os.getenv("MIN_RELATIVE_STRENGTH", "0")
    )

    return MarketScanner(
        max_symbols=max_symbols,
        min_relative_strength=min_relative_strength,
    )


def get_scheduler():
    """
    取得排程器。

    當測試替換 MarketScanner 類別時，
    自動重新建立 scheduler，避免沿用舊的掃描器。
    """
    global _scheduler
    global _scheduler_scanner_class

    if (
        _scheduler is not None
        and _scheduler_scanner_class is MarketScanner
    ):
        return _scheduler

    with _scheduler_lock:
        if (
            _scheduler is not None
            and _scheduler_scanner_class is MarketScanner
        ):
            return _scheduler

        scanner = get_scanner()
        notifier = LineNotifier()
        database = Database()

        interval_seconds = int(
            os.getenv("SCAN_INTERVAL_SECONDS", "300")
        )
        summary_hour = int(
            os.getenv("SUMMARY_HOUR", "21")
        )

        _scheduler = TradingScheduler(
            scanner=scanner,
            notifier=notifier,
            interval_seconds=interval_seconds,
            summary_hour=summary_hour,
            database=database,
        )

        _scheduler_scanner_class = MarketScanner

        return _scheduler


def reset_scheduler():
    """重設排程器，供測試或管理用途使用。"""
    global _scheduler
    global _scheduler_scanner_class

    with _scheduler_lock:
        if _scheduler is not None:
            try:
                _scheduler.stop()
            except Exception:
                pass

        _scheduler = None
        _scheduler_scanner_class = None


def get_local_time():
    """取得台灣時間。"""
    return datetime.now(
        ZoneInfo("Asia/Taipei")
    ).isoformat()


def get_scan_key():
    """取得掃描 API 密碼。"""
    return (
        os.getenv("SCAN_API_KEY")
        or getattr(Config, "SCAN_API_KEY", "")
        or ""
    )


def check_api_key():
    """驗證 API 密碼。"""
    expected_key = get_scan_key()

    if not expected_key:
        return False

    supplied_key = (
        request.headers.get("X-API-Key")
        or request.args.get("key")
        or request.form.get("key")
    )

    if not supplied_key:
        data = request.get_json(silent=True) or {}
        supplied_key = data.get("key")

    return supplied_key == expected_key


def strategy_items(result, strategy_name):
    """取得指定策略的候選清單。"""
    if not isinstance(result, dict):
        return []

    items = result.get(strategy_name, [])

    if not isinstance(items, list):
        return []

    return items


def format_price(value):
    """格式化價格。"""
    if value is None:
        return "-"

    try:
        number = float(value)

        if number >= 1000:
            return f"{number:,.2f}"

        if number >= 1:
            return f"{number:.4f}"

        return f"{number:.8f}".rstrip("0").rstrip(".")

    except (TypeError, ValueError):
        return "-"


def render_candidate(candidate):
    """產生單筆策略訊號 HTML。"""
    if not isinstance(candidate, dict):
        return ""

    symbol = candidate.get("symbol", "-")
    strategy = candidate.get("strategy", "-")
    direction = candidate.get("direction", "-")
    score = candidate.get("score", 0)

    plan = candidate.get("trade_plan") or {}

    if not isinstance(plan, dict):
        plan = {}

    entry = plan.get("entry_price", candidate.get("entry_price"))
    stop = plan.get("stop_loss", candidate.get("stop_loss"))
    tp1 = plan.get(
        "tp1",
        plan.get("take_profit", candidate.get("take_profit")),
    )
    tp2 = plan.get("tp2", candidate.get("tp2"))
    rr = plan.get("risk_reward_ratio", candidate.get("risk_reward_ratio"))

    return f"""
    <div class="signal">
        <div class="signal-top">
            <strong>{symbol}</strong>
            <span>{strategy}</span>
        </div>
        <div class="meta">
            方向：{direction}
            ｜評分：{score}
        </div>
        <div class="prices">
            進場：{format_price(entry)}<br>
            停損：{format_price(stop)}<br>
            TP1：{format_price(tp1)}<br>
            TP2：{format_price(tp2)}<br>
            風險報酬比：{rr if rr is not None else "-"}
        </div>
    </div>
    """


def render_strategy_panel(title, items):
    """產生策略區塊 HTML。"""
    if not items:
        content = '<div class="empty">目前沒有符合條件的訊號</div>'
    else:
        content = "".join(
            render_candidate(item)
            for item in items
        )

    return f"""
    <section class="panel">
        <h2>{title}</h2>
        {content}
    </section>
    """


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">
    <title>OKX SMART TRADING V1.0</title>
    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            padding: 16px;
            background: #101722;
            color: #e8edf5;
            font-family: -apple-system, BlinkMacSystemFont,
                         "Segoe UI", sans-serif;
        }

        .container {
            max-width: 1100px;
            margin: auto;
        }

        h1 {
            font-size: 25px;
            margin-bottom: 6px;
        }

        h2 {
            font-size: 18px;
            margin-top: 0;
        }

        .subtitle {
            color: #9ba9ba;
            font-size: 13px;
            margin-bottom: 20px;
        }

        .toolbar {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 18px;
        }

        input, button {
            border: 0;
            border-radius: 8px;
            padding: 12px;
            font-size: 15px;
        }

        input {
            flex: 1;
            min-width: 160px;
            background: #202c3b;
            color: white;
        }

        button {
            background: #2878e5;
            color: white;
            font-weight: bold;
            cursor: pointer;
        }

        button:disabled {
            opacity: .5;
        }

        .status {
            background: #1b2736;
            border-radius: 10px;
            padding: 14px;
            margin-bottom: 16px;
            line-height: 1.8;
            overflow-wrap: anywhere;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 14px;
        }

        .panel {
            background: #1b2736;
            border-radius: 12px;
            padding: 15px;
            min-width: 0;
        }

        .signal {
            background: #263548;
            border-radius: 9px;
            padding: 12px;
            margin-bottom: 10px;
            overflow-wrap: anywhere;
        }

        .signal:last-child {
            margin-bottom: 0;
        }

        .signal-top {
            display: flex;
            justify-content: space-between;
            gap: 8px;
            font-size: 15px;
        }

        .signal-top span {
            color: #8ebcff;
        }

        .meta {
            color: #b8c5d5;
            font-size: 13px;
            margin: 8px 0;
        }

        .prices {
            font-size: 13px;
            line-height: 1.8;
            color: #e2e9f2;
        }

        .empty {
            color: #8493a6;
            font-size: 13px;
        }

        .error {
            color: #ff8585;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }

        .success {
            color: #7fe0a1;
        }

        @media (max-width: 700px) {
            body {
                padding: 12px;
            }

            h1 {
                font-size: 21px;
            }

            .grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
<div class="container">
    <h1>OKX SMART TRADING V1.0</h1>
    <div class="subtitle">
        OKX USDT 永續合約｜多空雙向掃描｜模擬訊號
    </div>

    <div class="toolbar">
        <input id="apiKey"
               type="password"
               placeholder="輸入掃描密碼">
        <button id="scanButton" onclick="runScan()">
            開始掃描
        </button>
    </div>

    <div class="status" id="status">
        系統狀態：等待掃描<br>
        請輸入 API 密碼後開始掃描。
    </div>

    <div class="grid" id="panels">
        <section class="panel">
            <h2>LONG-A 提前埋伏做多</h2>
            <div class="empty">等待掃描</div>
        </section>
        <section class="panel">
            <h2>LONG-B 突破確認做多</h2>
            <div class="empty">等待掃描</div>
        </section>
        <section class="panel">
            <h2>SHORT-A 提前埋伏做空</h2>
            <div class="empty">等待掃描</div>
        </section>
        <section class="panel">
            <h2>SHORT-B 跌破確認做空</h2>
            <div class="empty">等待掃描</div>
        </section>
    </div>
</div>

<script>
async function runScan() {
    const key = document.getElementById("apiKey").value.trim();
    const button = document.getElementById("scanButton");
    const status = document.getElementById("status");

    if (!key) {
        status.textContent = "請先輸入掃描密碼。";
        return;
    }

    button.disabled = true;
    button.textContent = "掃描中...";
    status.textContent = "正在取得 OKX 市場資料，請稍候...";

    try {
        const response = await fetch("/api/scan", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-API-Key": key
            },
            body: JSON.stringify({})
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "掃描失敗");
        }

        const names = [
            ["long_a", "LONG-A 提前埋伏做多"],
            ["long_b", "LONG-B 突破確認做多"],
            ["short_a", "SHORT-A 提前埋伏做空"],
            ["short_b", "SHORT-B 跌破確認做空"]
        ];

        document.getElementById("panels").innerHTML =
            names.map(([key, title]) => {
                const items = Array.isArray(data[key]) ? data[key] : [];

                const content = items.length
                    ? items.map(item => {
                        const plan = item.trade_plan || {};
                        const entry = plan.entry_price ?? "-";
                        const stop = plan.stop_loss ?? "-";
                        const tp1 = plan.tp1 ?? plan.take_profit ?? "-";
                        const tp2 = plan.tp2 ?? "-";
                        const rr = plan.risk_reward_ratio ?? "-";

                        return `
                            <div class="signal">
                                <div class="signal-top">
                                    <strong>${escapeHtml(item.symbol || "-")}</strong>
                                    <span>${escapeHtml(item.strategy || title)}</span>
                                </div>
                                <div class="meta">
                                    方向：${escapeHtml(item.direction || "-")}
                                    ｜評分：${escapeHtml(item.score ?? "-")}
                                </div>
                                <div class="prices">
                                    進場：${escapeHtml(entry)}<br>
                                    停損：${escapeHtml(stop)}<br>
                                    TP1：${escapeHtml(tp1)}<br>
                                    TP2：${escapeHtml(tp2)}<br>
                                    風險報酬比：${escapeHtml(rr)}
                                </div>
                            </div>
                        `;
                    }).join("")
                    : '<div class="empty">目前沒有符合條件的訊號</div>';

                return `<section class="panel"><h2>${title}</h2>${content}</section>`;
            }).join("");

        const scanned = data.total_scanned ?? "-";
        const successful = data.successful ?? "-";
        const failed = data.failed ?? "-";

        status.innerHTML = `
            <span class="success">掃描完成</span><br>
            掃描數量：${escapeHtml(scanned)}<br>
            成功：${escapeHtml(successful)}<br>
            失敗：${escapeHtml(failed)}<br>
            更新時間：${new Date().toLocaleString("zh-TW")}
        `;

    } catch (error) {
        status.innerHTML =
            '<span class="error">' +
            escapeHtml(error.message) +
            '</span>';
    } finally {
        button.disabled = false;
        button.textContent = "開始掃描";
    }
}

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;"
    })[char]);
}
</script>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    """手機版儀表板首頁。"""
    return render_template_string(DASHBOARD_HTML)


@app.route("/health", methods=["GET"])
def health():
    """服務健康檢查。"""
    try:
        database = Database()
        db_status = database.health_check()

        return jsonify({
            "status": "ok",
            "service": "OKX SMART TRADING V1.0",
            "time": get_local_time(),
            "database": db_status,
        }), 200

    except Exception as exc:
        return jsonify({
            "status": "degraded",
            "service": "OKX SMART TRADING V1.0",
            "time": get_local_time(),
            "error": str(exc),
        }), 503


@app.route("/api/status", methods=["GET"])
def api_status():
    """系統設定與服務狀態。"""
    line_configured = bool(
        getattr(Config, "LINE_CHANNEL_ACCESS_TOKEN", "")
        and getattr(Config, "LINE_TO_USER_ID", "")
    )

    return jsonify({
        "service": "OKX SMART TRADING V1.0",
        "status": "running",
        "time": get_local_time(),
        "line_configured": line_configured,
        "database_backend": getattr(
            Config, "DATABASE_BACKEND", "sqlite"
        ),
        "timeframes": ["1H", "4H", "1D", "1W"],
        "strategies": [
            "LONG-A",
            "LONG-B",
            "SHORT-A",
            "SHORT-B",
        ],
        "real_trading": False,
        "simulation_only": True,
    })


@app.route("/api/scheduler/status", methods=["GET"])
def scheduler_status():
    """排程器狀態。"""
    if not check_api_key():
        return jsonify({"error": "未授權"}), 401

    try:
        scheduler = get_scheduler()
        return jsonify(scheduler.get_status()), 200

    except Exception as exc:
        app.logger.exception("取得排程器狀態失敗")
        return jsonify({
            "error": str(exc)
        }), 500


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """執行一次市場掃描。"""
    if not check_api_key():
        return jsonify({"error": "未授權，請檢查掃描密碼"}), 401

    try:
        scheduler = get_scheduler()
        result = scheduler.run_once()

        if not isinstance(result, dict):
            return jsonify({
                "error": "掃描器回傳格式錯誤"
            }), 500

        status = result.get("status")

        if status == "error":
            return jsonify(result), 500

        return jsonify(result), 200

    except Exception as exc:
        app.logger.exception("市場掃描發生錯誤")

        return jsonify({
            "status": "error",
            "error": str(exc),
            "time": get_local_time(),
        }), 500


@app.errorhandler(404)
def not_found(_error):
    return jsonify({
        "error": "找不到指定的 API 或頁面"
    }), 404


@app.errorhandler(500)
def internal_error(_error):
    return jsonify({
        "error": "伺服器內部錯誤"
    }), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
