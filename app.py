
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, render_template_string

from config import Config
from scanner import MarketScanner
from scheduler import TradingScheduler
from line_notifier import LineNotifier
from database import Database


APP_NAME = "OKX SMART TRADING V1.0"

app = Flask(__name__)

_scheduler = None
_scheduler_lock = threading.RLock()
_scheduler_scanner_class = None
_scheduler_started = False


def get_local_time():
    timezone_name = getattr(Config, "TIMEZONE", "Asia/Taipei")
    return datetime.now(ZoneInfo(timezone_name)).isoformat()


def get_scanner():
    max_symbols = int(
        getattr(
            Config,
            "TOP_N_SYMBOLS",
            os.getenv("TOP_N_SYMBOLS", "10"),
        )
    )

    return MarketScanner(
        max_symbols=max_symbols,
        min_relative_strength=float(
            os.getenv("MIN_RELATIVE_STRENGTH", "0")
        ),
    )


def get_scheduler():
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

        _scheduler = TradingScheduler(
            scanner=scanner,
            notifier=notifier,
            interval_seconds=int(
                getattr(Config, "SCAN_INTERVAL_SECONDS", 60)
            ),
            summary_hour=int(os.getenv("SUMMARY_HOUR", "21")),
            database=database,
        )

        _scheduler_scanner_class = MarketScanner
        return _scheduler


def start_scheduler_once():
    global _scheduler_started

    if getattr(Config, "APP_ENV", "development") != "production":
        return

    with _scheduler_lock:
        if _scheduler_started:
            return

        scheduler = get_scheduler()
        result = scheduler.start()

        if isinstance(result, dict) and result.get("status") in (
            "started",
            "already_running",
        ):
            _scheduler_started = True
            app.logger.info("背景掃描排程已啟動：%s", result)
        else:
            app.logger.error("背景掃描排程啟動失敗：%s", result)


def reset_scheduler():
    global _scheduler
    global _scheduler_scanner_class
    global _scheduler_started

    with _scheduler_lock:
        if _scheduler is not None:
            try:
                _scheduler.stop()
            except Exception:
                app.logger.exception("停止 Scheduler 失敗")

        _scheduler = None
        _scheduler_scanner_class = None
        _scheduler_started = False


def get_scan_key():
    return (
        getattr(Config, "ADMIN_API_KEY", "")
        or os.getenv("ADMIN_API_KEY", "")
        or os.getenv("SCAN_API_KEY", "")
        or ""
    )


def check_api_key():
    expected_key = get_scan_key()

    if not expected_key:
        return (
            getattr(Config, "APP_ENV", "development")
            != "production"
        )

    supplied_key = (
        request.headers.get("X-Scan-Key")
        or request.headers.get("X-API-Key")
        or request.args.get("key")
    )

    if not supplied_key:
        body = request.get_json(silent=True) or {}
        supplied_key = body.get("key", "")

    return supplied_key == expected_key


def unauthorized_response():
    return jsonify({
        "status": "error",
        "error": "unauthorized",
        "message": "未授權，請檢查管理密碼",
    }), 401


def error_response(message, status_code=500):
    return jsonify({
        "status": "error",
        "error": str(message),
        "message": str(message),
        "application": APP_NAME,
        "time": get_local_time(),
    }), status_code


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OKX SMART TRADING V1.0</title>
<style>
* { box-sizing: border-box; }

body {
    margin: 0;
    padding: 15px;
    background: #101722;
    color: #edf2f7;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
}

.container { max-width: 1100px; margin: auto; }
h1 { font-size: 23px; }
h2 { font-size: 17px; }
.subtitle { color: #9ba9ba; font-size: 13px; }

.panel {
    background: #1b2736;
    border-radius: 12px;
    padding: 14px;
    margin: 14px 0;
    min-width: 0;
}

.grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
}

input, button {
    width: 100%;
    padding: 12px;
    margin-top: 10px;
    border: 0;
    border-radius: 8px;
    font-size: 15px;
}

input { background: #263548; color: white; }

button {
    background: #2878e5;
    color: white;
    font-weight: bold;
}

button:disabled { opacity: 0.5; }

.signal {
    background: #263548;
    border-radius: 8px;
    padding: 11px;
    margin-top: 9px;
    overflow-wrap: anywhere;
}

.muted { color: #a5b3c3; font-size: 13px; }
.prices { font-size: 13px; line-height: 1.8; }

@media(max-width:650px) {
    .grid { grid-template-columns: 1fr; }
}
</style>
</head>

<body>
<div class="container">

    <h1>OKX SMART TRADING V1.0</h1>

    <div class="subtitle">
        OKX USDT 永續合約｜多空雙向掃描｜模擬訊號
    </div>

    <div class="panel">
        <strong>市場掃描</strong>
        <input id="apiKey" type="password" placeholder="輸入管理密碼">
        <button id="scanButton" onclick="runScan()">立即掃描</button>
        <div id="status" class="muted">等待掃描</div>
    </div>

    <div class="grid">
        <div class="panel">
            <h2>LONG-A 提前埋伏做多</h2>
            <div id="longA" class="muted">等待掃描</div>
        </div>

        <div class="panel">
            <h2>LONG-B 突破確認做多</h2>
            <div id="longB" class="muted">等待掃描</div>
        </div>

        <div class="panel">
            <h2>SHORT-A 提前埋伏做空</h2>
            <div id="shortA" class="muted">等待掃描</div>
        </div>

        <div class="panel">
            <h2>SHORT-B 跌破確認做空</h2>
            <div id="shortB" class="muted">等待掃描</div>
        </div>
    </div>

    <div class="panel">
        <h2>多方候選清單</h2>
        <div id="longList" class="muted">等待掃描</div>
    </div>

    <div class="panel">
        <h2>空方候選清單</h2>
        <div id="shortList" class="muted">等待掃描</div>
    </div>

    <div class="panel">
        <h2>相對 BTC 強弱標的</h2>
        <div id="strongList" class="muted">等待掃描</div>
    </div>

</div>

<script>
function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;"
    })[ch]);
}


// 修正策略名稱可能是物件而非文字的問題
function getStrategyName(strategy) {
    if (typeof strategy === "string") {
        return strategy;
    }

    if (strategy && typeof strategy === "object") {
        return (
            strategy.name ||
            strategy.strategy ||
            strategy.type ||
            strategy.code ||
            "-"
        );
    }

    return "-";
}


function getTradePlan(item) {
    if (
        item.trade_plan &&
        typeof item.trade_plan === "object"
    ) {
        return item.trade_plan;
    }

    return {};
}


function getNumberDisplay(value) {
    if (value === null || value === undefined || value === "") {
        return "-";
    }

    if (typeof value === "number" && !Number.isFinite(value)) {
        return "-";
    }

    return value;
}


function renderCandidates(id, candidates) {
    const target = document.getElementById(id);

    if (!Array.isArray(candidates) || candidates.length === 0) {
        target.innerHTML =
            '<div class="muted">目前沒有符合條件的訊號</div>';
        return;
    }

    target.innerHTML = candidates.map(item => {
        const plan = getTradePlan(item);

        const entry =
            plan.entry_price ??
            item.entry_price ??
            item.price;

        const stop =
            plan.stop_loss ??
            item.stop_loss;

        const tp1 =
            plan.tp1 ??
            plan.take_profit ??
            item.tp1 ??
            item.take_profit;

        const tp2 =
            plan.tp2 ??
            item.tp2;

        const strategyName = getStrategyName(item.strategy);

        return `
        <div class="signal">
            <strong>${escapeHtml(item.symbol || "-")}</strong>

            <div class="muted">
                ${escapeHtml(strategyName)}
                ｜${escapeHtml(item.direction || "-")}
                ｜評分 ${escapeHtml(getNumberDisplay(item.score))}
            </div>

            <div class="prices">
                進場：${escapeHtml(getNumberDisplay(entry))}<br>
                停損：${escapeHtml(getNumberDisplay(stop))}<br>
                TP1：${escapeHtml(getNumberDisplay(tp1))}<br>
                TP2：${escapeHtml(getNumberDisplay(tp2))}
            </div>
        </div>`;
    }).join("");
}


function renderSimpleList(id, candidates) {
    const target = document.getElementById(id);

    if (!Array.isArray(candidates) || candidates.length === 0) {
        target.innerHTML =
            '<div class="muted">目前沒有資料</div>';
        return;
    }

    target.innerHTML = candidates.map(item => {
        const strategyName = getStrategyName(item.strategy);

        const relativeStrength =
            item.relative_strength &&
            typeof item.relative_strength === "object"
                ? item.relative_strength
                : {};

        const rsValue =
            item.relative_strength_score ??
            relativeStrength.score ??
            item.score;

        const rsDirection =
            relativeStrength.direction ||
            item.relative_strength_direction ||
            item.direction ||
            "NEUTRAL";

        return `
        <div class="signal">
            <strong>${escapeHtml(item.symbol || "-")}</strong>
            <br>
            <span class="muted">
                ${escapeHtml(strategyName)}
                ｜${escapeHtml(rsDirection)}
                ｜評分 ${escapeHtml(getNumberDisplay(rsValue))}
            </span>
        </div>`;
    }).join("");
}


async function runScan() {
    const button = document.getElementById("scanButton");
    const status = document.getElementById("status");
    const key = document.getElementById("apiKey").value.trim();

    if (!key) {
        status.textContent = "請先輸入管理密碼";
        return;
    }

    button.disabled = true;
    status.textContent = "掃描中，請稍候……";

    try {
        const response = await fetch("/api/scan", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Scan-Key": key
            },
            body: JSON.stringify({})
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.message || data.error || "掃描失敗"
            );
        }

        renderCandidates(
            "longA",
            data.long_a_candidates || data.long_a || []
        );

        renderCandidates(
            "longB",
            data.long_b_candidates || data.long_b || []
        );

        renderCandidates(
            "shortA",
            data.short_a_candidates || data.short_a || []
        );

        renderCandidates(
            "shortB",
            data.short_b_candidates || data.short_b || []
        );

        renderCandidates(
            "longList",
            data.long_candidates || []
        );

        renderCandidates(
            "shortList",
            data.short_candidates || []
        );

        renderSimpleList(
            "strongList",
            data.strong_coins || []
        );

        status.textContent =
            "掃描狀態：" + (data.status || "-") +
            "｜掃描數量：" + (data.total_scanned ?? "-") +
            "｜成功：" + (data.successful ?? "-") +
            "｜失敗：" + (data.failed ?? "-");

    } catch (error) {
        status.textContent = "掃描錯誤：" + error.message;

    } finally {
        button.disabled = false;
    }
}
</script>

</body>
</html>
"""


@app.before_request
def initialize_production_scheduler():
    start_scheduler_once()


@app.route("/", methods=["GET"])
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/health", methods=["GET"])
def health():
    try:
        database = Database()
        db_health = database.health_check()

        return jsonify({
            "status": "ok",
            "application": APP_NAME,
            "service": APP_NAME,
            "time": get_local_time(),
            "database": db_health,
        }), 200

    except Exception as exc:
        app.logger.exception("Health check failed")

        return jsonify({
            "status": "degraded",
            "application": APP_NAME,
            "service": APP_NAME,
            "time": get_local_time(),
            "error": str(exc),
        }), 503


@app.route("/api/status", methods=["GET"])
def api_status():
    line_configured = bool(
        getattr(Config, "LINE_CHANNEL_ACCESS_TOKEN", "")
        and getattr(Config, "LINE_TO_USER_ID", "")
    )

    return jsonify({
        "status": "running",
        "application": APP_NAME,
        "service": APP_NAME,
        "trading_mode": "simulation_only",
        "simulation_only": True,
        "real_trading": False,
        "auto_trading": False,
        "line_configured": line_configured,
        "timeframes": ["1H", "4H"],
        "context_timeframes": ["1D", "1W"],
        "database_backend": getattr(
            Config, "DATABASE_BACKEND", "sqlite"
        ),
        "strategies": [
            "LONG-A",
            "LONG-B",
            "SHORT-A",
            "SHORT-B",
        ],
        "time": get_local_time(),
    })


@app.route("/api/scheduler/status", methods=["GET"])
def scheduler_status():
    if not check_api_key():
        return unauthorized_response()

    try:
        scheduler = get_scheduler()
        return jsonify(scheduler.get_status()), 200

    except Exception as exc:
        app.logger.exception("Scheduler status failed")
        return error_response(exc, 500)


@app.route("/api/scan", methods=["POST"])
def api_scan():
    if not check_api_key():
        return unauthorized_response()

    try:
        scheduler = get_scheduler()
        result = scheduler.run_once()

        if not isinstance(result, dict):
            return error_response("掃描器回傳格式錯誤", 500)

        if result.get("status") == "error":
            return jsonify(result), 500

        return jsonify(result), 200

    except Exception as exc:
        app.logger.exception("Market scan failed")
        return error_response(exc, 500)


@app.route("/api/line/test", methods=["POST"])
def api_line_test():
    if not check_api_key():
        return unauthorized_response()

    try:
        notifier = LineNotifier()
        result = notifier.send_test_message()

        success = (
            isinstance(result, dict)
            and result.get("success") is True
        )

        return jsonify(result), 200 if success else 400

    except Exception as exc:
        app.logger.exception("LINE test failed")
        return error_response(exc, 500)


@app.errorhandler(404)
def not_found(_error):
    return jsonify({
        "status": "error",
        "error": "not_found",
        "message": "找不到指定頁面",
    }), 404


@app.errorhandler(500)
def internal_error(_error):
    return jsonify({
        "status": "error",
        "error": "internal_server_error",
        "message": "伺服器內部錯誤",
    }), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
