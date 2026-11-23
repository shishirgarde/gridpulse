
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from chronos import Chronos2Pipeline

from .tcn_model import GridPulseTCN

CALENDAR_COLS = ("year_sin", "year_cos", "week_sin", "week_cos")


def calendar_features(dates):
    dates = pd.DatetimeIndex(dates)

    doy = dates.dayofyear.to_numpy()
    dow = dates.dayofweek.to_numpy()

    return {
        "year_sin": np.sin(2 * np.pi * doy / 365.25).astype(np.float32),
        "year_cos": np.cos(2 * np.pi * doy / 365.25).astype(np.float32),
        "week_sin": np.sin(2 * np.pi * dow / 7).astype(np.float32),
        "week_cos": np.cos(2 * np.pi * dow / 7).astype(np.float32),
    }


class GridPulseForecaster:

    def __init__(self, models_dir):
        models_dir = Path(models_dir)

        checkpoint = torch.load(
            models_dir / "gridpulse_ensemble_v1" / "tcn_checkpoint.pt",
            map_location="cpu",
            weights_only=True,
        )

        arch = checkpoint["architecture"]
        self.norm = checkpoint["normalization"]

        assert arch["history_length"] == 56
        assert arch["prediction_length"] == 7
        assert arch["future_features"] == 10

        self.tcn = GridPulseTCN(
            future_features=arch["future_features"],
            hidden=arch["hidden"],
        )

        self.tcn.load_state_dict(
            checkpoint["model_state_dict"],
            strict=True,
        )
        self.tcn.eval()

        self.chronos = Chronos2Pipeline.from_pretrained(
            str((models_dir / "chronos2_calendar_200").resolve()),
            device_map="cpu",
            torch_dtype=torch.float32,
        )

        self.chronos.model.eval()
        self.median_idx = self.chronos.quantiles.index(0.5)

    @classmethod
    def from_local(cls, models_dir):
        return cls(models_dir)

    def predict(self, forecast_origin, demand_history_mu, weather_forecast):
        origin = pd.Timestamp(forecast_origin)

        if pd.isna(origin) or origin != origin.normalize():
            raise ValueError("forecast_origin must be a calendar date")

        # Validate demand history.
        history = np.asarray(demand_history_mu, dtype=np.float32)

        if history.shape != (56,):
            raise ValueError("Exactly 56 demand observations are required")

        if not np.isfinite(history).all():
            raise ValueError("Demand history contains invalid values")

        # Validate seven future weather records.
        if len(weather_forecast) != 7:
            raise ValueError("Exactly seven weather records are required")

        future_dates = pd.date_range(
            origin + pd.Timedelta(days=1),
            periods=7,
            freq="D",
        )

        past_dates = pd.date_range(
            end=origin,
            periods=56,
            freq="D",
        )

        # Require chronological weather records.
        temperatures = []

        for expected_date, record in zip(future_dates, weather_forecast, strict=True):
            supplied_date = pd.Timestamp(record["date"])

            if supplied_date != expected_date:
                raise ValueError(
                    f"Expected weather for {expected_date.date()}, "
                    f"received {supplied_date.date()}"
                )

            temperatures.append([
                record["mean"],
                record["max"],
                record["min"],
            ])

        temperatures = np.asarray(temperatures, dtype=np.float32)

        if not np.isfinite(temperatures).all():
            raise ValueError("Weather forecast contains invalid temperatures")

        # --------------------------------------------------
        # Chronos-2: calendar-only inference contract
        # --------------------------------------------------
        chronos_input = {
            "target": history,
            "past_covariates": calendar_features(past_dates),
            "future_covariates": calendar_features(future_dates),
        }

        self.chronos.model.eval()

        with torch.inference_mode():
            result = self.chronos.predict(
                inputs=[chronos_input],
                prediction_length=7,
            )

        chronos_pred = np.asarray(result[0])[
            0, self.median_idx, :
        ].copy()

        # --------------------------------------------------
        # TCN: saved normalization and feature ordering
        # --------------------------------------------------
        norm = self.norm

        history_n = (
            (history - norm["demand_mean"]) / norm["demand_std"]
        ).astype(np.float32)

        temp_mean = np.asarray(norm["temp_mean"], dtype=np.float32)
        temp_std = np.asarray(norm["temp_std"], dtype=np.float32)

        temp_n = (temperatures - temp_mean) / temp_std

        cal = calendar_features(future_dates)

        calendar_array = np.column_stack([
            cal[col] for col in CALENDAR_COLS
        ]).astype(np.float32)

        # Three normalized temperatures, four calendar
        # features, and three temperature-availability masks.
        future_features = np.concatenate([
            temp_n,
            calendar_array,
            np.ones((7, 3), dtype=np.float32),
        ], axis=1).astype(np.float32)

        assert future_features.shape == (7, 10)

        self.tcn.eval()

        with torch.inference_mode():
            tcn_n = self.tcn(
                torch.from_numpy(history_n[None, :]),
                torch.from_numpy(future_features[None, :, :]),
            ).numpy()[0]

        tcn_pred = (
            tcn_n * norm["demand_std"] + norm["demand_mean"]
        )

        # Frozen ensemble weights.
        ensemble_pred = 0.5 * chronos_pred + 0.5 * tcn_pred

        return {
            "forecast_origin": origin.strftime("%Y-%m-%d"),
            "predictions": [
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "horizon": i + 1,
                    "chronos2_mu": float(chronos_pred[i]),
                    "tcn_mu": float(tcn_pred[i]),
                    "ensemble_mu": float(ensemble_pred[i]),
                }
                for i, date in enumerate(future_dates)
            ],
        }
