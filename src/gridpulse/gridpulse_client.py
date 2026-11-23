import os
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

DEFAULT_URL = "https://shishir-garde--gridpulse-predict.us-east.modal.run"


class GridPulseClient:
    def __init__(self, url=DEFAULT_URL, timeout=180):
        load_dotenv()

        self.url = url
        self.timeout = timeout

        self.key = os.getenv("MODAL_PROXY_KEY")
        self.secret = os.getenv("MODAL_PROXY_SECRET")

        if not self.key or not self.secret:
            raise RuntimeError(
                "Missing MODAL_PROXY_KEY or MODAL_PROXY_SECRET"
            )

    def predict(self, forecast_origin, demand_history_mu, weather_forecast):
        origin = date.fromisoformat(str(forecast_origin))

        if len(demand_history_mu) != 56:
            raise ValueError("Exactly 56 historical demand values required")

        if len(weather_forecast) != 7:
            raise ValueError("Exactly 7 weather forecast records required")

        expected_dates = [
            (origin + timedelta(days=i)).isoformat()
            for i in range(1, 8)
        ]

        received_dates = [row["date"] for row in weather_forecast]

        if received_dates != expected_dates:
            raise ValueError(
                f"Weather forecast dates must be {expected_dates}"
            )

        response = requests.post(
            self.url,
            headers={
                "Modal-Key": self.key,
                "Modal-Secret": self.secret,
            },
            json={
                "forecast_origin": origin.isoformat(),
                "demand_history_mu": list(demand_history_mu),
                "weather_forecast": weather_forecast,
            },
            timeout=self.timeout,
        )

        response.raise_for_status()
        return response.json()
