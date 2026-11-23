"""Reproduce the headline results table from the committed prediction files.

Scores every model, plus a weekly-naive baseline, on exactly the same
origin/horizon pairs: 2024 validation (360 origins) and the 2025-26 external
test (617 origins, never seen during development).

    python scripts/evaluate_baselines.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
MODELS = ROOT / "models" / "gridpulse_ensemble_v1"

SPLITS = {
    "2024 validation": (
        "validation_2024_predictions.parquet",
        {"chronos2_lora_calendar_200": "Chronos-2 calendar LoRA", "tcn_pred": "TCN",
         "ensemble_50_50": "50/50 ensemble"},
    ),
    "2025-26 external test": (
        "external_2025_2026_predictions.parquet",
        {"chronos2_pred": "Chronos-2 calendar LoRA", "tcn_pred": "TCN",
         "ensemble_pred": "50/50 ensemble"},
    ),
}


def demand_series() -> pd.Series:
    frames = [pd.read_csv(PROCESSED / name, parse_dates=["date"])
              for name in ("gridpulse_v2_development.csv", "gridpulse_v2_external_test.csv")]
    demand = pd.concat(frames).drop_duplicates("date").set_index("date")["energy_met_mu"]
    return demand.sort_index()


def score(pred: pd.Series, actual: pd.Series) -> dict:
    error = pred - actual
    return {"MAE": error.abs().mean(), "RMSE": float(np.sqrt((error**2).mean())),
            "Bias": error.mean(), "WAPE %": 100 * error.abs().sum() / actual.abs().sum()}


def main() -> None:
    demand = demand_series()
    for split, (filename, columns) in SPLITS.items():
        pairs = pd.read_parquet(MODELS / filename)
        pairs["origin"] = pd.to_datetime(pairs["origin"])
        pairs["target_date"] = pd.to_datetime(pairs["target_date"])
        # Weekly naive: same weekday last week. Always known at the origin.
        source_day = pairs["target_date"] - pd.Timedelta(days=7)
        assert (source_day <= pairs["origin"]).all()
        pairs["weekly_naive"] = demand.reindex(source_day).to_numpy()
        columns = {"weekly_naive": "Weekly naive", **columns}

        rows = {label: score(pairs[col], pairs["actual_mu"]) for col, label in columns.items()}
        table = pd.DataFrame(rows).T.round(2)
        naive_mae = table.loc["Weekly naive", "MAE"]
        table["vs naive"] = (100 * (1 - table["MAE"] / naive_mae)).round(1).astype(str) + "%"
        print(f"\n{split}: {pairs['origin'].nunique()} origins, {len(pairs)} pairs")
        print(table.to_string())

        by_h = pairs.assign(
            ensemble=(pairs[list(columns)[-1]] - pairs["actual_mu"]).abs(),
            naive=(pairs["weekly_naive"] - pairs["actual_mu"]).abs(),
        ).groupby("horizon")[["ensemble", "naive"]].mean().round(2)
        print("MAE by horizon (days ahead):")
        print(by_h.T.to_string())


if __name__ == "__main__":
    main()
