
import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as test_client:
        yield test_client


def test_home_page(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"OKX SMART TRADING V1.0" in response.data
    assert b"/api/scan" in response.data

    # 確認四種策略都有獨立顯示區塊
    assert b"LONG-A" in response.data
    assert b"LONG-B" in response.data
    assert b"SHORT-A" in response.data
    assert b"SHORT-B" in response.data


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "ok"
    assert data["application"] == app_module.APP_NAME
    assert "time" in data


def test_status_endpoint(client):
    response = client.get("/api/status")

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "running"
    assert data["trading_mode"] == "simulation_only"
    assert data["auto_trading"] is False
    assert data["timeframes"] == ["1H", "4H"]

    assert data["strategies"] == [
        "LONG-A",
        "LONG-B",
        "SHORT-A",
        "SHORT-B"
    ]


def test_scan_without_api_key_is_rejected(
    client, monkeypatch
):
    monkeypatch.setenv("SCAN_API_KEY", "test-secret")

    response = client.post("/api/scan")

    assert response.status_code == 401
    assert response.get_json()["status"] == "error"


def test_scan_with_wrong_api_key_is_rejected(
    client, monkeypatch
):
    monkeypatch.setenv("SCAN_API_KEY", "test-secret")

    response = client.post(
        "/api/scan",
        headers={"X-Scan-Key": "wrong-secret"}
    )

    assert response.status_code == 401


def test_scan_with_correct_api_key(
    client, monkeypatch
):
    monkeypatch.setenv("SCAN_API_KEY", "test-secret")

    class FakeScanner:
        def __init__(self, **kwargs):
            pass

        def scan(self):
            return {
                "status": "completed",
                "total_scanned": 2,
                "successful": 2,
                "failed": 0,

                "long_count": 1,
                "short_count": 1,
                "strong_coin_count": 1,

                "long_a_count": 1,
                "long_b_count": 0,
                "short_a_count": 0,
                "short_b_count": 1,

                "long_a_candidates": [
                    {
                        "symbol": "ETH-USDT-SWAP",
                        "strategy": "LONG-A",
                        "direction": "LONG",
                        "score": 85,
                        "price": 3000
                    }
                ],
                "long_b_candidates": [],
                "short_a_candidates": [],
                "short_b_candidates": [
                    {
                        "symbol": "XRP-USDT-SWAP",
                        "strategy": "SHORT-B",
                        "direction": "SHORT",
                        "score": 82,
                        "price": 0.5
                    }
                ],

                "long_candidates": [],
                "short_candidates": [],
                "strong_coins": [],
                "results": [],

                "trading_mode": "simulation_only",
                "auto_trading": False
            }

    monkeypatch.setattr(
        app_module,
        "MarketScanner",
        FakeScanner
    )

    response = client.post(
        "/api/scan",
        headers={"X-Scan-Key": "test-secret"}
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "completed"
    assert data["total_scanned"] == 2
    assert data["auto_trading"] is False

    # 確認四種策略清單都有回傳
    assert len(data["long_a_candidates"]) == 1
    assert len(data["long_b_candidates"]) == 0
    assert len(data["short_a_candidates"]) == 0
    assert len(data["short_b_candidates"]) == 1

    assert data["long_a_candidates"][0]["strategy"] == "LONG-A"
    assert data["short_b_candidates"][0]["strategy"] == "SHORT-B"


def test_scan_exception_returns_error(
    client, monkeypatch
):
    monkeypatch.setenv("SCAN_API_KEY", "test-secret")

    class BrokenScanner:
        def __init__(self, **kwargs):
            pass

        def scan(self):
            raise RuntimeError("Test scanner error")

    monkeypatch.setattr(
        app_module,
        "MarketScanner",
        BrokenScanner
    )

    response = client.post(
        "/api/scan",
        headers={"X-Scan-Key": "test-secret"}
    )

    assert response.status_code == 500

    data = response.get_json()

    assert data["status"] == "error"
    assert "Test scanner error" in data["error"]
    assert data["auto_trading"] is False
