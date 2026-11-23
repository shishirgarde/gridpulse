"""Modal app serving the GridPulse ensemble behind proxy auth.

Deploy: modal deploy deploy/modal_inference.py
Smoke test: modal run deploy/modal_inference.py
"""
import modal

app = modal.App("gridpulse-ensemble-v1")

REVISION = "e2dcdfda9380130aa0c2624f4d7c641f0669c2d8"
REPO_ID = "shishirgarde/gridpulse-ensemble-v1"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgomp1")
    .uv_pip_install(
        "torch==2.7.1",
        "chronos-forecasting==2.3.2",
        "transformers==5.23.0",
        "peft==0.22.0",
        "huggingface_hub",
        "numpy",
        "pandas",
        "safetensors",
        "accelerate",
        "fastapi",
    )
    .env({
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "4",
    })
)

hf_secret = modal.Secret.from_name("huggingface-secret")


def load_forecaster():
    import os
    import sys
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def load():
        # Import PEFT before Chronos to avoid the dependency
        # detection issue encountered in our local environment.
        import torch
        import transformers

        print("PyTorch:", torch.__version__)
        print("Transformers:", transformers.__version__)
        print("CUDA available:", torch.cuda.is_available())

        assert tuple(map(int, torch.__version__.split("+")[0].split(".")[:2])) >= (2, 6)
        import peft  # noqa: F401  (import before Chronos so transformers detects PEFT)
        import transformers.utils.import_utils as iu

        iu.is_peft_available.cache_clear()

        from huggingface_hub import snapshot_download

        path = snapshot_download(
            repo_id=REPO_ID,
            revision=REVISION,
            token=os.environ["HF_TOKEN"],
            local_dir="/root/gridpulse_model",
        )

        sys.path.insert(0, str(path))

        from gridpulse.inference import GridPulseForecaster

        model = GridPulseForecaster.from_local(path)

        return model

    return load()


@app.function(
    image=image,
    secrets=[hf_secret],
    cpu=4,
    memory=8192,
    timeout=600,
)
def smoke_test():
    import numpy as np

    model = load_forecaster()

    # Synthetic inputs: only verify loading and execution.
    history = [85.0] * 56

    weather = [
        {
            "date": f"2025-01-0{i}",
            "mean": 20.0,
            "max": 25.0,
            "min": 15.0,
        }
        for i in range(1, 8)
    ]

    result = model.predict(
        forecast_origin="2024-12-31",
        demand_history_mu=history,
        weather_forecast=weather,
    )

    values = [
        row["ensemble_mu"]
        for row in result["predictions"]
    ]

    assert len(values) == 7
    assert np.isfinite(values).all()

    return {
        "status": "ok",
        "prediction_count": len(values),
        "model_revision": REVISION[:8],
    }

@app.cls(
    image=image,
    secrets=[hf_secret],
    cpu=4,
    memory=8192,
    timeout=600,
)
class GridPulseAPI:

    @modal.enter()
    def startup(self):
        self.model = load_forecaster()
        print("GridPulse models loaded and ready.")

    @modal.fastapi_endpoint(
        method="POST",
        label="gridpulse-predict",
        requires_proxy_auth=True,
    )
    def predict(self, payload: dict):
        from fastapi import HTTPException

        try:
            return self.model.predict(
                forecast_origin=payload["forecast_origin"],
                demand_history_mu=payload["demand_history_mu"],
                weather_forecast=payload["weather_forecast"],
            )

        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc


@app.local_entrypoint()
def main():
    print(smoke_test.remote())
