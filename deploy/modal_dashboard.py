"""Modal app: public read-only dashboard + daily scheduled forecast writer.

Deploy: modal deploy deploy/modal_dashboard.py
Seed archives / force a run: modal run deploy/modal_dashboard.py --seed --refresh
Verify official source without writing the Volume: modal run deploy/modal_dashboard.py --check-source
"""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import modal

LOCAL_ROOT = Path(__file__).resolve().parents[1]  # repository root
SOURCE_REGION = "ap-south"
app = modal.App("gridpulse-dashboard")
volume = modal.Volume.from_name("gridpulse-dashboard-history", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("requests>=2.32,<3", "python-dotenv>=1,<2", "tzdata", "fastapi[standard]",
                 "xlrd>=2.0.1,<3")
    .env({"GRIDPULSE_DATA_DIR": "/history", "PYTHONPATH": "/app/dashboard:/app/src"})
    .add_local_file(LOCAL_ROOT / "dashboard" / "dashboard.py", "/app/dashboard/dashboard.py")
    .add_local_dir(LOCAL_ROOT / "dashboard" / "web", "/app/dashboard/web")
    .add_local_file(LOCAL_ROOT / "src" / "gridpulse" / "__init__.py", "/app/src/gridpulse/__init__.py")
    .add_local_file(LOCAL_ROOT / "src" / "gridpulse" / "gridpulse_client.py", "/app/src/gridpulse/gridpulse_client.py")
    .add_local_file(LOCAL_ROOT / "src" / "gridpulse" / "grid_india.py", "/app/src/gridpulse/grid_india.py")
)


@app.function(image=image, timeout=900, region=SOURCE_REGION)
def verify_source():
    from tempfile import TemporaryDirectory

    from gridpulse.grid_india import fetch_observations

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    with TemporaryDirectory() as folder:
        root = Path(folder)
        observations = fetch_observations(root, today)
        latest_day = max(observations)
        expected = {latest_day - timedelta(days=offset) for offset in range(56)}
        if set(observations) != expected or not today - timedelta(days=4) <= latest_day < today:
            raise ValueError("Grid-India must supply 56 consecutive, current demand observations.")
        if fetch_observations(root, today) != observations:
            raise ValueError("Grid-India observations changed during the cache verification.")
        return {
            "status": "ok",
            "observation_count": len(observations),
            "first_day": min(observations).isoformat(),
            "latest_day": latest_day.isoformat(),
            "recent_actuals_mu": {
                day.isoformat(): observations[day] for day in sorted(observations)[-7:]
            },
            "raw_report_count": len(list((root / "grid_india_reports").glob("*.xls"))),
        }


@app.function(
    image=image,
    region=SOURCE_REGION,
    volumes={"/history": volume},
    secrets=[modal.Secret.from_name("gridpulse-dashboard-proxy")],
    schedule=modal.Cron("30 14 * * *", timezone="Asia/Kolkata"),
    timeout=900,
    max_containers=1,
    retries=modal.Retries(max_retries=2, initial_delay=60, max_delay=60),
)
def daily_refresh():
    import dashboard

    volume.reload()
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    current = dashboard.latest()
    if current and datetime.fromisoformat(current["issued_at_utc"]).astimezone(
        ZoneInfo("Asia/Kolkata")
    ).date() == today:
        dashboard.fetch_observations()
        volume.commit()
        return {"status": "already_issued_today", "forecast_origin": current["forecast_origin"]}
    try:
        record = dashboard.refresh()
        volume.commit()
    except Exception as exc:
        volume.commit()
        raise RuntimeError("Daily GridPulse refresh failed; the prior archive is retained.") from exc
    return {"status": "updated", "forecast_origin": record["forecast_origin"],
            "issued_at_utc": record["issued_at_utc"], "prediction_count": len(record["predictions"])}


@app.function(image=image, volumes={"/history": volume}, max_containers=2, timeout=60)
@modal.asgi_app(label="gridpulse-dashboard")
def web():
    import threading

    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse

    import dashboard

    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    read_lock = threading.Lock()

    @api.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'"
        )
        return response

    @api.get("/api/config")
    def config():
        return {"hosted": True, "schedule": "30 14 * * *", "timezone": "Asia/Kolkata"}

    @api.get("/api/dashboard")
    def forecast():
        with read_lock:
            volume.reload()
            return {"forecast": dashboard.latest()}

    @api.get("/api/history")
    def history(horizon: str = "all"):
        if horizon not in ("all", "1", "2", "3", "4", "5", "6", "7"):
            raise HTTPException(status_code=400, detail="Choose a horizon between 1 and 7.")
        with read_lock:
            volume.reload()
            return dashboard.comparison(horizon=None if horizon == "all" else int(horizon))

    @api.get("/")
    def index():
        return FileResponse("/app/dashboard/web/index.html")

    @api.get("/{asset}")
    def static(asset: str):
        if asset not in ("app.js", "style.css", "history.css"):
            raise HTTPException(status_code=404)
        return FileResponse(Path("/app/dashboard/web") / asset)

    return api


@app.local_entrypoint()
def main(seed: bool = False, refresh: bool = False, check_source: bool = False):
    if check_source:
        print(verify_source.remote())
    if seed:
        with volume.batch_upload() as batch:
            for path in (LOCAL_ROOT / "data" / "forecasts").glob("gridpulse_*.json"):
                batch.put_file(path, f"/forecasts/{path.name}")
        print("Local forecast archives uploaded; existing remote files are not overwritten.")
    if refresh:
        print(daily_refresh.remote())
