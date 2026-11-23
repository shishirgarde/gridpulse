"""Checks on the committed TCN checkpoint. Skipped when torch is not installed."""

import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
from gridpulse.tcn_model import GridPulseTCN  # noqa: E402

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "gridpulse_ensemble_v1"


@pytest.fixture(scope="module")
def checkpoint():
    return torch.load(MODEL_DIR / "tcn_checkpoint.pt", map_location="cpu", weights_only=True)


def test_checkpoint_matches_the_inference_contract(checkpoint):
    arch = checkpoint["architecture"]
    assert (arch["history_length"], arch["prediction_length"], arch["future_features"]) == (56, 7, 10)
    for key in ("demand_mean", "demand_std", "temp_mean", "temp_std"):
        assert key in checkpoint["normalization"]


def test_checkpoint_loads_strictly_and_predicts_seven_days(checkpoint):
    arch = checkpoint["architecture"]
    model = GridPulseTCN(future_features=arch["future_features"], hidden=arch["hidden"])
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    model.eval()
    with torch.inference_mode():
        out = model(torch.zeros(2, 56), torch.zeros(2, 7, 10))
    assert out.shape == (2, 7)
    assert torch.isfinite(out).all()


def test_metadata_records_frozen_weights_and_validation_score():
    meta = json.loads((MODEL_DIR / "metadata.json").read_text())
    assert meta["ensemble_weights"] == {"chronos2": 0.5, "tcn": 0.5}
    assert meta["validation_mae_mu"] == pytest.approx(6.0547)
