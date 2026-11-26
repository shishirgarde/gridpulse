import json
import threading
import urllib.error
import urllib.request
from datetime import date, timedelta
from http.server import ThreadingHTTPServer

import pytest
from conftest import make_record

ORIGIN = date(2026, 11, 14)


def save(module, record, name):
    path = module.DATA_ROOT / "forecasts" / f"gridpulse_{name}.json"
    path.write_text(json.dumps(record), encoding="utf-8")


def test_validate_accepts_a_well_formed_record(dashboard):
    record = make_record(ORIGIN, "2026-11-15T09:00:00+00:00")
    assert dashboard.validate(record) is record


@pytest.mark.parametrize("breakage", ["short_history", "nan_history", "negative", "wrong_dates",
                                      "wrong_horizon"])
def test_validate_rejects_broken_records(dashboard, breakage):
    record = make_record(ORIGIN, "2026-11-15T09:00:00+00:00")
    if breakage == "short_history":
        record["demand_history_mu"] = record["demand_history_mu"][:55]
    elif breakage == "nan_history":
        record["demand_history_mu"][10] = float("nan")
    elif breakage == "negative":
        record["demand_history_mu"][0] = -1.0
    elif breakage == "wrong_dates":
        record["weather_forecast"][0]["date"] = ORIGIN.isoformat()
    elif breakage == "wrong_horizon":
        record["predictions"][2]["horizon"] = 9
    with pytest.raises(ValueError):
        dashboard.validate(record)


def test_latest_picks_newest_valid_archive_and_whitelists_fields(dashboard):
    old = make_record(ORIGIN, "2026-11-15T09:00:00+00:00", base=80)
    new = make_record(ORIGIN + timedelta(days=1), "2026-11-16T09:00:00+00:00", base=95)
    new["internal_note"] = "must not reach the browser"
    save(dashboard, old, "old")
    save(dashboard, new, "new")
    save(dashboard, {"forecast_origin": "broken"}, "corrupt")

    latest = dashboard.latest()
    assert latest["forecast_origin"] == new["forecast_origin"]
    assert "internal_note" not in latest


def test_latest_ignores_naive_timestamps(dashboard):
    save(dashboard, make_record(ORIGIN, "2026-11-15T09:00:00"), "naive")
    assert dashboard.latest() is None


def test_comparison_only_scores_forecasts_issued_before_the_target_day(dashboard):
    # Issued 15 Nov (IST): may score 16-21 Nov, never 15 Nov itself.
    save(dashboard, make_record(ORIGIN, "2026-11-15T03:00:00+00:00", base=100), "a")
    actuals = {(ORIGIN + timedelta(days=d)).isoformat(): 104.0 for d in range(1, 8)}
    (dashboard.DATA_ROOT / "dashboard_actuals.json").write_text(
        json.dumps({"fetched_at_utc": "2026-11-22T00:00:00+00:00", "observations": actuals}))

    result = dashboard.comparison(today=date(2026, 11, 22))
    rows = {row["date"]: row for row in result["rows"]}
    assert rows["2026-11-15"]["predicted_mu"] is None
    assert rows["2026-11-16"]["predicted_mu"] == 100
    assert result["scored_days"] == 6
    assert result["mae_mu"] == pytest.approx(4.0)
    assert result["latest_actual_date"] == "2026-11-21"

    only_d3 = dashboard.comparison(today=date(2026, 11, 22), horizon=3)
    assert only_d3["scored_days"] == 1


def test_refresh_refuses_to_fill_gaps(dashboard, monkeypatch):
    today = date.today()
    observations = {today - timedelta(days=d): 90.0 for d in range(1, 70) if d != 30}
    monkeypatch.setattr(dashboard, "fetch_observations", lambda: observations)
    with pytest.raises(ValueError, match="gaps"):
        dashboard.refresh()


def test_refresh_rejects_stale_demand(dashboard, monkeypatch):
    old = date.today() - timedelta(days=30)
    observations = {old - timedelta(days=d): 90.0 for d in range(70)}
    monkeypatch.setattr(dashboard, "fetch_observations", lambda: observations)
    with pytest.raises(ValueError, match="too old"):
        dashboard.refresh()


@pytest.fixture
def server(dashboard):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_http_serves_page_and_api(server, dashboard):
    save(dashboard, make_record(ORIGIN, "2026-11-15T09:00:00+00:00"), "a")
    with urllib.request.urlopen(f"{server}/") as response:
        assert "GridPulse" in response.read().decode()
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    with urllib.request.urlopen(f"{server}/api/dashboard") as response:
        assert json.load(response)["forecast"]["forecast_origin"] == ORIGIN.isoformat()


@pytest.mark.parametrize("path", ["/.env", "/../dashboard.py", "/data/dashboard_actuals.json",
                                  "/api/history?horizon=8"])
def test_http_does_not_expose_files_or_accept_bad_input(server, path):
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(f"{server}{path}")
    assert error.value.code in (400, 404)


def test_refresh_requires_the_dashboard_header(server):
    request = urllib.request.Request(f"{server}/api/refresh", method="POST")
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 403
