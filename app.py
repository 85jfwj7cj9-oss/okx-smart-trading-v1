
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, render_template_string

from config import Config
from scanner import MarketScanner

app = Flask(__name__)

APP_NAME = "OKX SMART TRADING V1.0"
TIMEZONE = os.getenv("TIMEZONE", "Asia/Taipei")

STRATEGY_PANELS = [
    {
        "key": "long_a_candidates",
        "title": "🟢 LONG-A 提前埋伏做多",
        "panel": "longAPanel",
        "list": "longAList",
        "direction": "long",
    },
    {
        "key": "long_b_candidates",
        "title": "🚀 LONG-B 突破確認做多",
        "panel": "longBPanel",
        "list": "longBList",
        "direction": "long",
    },
    {
        "key": "short_a_candidates",
        "title": "🔴 SHORT-A 提前埋伏做空",
        "panel": "shortAPanel",
        "list": "shortAList",
        "direction": "short",
    },
    {
        "key": "short_b_candidates",
        "title": "📉 SHORT-B 跌破確認做空",
        "panel": "shortBPanel",
        "list": "shortBList",
        "direction": "short",
    },
]


def current_time():
    try:
        return datetime.now(ZoneInfo(TIMEZONE)).isoformat()
    except Exception:
        return datetime.now().astimezone().isoformat()


def get_scanner():
    max_symbols = int(os.getenv("MAX_SCAN_SYMBOLS", "20"))
    min_rs = float(os.getenv("MIN_RELATIVE_STRENGTH", "0"))

    return MarketScanner(
        max_symbols=max_symbols,
        min_relative_strength=min_rs
    )


def verify_scan_key():
    expected_key = os.getenv("SCAN_API_KEY", "").strip()

    if not expected_key:
        return False, "尚未設定 SCAN_API_KEY"

    supplied_key = request.headers.get(
        "X-Scan-Key", ""
    ).strip()

    if supplied_key != expected_key:
        return False, "掃描授權碼錯誤"

    return True, None


@app.route("/")
def home():
    return render_template_string("""
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ app_name }}</title>

<style>
* { box-sizing: border-box; }

body {
    margin: 0;
    padding: 14px;
    background: #101827;
    color: white;
    font-family: Arial, sans-serif;
}

.container {
    max-width: 850px;
    margin: auto;
}

.panel {
    background: #1e293b;
    padding: 17px;
    border-radius: 14px;
    margin-bottom: 15px;
    overflow-wrap: anywhere;
}

h1 { font-size: 22px; }
h2 { font-size: 18px; margin-top: 0; }

.muted {
    color: #94a3b8;
    font-size: 13px;
}

input {
    width: 100%;
    padding: 13px;
    border-radius: 8px;
    border: 1px solid #475569;
    background: #0f172a;
    color: white;
    margin: 8px 0;
}

button {
    width: 100%;
    padding: 14px;
    border: 0;
    border-radius: 8px;
    background: #2563eb;
    color: white;
    font-size: 16px;
    font-weight: bold;
    margin-top: 10px;
}

button:disabled { opacity: .5; }

.status {
    color: #4ade80;
    font-weight: bold;
}

.error { color: #f87171; }

.card {
    background: #0f172a;
    padding: 14px;
    border-radius: 9px;
    margin: 10px 0;
    line-height: 1.7;
}

.long { border-left: 4px solid #22c55e; }
.short { border-left: 4px solid #ef4444; }
.neutral { border-left: 4px solid #64748b; }

.price {
    font-size: 19px;
    font-weight: bold;
    margin-bottom: 5px;
}

.score {
    font-weight: bold;
    color: #facc15;
}

.detail {
    color: #cbd5e1;
    font-size: 13px;
    margin-top: 5px;
}

a { color: #60a5fa; }

.summary-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
}

.summary-item {
    background: #0f172a;
    padding: 10px;
    border-radius: 8px;
    font-size: 13px;
}

@media (max-width: 420px) {
    body { padding: 9px; }
    .panel { padding: 13px; }
}
</style>
</head>

<body>
<div class="container">

<div class="panel">
    <h1>{{ app_name }}</h1>
    <p class="status">● 網頁伺服器已啟動</p>
    <p class="muted">
        交易模式：模擬觀察，不會自動下單
    </p>
    <p id="serverTime" class="muted">
        讀取系統時間中...
    </p>
    <p>
        <a href="/health">健康檢查</a> |
        <a href="/api/status">API 狀態</a>
    </p>
</div>

<div class="panel">
    <h2>市場掃描控制台</h2>
    <p class="muted">
        請輸入部署時設定的 SCAN_API_KEY，才可執行掃描。
    </p>

    <input
        id="scanKey"
        type="password"
        placeholder="輸入掃描授權碼"
        autocomplete="off"
    >

    <button id="scanButton" onclick="runScan()">
        開始掃描 OKX 市場
    </button>

    <p id="scanStatus" class="muted">
        等待掃描指令
    </p>
</div>

<div id="summary" class="panel" hidden>
    <h2>📊 掃描結果摘要</h2>
    <div id="summaryContent" class="summary-grid"></div>
</div>

<div id="longAPanel" class="panel" hidden>
    <h2>🟢 LONG-A 提前埋伏做多</h2>
    <div id="longAList"></div>
</div>

<div id="longBPanel" class="panel" hidden>
    <h2>🚀 LONG-B 突破確認做多</h2>
    <div id="longBList"></div>
</div>

<div id="shortAPanel" class="panel" hidden>
    <h2>🔴 SHORT-A 提前埋伏做空</h2>
    <div id="shortAList"></div>
</div>

<div id="shortBPanel" class="panel" hidden>
    <h2>📉 SHORT-B 跌破確認做空</h2>
    <div id="shortBList"></div>
</div>

<div id="longPanel" class="panel" hidden>
    <h2>🟢 舊版 LONG 多方候選</h2>
    <div id="longList"></div>
</div>

<div id="shortPanel" class="panel" hidden>
    <h2>🔴 舊版 SHORT 空方候選</h2>
    <div id="shortList"></div>
</div>

<div id="strongPanel" class="panel" hidden>
    <h2>⭐ BTC 相對強勢幣種</h2>
    <div id="strongList"></div>
</div>

<div id="errorPanel" class="panel" hidden>
    <h2>⚠️ 掃描錯誤</h2>
    <div id="errorList"></div>
</div>

</div>

<script>
const keyInput = document.getElementById("scanKey");
const scanButton = document.getElementById("scanButton");
const scanStatus = document.getElementById("scanStatus");

function addLine(card, text, className = "detail") {
    const div = document.createElement("div");
    div.className = className;
    div.textContent = text;
    card.appendChild(div);
}

function makeCard(item, direction) {
    const card = document.createElement("div");
    card.className = "card " + direction;

    const symbol = document.createElement("div");
    symbol.className = "price";
    symbol.textContent =
        item.symbol || item.scan_symbol || "未知幣種";
    card.appendChild(symbol);

    const score = document.createElement("div");
    score.className = "score";
    score.textContent =
        "策略評分：" + (item.score ?? "無資料") + " 分";
    card.appendChild(score);

    addLine(
        card,
        "方向：" + (item.direction || "NEUTRAL")
    );

    if (item.strategy) {
        addLine(
            card,
            "策略訊號：" +
            (item.strategy.signal || item.strategy.name || "無")
        );
    } else if (item.strategy_name) {
        addLine(card, "策略：" + item.strategy_name);
    }

    if (item.price !== undefined && item.price !== null) {
        addLine(card, "最新參考價格：" + item.price);
    }

    if (
        item.average_relative_strength_pct !== undefined &&
        item.average_relative_strength_pct !== null
    ) {
        addLine(
            card,
            "BTC 相對強度：" +
            item.average_relative_strength_pct + "%"
        );
    }

    const trade = item.trade_plan || {};

    const entry = trade.entry_price ?? item.entry_price;
    const stop = trade.stop_loss ?? item.stop_loss;
    const tp1 = trade.tp1 ?? item.tp1;
    const tp2 = trade.tp2 ?? item.tp2;
    const rr = trade.reward_risk_ratio ??
               item.reward_risk_ratio;

    addLine(
        card,
        "進場：" + (entry ?? "尚無交易計畫")
    );

    addLine(
        card,
        "停損：" + (stop ?? "尚無")
    );

    addLine(
        card,
        "TP1：" + (tp1 ?? "尚無")
    );

    addLine(
        card,
        "TP2：" + (tp2 ?? "尚無")
    );

    addLine(
        card,
        "風險報酬比：" + (rr ?? "尚無")
    );

    if (trade.status) {
        addLine(card, "交易計畫狀態：" + trade.status);
    }

    if (item.invalidation_price !== undefined &&
        item.invalidation_price !== null) {
        addLine(
            card,
            "訊號失效參考價：" + item.invalidation_price
        );
    }

    if (Array.isArray(item.reasons) && item.reasons.length > 0) {
        addLine(
            card,
            "判斷理由：" + item.reasons.join("；")
        );
    }

    addLine(
        card,
        item.simulation_only === false
            ? "注意：非模擬訊號"
            : "模式：模擬觀察，不會自動下單"
    );

    return card;
}

function renderList(elementId, panelId, items, direction) {
    const list = document.getElementById(elementId);
    const panel = document.getElementById(panelId);

    list.replaceChildren();
    panel.hidden = false;

    if (!Array.isArray(items) || items.length === 0) {
        const empty = document.createElement("p");
        empty.className = "muted";
        empty.textContent = "目前沒有符合條件的幣種";
        list.appendChild(empty);
        return;
    }

    items.forEach(item => {
        list.appendChild(makeCard(item, direction));
    });
}

function hideAllResultPanels() {
    const ids = [
        "summary",
        "longAPanel",
        "longBPanel",
        "shortAPanel",
        "shortBPanel",
        "longPanel",
        "shortPanel",
        "strongPanel",
        "errorPanel"
    ];

    ids.forEach(id => {
        document.getElementById(id).hidden = true;
    });
}

function renderSummary(data) {
    const summary = document.getElementById("summary");
    const content = document.getElementById("summaryContent");

    content.replaceChildren();
    summary.hidden = false;

    const values = [
        ["掃描幣種", data.total_scanned ?? 0],
        ["成功", data.successful ?? 0],
        ["失敗", data.failed ?? 0],
        ["LONG", data.long_count ?? 0],
        ["SHORT", data.short_count ?? 0],
        ["強勢幣", data.strong_coin_count ?? 0],
        ["LONG-A", data.long_a_count ?? 0],
        ["LONG-B", data.long_b_count ?? 0],
        ["SHORT-A", data.short_a_count ?? 0],
        ["SHORT-B", data.short_b_count ?? 0],
        ["完成時間", data.finished_at ?? "無資料"]
    ];

    values.forEach(([label, value]) => {
        const div = document.createElement("div");
        div.className = "summary-item";
        div.textContent = label + "：" + value;
        content.appendChild(div);
    });
}

function renderErrors(results) {
    const errors = (results || []).filter(
        item => item.status === "error"
    );

    if (errors.length === 0) return;

    const panel = document.getElementById("errorPanel");
    const list = document.getElementById("errorList");

    panel.hidden = false;
    list.replaceChildren();

    errors.forEach(item => {
        const p = document.createElement("p");
        p.textContent =
            (item.symbol || "未知幣種") +
            "：" + (item.error || "未知錯誤");
        list.appendChild(p);
    });
}

async function runScan() {
    const key = keyInput.value.trim();

    if (!key) {
        scanStatus.textContent = "請先輸入掃描授權碼";
        scanStatus.className = "error";
        return;
    }

    scanButton.disabled = true;
    scanStatus.textContent =
        "正在取得 OKX 行情並分析，請稍候...";
    scanStatus.className = "muted";

    hideAllResultPanels();

    try {
        const response = await fetch("/api/scan", {
            method: "POST",
            headers: {
                "X-Scan-Key": key
            }
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "掃描請求失敗");
        }

        if (data.status !== "completed") {
            throw new Error(data.error || "掃描未完成");
        }

        renderSummary(data);

        STRATEGY_PANELS.forEach(config => {
            renderList(
                config.list,
                config.panel,
                data[config.key] || [],
                config.direction
            );
        });

        // 保留舊版候選清單
        renderList(
            "longList",
            "longPanel",
            data.long_candidates || [],
            "long"
        );

        renderList(
            "shortList",
            "shortPanel",
            data.short_candidates || [],
            "short"
        );

        renderList(
            "strongList",
            "strongPanel",
            data.strong_coins || [],
            "neutral"
        );

        renderErrors(data.results);

        scanStatus.textContent = "掃描完成";
        scanStatus.className = "status";

    } catch (error) {
        scanStatus.textContent = error.message;
        scanStatus.className = "error";
    } finally {
        scanButton.disabled = false;
    }
}

async function loadStatus() {
    try {
        const response = await fetch("/health");
        const data = await response.json();

        document.getElementById("serverTime").textContent =
            "伺服器時間：" + data.time;

    } catch (error) {
        document.getElementById("serverTime").textContent =
            "無法讀取伺服器狀態";
    }
}

loadStatus();
</script>
</body>
</html>
    """, app_name=APP_NAME)


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
        "okx_market_data": "available_on_scan",
        "line_notification": (
            "configured"
            if os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
            else "not_configured"
        ),
        "scan_api_key_configured": bool(
            os.getenv("SCAN_API_KEY", "").strip()
        ),
        "timeframes": ["1H", "4H"],
        "strategies": [
            "LONG-A",
            "LONG-B",
            "SHORT-A",
            "SHORT-B"
        ],
        "time": current_time()
    })


@app.route("/api/scan", methods=["POST"])
def api_scan():
    authorized, error = verify_scan_key()

    if not authorized:
        return jsonify({
            "status": "error",
            "error": error
        }), 401

    try:
        scanner = get_scanner()
        result = scanner.scan()

        return jsonify(result)

    except Exception as exc:
        app.logger.exception("Market scan failed")

        return jsonify({
            "status": "error",
            "error": str(exc),
            "time": current_time(),
            "trading_mode": "simulation_only",
            "auto_trading": False
        }), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
