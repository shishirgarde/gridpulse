import importlib
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "dashboard"))


def make_record(origin: date, issued_at_utc: str, base: float = 90.0) -> dict:
    """A minimal, valid forecast archive record."""
    future = [origin + timedelta(days=offset) for offset in range(1, 8)]
    return {
        "forecast_origin": origin.isoformat(),
        "issued_at_utc": issued_at_utc,
        "inputs_fetched_at_utc": issued_at_utc,
        "demand_history_mu": [base + (i % 7) for i in range(56)],
        "weather_forecast": [
            {"date": day.isoformat(), "mean": 20.0, "max": 26.0, "min": 14.0} for day in future
        ],
        "predictions": [
            {"date": day.isoformat(), "horizon": h, "chronos2_mu": base + h,
             "tcn_mu": base - h, "ensemble_mu": base}
            for h, day in enumerate(future, 1)
        ],
    }


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    """The dashboard module, pointed at an empty temporary data directory."""
    monkeypatch.setenv("GRIDPULSE_DATA_DIR", str(tmp_path))
    import dashboard as module

    module = importlib.reload(module)
    (tmp_path / "forecasts").mkdir()
    return module
