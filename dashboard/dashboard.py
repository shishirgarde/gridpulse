import json
import math
import os
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent  # dashboard/ (holds web/)
PROJECT = ROOT.parent
DATA_ROOT = Path(os.getenv("GRIDPULSE_DATA_DIR", str(PROJECT / "data")))
sys.path.insert(0, str(PROJECT / "src"))
from gridpulse.grid_india import fetch_observations as fetch_grid_india_observations  # noqa: E402
from gridpulse.gridpulse_client import GridPulseClient  # noqa: E402  (after sys.path setup)

load_dotenv(PROJECT / ".env")
LOCK = threading.Lock()


def finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("A source returned a missing or non-finite value.")
    return result


def validate(record):
    origin = date.fromisoformat(record["forecast_origin"])
    history = record["demand_history_mu"]
    if len(history) != 56 or any(finite(value) < 0 for value in history):
        raise ValueError("The forecast requires 56 valid daily demand observations.")
    expected = [(origin + timedelta(days=offset)).isoformat() for offset in range(1, 8)]
    for field in ("weather_forecast", "predictions"):
        rows = record[field]
        if [row["date"] for row in rows] != expected:
            raise ValueError("The source dates do not cover the required seven days.")
        for offset, row in enumerate(rows, 1):
            keys = ("mean", "max", "min") if field == "weather_forecast" else (
                "chronos2_mu", "tcn_mu", "ensemble_mu"
            )
            for key in keys:
                finite(row[key])
            if field == "predictions" and row["horizon"] != offset:
                raise ValueError("Unexpected prediction horizon.")
    return record


def archives():
    folder = DATA_ROOT / "forecasts"
    records = []
    for path in folder.glob("gridpulse_*.json"):
        try:
            record = validate(json.loads(path.read_text(encoding="utf-8")))
            issued = datetime.fromisoformat(record["issued_at_utc"])
            if issued.tzinfo is None:
                continue
            records.append(record)
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(records, key=lambda item: datetime.fromisoformat(item["issued_at_utc"]))


def latest():
    records = archives()
    if not records:
        return None
    record = max(records, key=lambda item: item["issued_at_utc"])
    allowed = ("issued_at_utc", "forecast_origin", "demand_history_mu", "weather_forecast",
               "predictions", "inputs_fetched_at_utc")
    return {key: record[key] for key in allowed if key in record}


def fetch_observations():
    return fetch_grid_india_observations(DATA_ROOT)


def comparison(today=None, horizon=None):
    today = today or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    observations = {}
    records = archives()
    for record in records:
        origin = date.fromisoformat(record["forecast_origin"])
        for index, value in enumerate(record["demand_history_mu"]):
            observations[(origin - timedelta(days=55-index)).isoformat()] = finite(value)
    fetched = None
    try:
        cache = json.loads((DATA_ROOT / "dashboard_actuals.json").read_text(encoding="utf-8"))
        observations.update({date.fromisoformat(day).isoformat(): finite(value)
                             for day, value in cache["observations"].items()})
        fetched = cache["fetched_at_utc"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    rows = []
    for offset in range(7, 0, -1):
        target = today - timedelta(days=offset)
        candidates = []
        for record in records:
            issued = datetime.fromisoformat(record["issued_at_utc"])
            if issued.astimezone(ZoneInfo("Asia/Kolkata")).date() >= target:
                continue
            for prediction in record["predictions"]:
                if prediction["date"] == target.isoformat() and (
                    horizon is None or prediction["horizon"] == horizon
                ):
                    candidates.append((issued, record, prediction))
        chosen = max(candidates, key=lambda item: item[0]) if candidates else None
        actual = observations.get(target.isoformat())
        predicted = finite(chosen[2]["ensemble_mu"]) if chosen else None
        rows.append({"date": target.isoformat(), "actual_mu": actual,
                     "predicted_mu": predicted,
                     "error_mu": predicted-actual if predicted is not None and actual is not None else None,
                     "issued_at_utc": chosen[1]["issued_at_utc"] if chosen else None,
                     "forecast_origin": chosen[1]["forecast_origin"] if chosen else None,
                     "horizon": chosen[2]["horizon"] if chosen else None})
    errors = [abs(row["error_mu"]) for row in rows if row["error_mu"] is not None]
    return {"rows": rows, "scored_days": len(errors),
            "mae_mu": sum(errors)/len(errors) if errors else None,
            "actuals_fetched_at_utc": fetched, "archive_count": len(records),
            "latest_actual_date": max(observations, default=None)}


def refresh():
    observations = fetch_observations()
    origin = max(observations)
    days = [origin - timedelta(days=offset) for offset in range(55, -1, -1)]
    if any(day not in observations for day in days):
        raise ValueError("The latest 56-day demand window has gaps. No values were filled in.")
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    if not today - timedelta(days=4) <= origin <= today:
        raise ValueError("The demand feed is too old or future-dated for a current weather forecast.")
    response = requests.get("https://api.open-meteo.com/v1/gfs", params={
        "latitude": 28.6139, "longitude": 77.2090, "timezone": "Asia/Kolkata",
        "daily": "temperature_2m_mean,temperature_2m_max,temperature_2m_min",
        "start_date": (origin + timedelta(days=1)).isoformat(),
        "end_date": (origin + timedelta(days=7)).isoformat(),
        "temperature_unit": "celsius",
    }, timeout=60)
    response.raise_for_status()
    daily = response.json()["daily"]
    weather = [{"date": day, **{name: finite(daily[f"temperature_2m_{name}"][index])
                for name in ("mean", "max", "min")}} for index, day in enumerate(daily["time"])]
    fetched = datetime.now(timezone.utc).isoformat()
    history = [observations[day] for day in days]
    result = GridPulseClient().predict(origin.isoformat(), history, weather)
    record = validate({"forecast_origin": origin.isoformat(), "demand_history_mu": history,
                       "weather_forecast": weather, "predictions": result["predictions"],
                       "inputs_fetched_at_utc": fetched,
                       "issued_at_utc": datetime.now(timezone.utc).isoformat()})
    folder = DATA_ROOT / "forecasts"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = folder / f"gridpulse_{origin:%Y%m%d}_{stamp}.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(destination)
    return record


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type="application/json"):
        payload = json.dumps(body, allow_nan=False).encode() if content_type == "application/json" else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/api/config":
            self.send(200, {"hosted": False})
        elif self.path == "/api/dashboard":
            self.send(200, {"forecast": latest()})
        elif self.path.startswith("/api/history"):
            from urllib.parse import parse_qs, urlsplit

            parsed = urlsplit(self.path)
            if parsed.path != "/api/history":
                return self.send(404, {"error": "Not found"})
            selected = parse_qs(parsed.query).get("horizon", ["all"])[0]
            if selected not in ("all", "1", "2", "3", "4", "5", "6", "7"):
                return self.send(400, {"error": "Choose a horizon between 1 and 7."})
            self.send(200, comparison(horizon=None if selected == "all" else int(selected)))
        elif self.path in ("/", "/app.js", "/style.css", "/history.css"):
            name = "index.html" if self.path == "/" else self.path[1:]
            content_type = "text/css; charset=utf-8" if name.endswith(".css") else {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8"}[name]
            self.send(200, (ROOT / "web" / name).read_bytes(), content_type)
        else:
            self.send(404, {"error": "Not found"})

    def do_POST(self):
        if self.path not in ("/api/refresh", "/api/actuals"):
            return self.send(404, {"error": "Not found"})
        if self.headers.get("X-GridPulse-Request") != "dashboard" or self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self.send(403, {"error": "Open the local dashboard to refresh."})
        if not LOCK.acquire(blocking=False):
            return self.send(409, {"error": "A forecast refresh is already running."})
        try:
            if self.path == "/api/actuals":
                fetch_observations()
                self.send(200, {"status": "updated"})
            else:
                self.send(200, {"forecast": refresh()})
        except requests.RequestException:
            self.send(502, {"error": "A data source or forecast service could not be reached. Your saved forecast is unchanged; try again shortly."})
        except (ValueError, KeyError, TypeError, RuntimeError):
            self.send(422, {"error": "Forecast inputs or service configuration could not be validated. Check the feed coverage and server .env configuration. The saved forecast is unchanged."})
        except Exception:
            self.send(500, {"error": "Refresh failed. The saved forecast is unchanged."})
        finally:
            LOCK.release()


if __name__ == "__main__":
    port = int(os.getenv("GRIDPULSE_PORT", "8050"))
    print(f"GridPulse: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
