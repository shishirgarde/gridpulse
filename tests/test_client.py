from datetime import date, timedelta

import pytest

import gridpulse.gridpulse_client as client_module
from gridpulse.gridpulse_client import GridPulseClient

ORIGIN = date(2026, 11, 19)
WEATHER = [{"date": (ORIGIN + timedelta(days=d)).isoformat(), "mean": 20.0, "max": 26.0,
            "min": 14.0} for d in range(1, 8)]


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    # Never read a developer's real .env during tests.
    monkeypatch.setattr(client_module, "load_dotenv", lambda *a, **k: None)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MODAL_PROXY_KEY", "test-key")
    monkeypatch.setenv("MODAL_PROXY_SECRET", "test-secret")
    return GridPulseClient(url="https://example.invalid/predict")


def test_missing_credentials_fail_fast(monkeypatch):
    monkeypatch.delenv("MODAL_PROXY_KEY", raising=False)
    monkeypatch.delenv("MODAL_PROXY_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        GridPulseClient()


@pytest.mark.parametrize("history, weather", [
    ([90.0] * 55, WEATHER),
    ([90.0] * 56, WEATHER[:6]),
    ([90.0] * 56, list(reversed(WEATHER))),
])
def test_input_contract_is_checked_before_any_network_call(client, monkeypatch, history, weather):
    monkeypatch.setattr(client_module.requests, "post",
                        lambda *a, **k: pytest.fail("network must not be called"))
    with pytest.raises(ValueError):
        client.predict(ORIGIN, history, weather)


def test_predict_sends_proxy_auth_and_payload(client, monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"predictions": []}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json)
        return Response()

    monkeypatch.setattr(client_module.requests, "post", fake_post)
    assert client.predict(ORIGIN.isoformat(), [90.0] * 56, WEATHER) == {"predictions": []}
    assert captured["headers"] == {"Modal-Key": "test-key", "Modal-Secret": "test-secret"}
    assert captured["json"]["forecast_origin"] == ORIGIN.isoformat()
    assert len(captured["json"]["demand_history_mu"]) == 56
